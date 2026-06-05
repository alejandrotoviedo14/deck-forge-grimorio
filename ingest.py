#!/usr/bin/env python3
"""
ingest.py — Generador rápido de collection_enriched.json

Usa el bulk data de Scryfall (~300MB, descarga única, válido 7 días)
en lugar de llamadas individuales por carta.

USO:
    python ingest.py --real real.csv --output collection_enriched.json
    python ingest.py --real real.csv --fake fake.csv --output collection_enriched.json
    python ingest.py --real real.csv --refresh-bulk   # fuerza re-descarga

REQUISITOS:
    pip install requests pandas
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: pip install requests")
    sys.exit(1)

# Cache dir: DECK_FORGE_CACHE env var o ~/.deck_forge_cache
_CACHE_ENV = os.environ.get("DECK_FORGE_CACHE")
CACHE_DIR = Path(_CACHE_ENV) if _CACHE_ENV else Path.home() / ".deck_forge_cache"
BULK_FILE = CACHE_DIR / "scryfall_bulk.json"
BULK_META = CACHE_DIR / "scryfall_bulk_meta.json"
BULK_TTL  = 7 * 24 * 3600  # 7 días en segundos

SCRYFALL_BULK_API = "https://api.scryfall.com/bulk-data"
USER_AGENT = "DeckForgeIngest/1.0"


# ---------------------------------------------------------------------------
# Descarga del bulk data
# ---------------------------------------------------------------------------

def _bulk_is_fresh() -> bool:
    if not BULK_FILE.exists() or not BULK_META.exists():
        return False
    try:
        meta = json.loads(BULK_META.read_text())
        age = time.time() - meta.get("downloaded_at", 0)
        return age < BULK_TTL
    except Exception:
        return False


def _download_bulk(force: bool = False) -> None:
    if not force and _bulk_is_fresh():
        print("  [bulk] Cache válido, reutilizando.")
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("  [bulk] Consultando Scryfall bulk-data API...")

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    resp = session.get(SCRYFALL_BULK_API, timeout=30)
    resp.raise_for_status()
    items = resp.json().get("data", [])

    # Usamos "default_cards": una entrada por carta, sin variantes de arte
    bulk_info = next((i for i in items if i["type"] == "default_cards"), None)
    if not bulk_info:
        raise RuntimeError("No se encontró 'default_cards' en la API de bulk.")

    download_url = bulk_info["download_uri"]
    size_mb = bulk_info.get("size", 0) / 1024 / 1024
    print(f"  [bulk] Descargando {size_mb:.0f} MB desde Scryfall...")

    r = session.get(download_url, stream=True, timeout=120)
    r.raise_for_status()

    total = int(r.headers.get("content-length", 0))
    downloaded = 0
    chunks = []
    for chunk in r.iter_content(chunk_size=1024 * 1024):
        chunks.append(chunk)
        downloaded += len(chunk)
        if total:
            pct = downloaded / total * 100
            print(f"\r  [bulk] {pct:.1f}%  ({downloaded // 1024 // 1024} MB)", end="", flush=True)
    print()

    BULK_FILE.write_bytes(b"".join(chunks))
    BULK_META.write_text(json.dumps({
        "downloaded_at": time.time(),
        "updated_at": bulk_info.get("updated_at"),
        "size": downloaded,
    }))
    print(f"  [bulk] Guardado en {BULK_FILE} ({downloaded // 1024 // 1024} MB)")


def _load_bulk_index() -> dict[str, dict]:
    """Carga el bulk JSON y construye índice por scryfall_id."""
    print("  [bulk] Cargando índice en memoria...", end=" ", flush=True)
    data = json.loads(BULK_FILE.read_text(encoding="utf-8"))
    index = {card["id"]: card for card in data}
    print(f"{len(index):,} cartas indexadas.")
    return index


# ---------------------------------------------------------------------------
# Extracción de campos (mismo formato que enrich_collection.py)
# ---------------------------------------------------------------------------

def _extract(card: dict) -> dict:
    faces = card.get("card_faces", [])
    primary = faces[0] if faces else card
    type_line = card.get("type_line") or ""
    oracle = primary.get("oracle_text") or card.get("oracle_text") or ""

    return {
        "name": card.get("name"),
        "scryfall_id": card.get("id"),
        "oracle_id": card.get("oracle_id"),
        "set": card.get("set"),
        "collector_number": card.get("collector_number"),
        "mana_cost": primary.get("mana_cost") or card.get("mana_cost"),
        "cmc": card.get("cmc"),
        "type_line": type_line,
        "oracle_text": oracle,
        "power": primary.get("power") or card.get("power"),
        "toughness": primary.get("toughness") or card.get("toughness"),
        "loyalty": primary.get("loyalty") or card.get("loyalty"),
        "colors": card.get("colors") or primary.get("colors") or [],
        "color_identity": card.get("color_identity", []),
        "keywords": card.get("keywords", []),
        "produced_mana": card.get("produced_mana", []),
        "rarity": card.get("rarity"),
        "set_name": card.get("set_name"),
        "legalities": {
            "commander": card.get("legalities", {}).get("commander"),
            "vintage":   card.get("legalities", {}).get("vintage"),
        },
        "edhrec_rank": card.get("edhrec_rank"),
        "prices": {
            "eur": card.get("prices", {}).get("eur"),
            "usd": card.get("prices", {}).get("usd"),
        },
        "is_legendary": "Legendary" in type_line,
        "is_creature":  "Creature"  in type_line,
        "is_land":      "Land"      in type_line,
        "can_be_commander": (
            ("Legendary" in type_line and "Creature" in type_line)
            or "can be your commander" in oracle.lower()
            or ("partner" in oracle.lower() and "Legendary" in type_line)
        ),
        "tagger_tags": [],
    }


# ---------------------------------------------------------------------------
# Procesado de CSV
# ---------------------------------------------------------------------------

def _detect_delimiter(csv_path: Path) -> str:
    """Detecta automáticamente el delimitador del CSV (coma o punto y coma)."""
    try:
        with open(csv_path, encoding="utf-8") as f:
            first_line = f.readline()
        # Si la primera línea tiene más ';' que ',' → semicolons
        if first_line.count(";") > first_line.count(","):
            return ";"
    except Exception:
        pass
    return ","


def _process_csv(csv_path: Path, label: str, bulk_index: dict) -> list[dict]:
    """Lee un CSV de ManaBox y enriquece con datos del bulk.

    Acepta tanto CSV con comas (formato estándar ManaBox) como con punto y coma
    (exportación alternativa de ManaBox / región europea).
    """
    print(f"\n  Procesando {label}: {csv_path.name}")

    delimiter = _detect_delimiter(csv_path)
    if delimiter != ",":
        print(f"  [CSV] Delimitador detectado: '{delimiter}'")

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter=delimiter))

    # Normalizar nombres de columna: strip espacios y manejar variantes
    # Algunas exportaciones usan "Scryfall ID" otras "ScryfallID"
    normalized = []
    for row in rows:
        clean = {k.strip(): v for k, v in row.items() if k}
        normalized.append(clean)
    rows = normalized

    print(f"  {len(rows)} filas encontradas")

    enriched = []
    missing = 0

    for row in rows:
        scryfall_id = (row.get("Scryfall ID") or "").strip()
        name = (row.get("Name") or "").strip()

        card_data = bulk_index.get(scryfall_id)

        if not card_data:
            # Fallback: buscar por nombre (toma la primera coincidencia)
            card_data = next(
                (c for c in bulk_index.values() if c.get("name") == name),
                None,
            )

        if not card_data:
            print(f"    [SKIP] No encontrada en bulk: {name} ({scryfall_id})")
            missing += 1
            continue

        fields = _extract(card_data)
        fields["quantity"]  = int(row.get("Quantity", 1) or 1)
        fields["source"]    = label
        fields["foil"]      = row.get("Foil", "normal")
        fields["condition"] = row.get("Condition", "near_mint")
        fields["language"]  = row.get("Language", "en")
        enriched.append(fields)

    print(f"  {len(enriched)} cartas enriquecidas, {missing} no encontradas")
    return enriched


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Genera collection_enriched.json desde CSV de ManaBox + Scryfall bulk",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--real",  required=True, help="CSV de cartas reales (ManaBox export)")
    parser.add_argument("--fake",  default=None,  help="CSV de proxies a excluir (opcional)")
    parser.add_argument("--output", default="collection_enriched.json")
    parser.add_argument("--refresh-bulk", action="store_true",
                        help="Fuerza re-descarga del bulk de Scryfall")
    args = parser.parse_args()

    real_path = Path(args.real)
    if not real_path.exists():
        print(f"ERROR: no existe {real_path}")
        sys.exit(1)

    fake_path = Path(args.fake) if args.fake else None
    if fake_path and not fake_path.exists():
        print(f"ERROR: no existe {fake_path}")
        sys.exit(1)

    print("=== Deck Forge Ingest ===")
    print(f"Cache dir: {CACHE_DIR}")

    _download_bulk(force=args.refresh_bulk)
    bulk_index = _load_bulk_index()

    real_cards = _process_csv(real_path, "real", bulk_index)
    fake_cards = _process_csv(fake_path, "fake", bulk_index) if fake_path else []

    # ── Enriquecer con tags funcionales (tagger_cache) ─────────────────────
    tagger_enabled = False
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.tagger_cache import build_tag_index, enrich_card_with_tags
        print("\n  [TAGGER] Cargando índice de tags funcionales...")
        tag_index = build_tag_index(verbose=True)
        tagged = 0
        for card in real_cards + fake_cards:
            prev = len(card.get("tagger_tags") or [])
            enrich_card_with_tags(card, tag_index)
            if len(card.get("tagger_tags") or []) > prev:
                tagged += 1
        tagger_enabled = True
        print(f"  [TAGGER] {tagged}/{len(real_cards)} cartas con tags funcionales asignados")
    except Exception as e:
        print(f"  [TAGGER] No disponible: {e}")

    output = {
        "metadata": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tagger_enabled": tagger_enabled,
            "real_count_unique": len(real_cards),
            "fake_count_unique": len(fake_cards),
            "real_count_total": sum(c["quantity"] for c in real_cards),
            "fake_count_total": sum(c["quantity"] for c in fake_cards),
        },
        "real": real_cards,
        "fake": fake_cards,
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✓ {out_path} generado")
    print(f"  Real: {len(real_cards)} cartas únicas")
    print(f"  Fake: {len(fake_cards)} cartas excluidas")


if __name__ == "__main__":
    main()
