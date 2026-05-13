#!/usr/bin/env python3
"""
enrich_collection.py — v2 con Scryfall Tagger
----------------------------------------------
Enriquece tus exports de ManaBox (real + fake) con datos de Scryfall
y, opcionalmente, con function tags de Scryfall Tagger.

USO:
    # Solo Scryfall (igual que v1)
    python3 enrich_collection.py \\
        --real /ruta/a/real.csv \\
        --fake /ruta/a/fake.csv \\
        --output collection_enriched.json

    # Con Scryfall Tagger (auto-detección de cookie — recomendado)
    python3 enrich_collection.py \
        --real real.csv --fake fake.csv \
        --output collection_enriched.json \
        --tagger

    # Con cookie manual (si la auto-detección no funciona)
    python3 enrich_collection.py \
        --real real.csv --fake fake.csv \
        --output collection_enriched.json \
        --tagger --tagger-session "YOUR_SESSION_COOKIE"

SCRYFALL TAGGER:
    La API de Tagger requiere sesión autenticada. El script intenta obtener
    la cookie automáticamente desde Chrome, Edge, Brave o Firefox.

    Para que funcione la auto-detección:
    1. pip install browser-cookie3
    2. Estar logueado en https://tagger.scryfall.com en cualquier navegador.
    3. Ejecutar con --tagger sin --tagger-session.

    Si la auto-detección falla, obtener la cookie manualmente:
    1. Ve a https://tagger.scryfall.com y haz login.
    2. F12 → Application → Cookies → tagger.scryfall.com → _scryfall_session.
    3. Pasar con --tagger-session "VALOR".

    Si --tagger no se pasa, el script funciona sin Tagger (solo Scryfall API).
    Si la cookie falla, se usan heurísticas de oracle_text como fallback.

TAGS QUÉ SON:
    Los function tags son etiquetas semánticas como:
    "ramp", "card-draw", "removal", "board-wipe", "counter-spell",
    "tribal", "blink", "landfall", "lifegain", "reanimator", etc.
    Son mucho más precisos que las heurísticas de oracle_text.

REQUISITOS:
    pip install requests pandas

CACHE:
    Scryfall: ~/.scryfall_cache/<scryfall_id>.json
    Tagger:   ~/.tagger_cache/<set>_<number>.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import pandas as pd
    import requests
except ImportError:
    print("ERROR: faltan dependencias. Ejecuta: pip install requests pandas")
    sys.exit(1)


SCRYFALL_API  = "https://api.scryfall.com"
TAGGER_API    = "https://tagger.scryfall.com/api/card"
TAGGER_DOMAIN = "tagger.scryfall.com"

CACHE_DIR        = Path.home() / ".scryfall_cache"
TAGGER_CACHE_DIR = Path.home() / ".tagger_cache"

RATE_LIMIT_MS        = 100   # Scryfall recomienda 50-100ms
TAGGER_RATE_LIMIT_MS = 200   # Tagger es más sensible, usamos 200ms

USER_AGENT = "AlexMTGCollectionEnricher/2.0"


# ---------------------------------------------------------------------------
# Auto-detección de cookie desde el navegador
# ---------------------------------------------------------------------------

def _find_tagger_cookie_in_browser() -> str | None:
    """
    Intenta leer _scryfall_session de tagger.scryfall.com directamente
    desde Chrome, Edge, Firefox o Brave instalados en el sistema.

    Devuelve el valor de la cookie, o None si no la encuentra.
    Requiere: pip install browser-cookie3
    """
    try:
        import browser_cookie3
    except ImportError:
        print("  [INFO] pip install browser-cookie3 para auto-detección de cookie.")
        return None

    browsers = [
        ("Chrome",  browser_cookie3.Chrome),
        ("Edge",    browser_cookie3.Edge),
        ("Brave",   browser_cookie3.Brave),
        ("Firefox", browser_cookie3.Firefox),
    ]

    for browser_name, browser_fn in browsers:
        try:
            jar = browser_fn(domain_name=TAGGER_DOMAIN)
            for cookie in jar:
                if cookie.name == "_scryfall_session" and TAGGER_DOMAIN in cookie.domain:
                    print(f"  Cookie encontrada en {browser_name}.")
                    return cookie.value
        except Exception:
            continue  # Navegador no instalado o perfil bloqueado

    return None


# ---------------------------------------------------------------------------
# Scryfall
# ---------------------------------------------------------------------------

def get_card_from_scryfall(scryfall_id: str, session: requests.Session) -> dict | None:
    """Recupera una carta por Scryfall ID, con cache local."""
    cache_file = CACHE_DIR / f"{scryfall_id}.json"
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    url = f"{SCRYFALL_API}/cards/{scryfall_id}"
    try:
        resp = session.get(url, timeout=15)
        time.sleep(RATE_LIMIT_MS / 1000)
        if resp.status_code == 404:
            print(f"  [WARN] Scryfall ID no encontrado: {scryfall_id}")
            return None
        resp.raise_for_status()
        data = resp.json()
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return data
    except requests.RequestException as e:
        print(f"  [ERROR] {scryfall_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Scryfall Tagger
# ---------------------------------------------------------------------------

def get_tagger_tags(
    set_code: str,
    collector_number: str,
    session: requests.Session,
    *,
    verbose: bool = False,
) -> list[str]:
    """
    Recupera los function tags de Scryfall Tagger para una carta.

    Devuelve lista de strings tipo ["ramp", "card-draw", "landfall", ...].
    Si la API falla (403, timeout, parse error), devuelve [] sin romper.

    La Tagger API devuelve una estructura con "relationships" donde cada
    relación tiene tag.name y tag.type == "FUNCTIONAL".
    """
    if not set_code or not collector_number:
        return []

    # Normalizar: set lower, number sin ceros a la izquierda para algunos sets
    set_code = set_code.lower().strip()
    collector_number = str(collector_number).strip()

    cache_key = f"{set_code}_{collector_number}"
    cache_file = TAGGER_CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    url = f"{TAGGER_API}/{set_code}/{collector_number}"
    try:
        resp = session.get(url, timeout=10)
        time.sleep(TAGGER_RATE_LIMIT_MS / 1000)

        if resp.status_code == 403:
            if verbose:
                print(f"  [TAGGER] 403 — sesión inválida o no autenticado para {set_code}/{collector_number}")
            return []
        if resp.status_code == 404:
            # Carta no indexada en Tagger (normal para cartas viejas/oscuras)
            tags: list[str] = []
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(tags, f)
            return tags

        resp.raise_for_status()
        data = resp.json()

        # Extraer function tags de la estructura de Tagger
        # La API devuelve: { "relationships": [ { "tag": { "name": "ramp", "type": "FUNCTIONAL" }, ... } ] }
        # O en algunos casos: { "tags": [ { "name": "ramp", "type": "FUNCTIONAL" } ] }
        tags = _parse_tagger_response(data)

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(tags, f)
        return tags

    except requests.RequestException as e:
        if verbose:
            print(f"  [TAGGER] Error {set_code}/{collector_number}: {e}")
        return []
    except (KeyError, ValueError, TypeError) as e:
        if verbose:
            print(f"  [TAGGER] Parse error {set_code}/{collector_number}: {e}")
        return []


def _parse_tagger_response(data: dict) -> list[str]:
    """
    Extrae function tags del JSON de Tagger.

    Tagger usa dos formatos según la versión del endpoint:
      v1: data["relationships"] = [{"tag": {"name": "...", "type": "FUNCTIONAL"}}]
      v2: data["tags"] = [{"name": "...", "type": "FUNCTIONAL"}]
    """
    tags: list[str] = []

    # Formato v1: relationships con tag anidado
    for rel in data.get("relationships", []):
        tag = rel.get("tag", {})
        if tag.get("type", "").upper() in ("FUNCTIONAL", "THEMATICS"):
            name = tag.get("name", "").strip().lower()
            if name:
                tags.append(name)

    # Formato v2: tags directos
    for tag in data.get("tags", []):
        if tag.get("type", "").upper() in ("FUNCTIONAL", "THEMATICS"):
            name = tag.get("name", "").strip().lower()
            if name and name not in tags:
                tags.append(name)

    return tags


# ---------------------------------------------------------------------------
# Extracción de campos Scryfall
# ---------------------------------------------------------------------------

def extract_relevant_fields(card: dict) -> dict:
    """Extrae los campos útiles para construcción de mazos."""
    faces = card.get("card_faces", [])
    primary = faces[0] if faces else card

    return {
        "name": card.get("name"),
        "scryfall_id": card.get("id"),
        "oracle_id": card.get("oracle_id"),
        "set": card.get("set"),
        "collector_number": card.get("collector_number"),
        "mana_cost": primary.get("mana_cost") or card.get("mana_cost"),
        "cmc": card.get("cmc"),
        "type_line": card.get("type_line"),
        "oracle_text": primary.get("oracle_text") or card.get("oracle_text"),
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
            "vintage": card.get("legalities", {}).get("vintage"),
        },
        "edhrec_rank": card.get("edhrec_rank"),
        "prices": {
            "eur": card.get("prices", {}).get("eur"),
            "usd": card.get("prices", {}).get("usd"),
        },
        "is_legendary": "Legendary" in (card.get("type_line") or ""),
        "is_creature": "Creature" in (card.get("type_line") or ""),
        "is_land": "Land" in (card.get("type_line") or ""),
        "can_be_commander": (
            "Legendary" in (card.get("type_line") or "")
            and "Creature" in (card.get("type_line") or "")
        ) or (
            "can be your commander" in (card.get("oracle_text") or "").lower()
        ) or (
            "partner" in (card.get("oracle_text") or "").lower()
            and "Legendary" in (card.get("type_line") or "")
        ),
        # Tagger tags se añaden después (inicialmente vacío)
        "tagger_tags": [],
    }


# ---------------------------------------------------------------------------
# Procesado de CSV
# ---------------------------------------------------------------------------

def process_csv(
    csv_path: Path,
    source_label: str,
    scryfall_session: requests.Session,
    tagger_session: requests.Session | None,
    *,
    verbose_tagger: bool = False,
) -> list[dict]:
    """Lee CSV de ManaBox, enriquece cada carta, devuelve lista de dicts."""
    print(f"\n=== Procesando {source_label}: {csv_path.name} ===")
    df = pd.read_csv(csv_path)
    print(f"  {len(df)} filas, {df['Quantity'].sum()} cartas totales")
    if tagger_session:
        print(f"  Tagger: ACTIVADO (se añadirán function tags)")
    else:
        print(f"  Tagger: desactivado (pasa --tagger para activar)")

    enriched = []
    tagger_hits = 0
    tagger_misses = 0
    total = len(df)

    for idx, row in df.iterrows():
        scryfall_id = row.get("Scryfall ID")
        if pd.isna(scryfall_id):
            print(f"  [SKIP] Fila {idx} sin Scryfall ID: {row.get('Name')}")
            continue

        if (idx + 1) % 50 == 0 or idx == total - 1:
            tagger_info = f", tagger hits: {tagger_hits}" if tagger_session else ""
            print(f"  Progreso: {idx + 1}/{total}{tagger_info}")

        card_data = get_card_from_scryfall(scryfall_id, scryfall_session)
        if card_data is None:
            continue

        fields = extract_relevant_fields(card_data)
        fields["quantity"] = int(row.get("Quantity", 1))
        fields["source"] = source_label
        fields["foil"] = row.get("Foil", "normal")
        fields["condition"] = row.get("Condition", "near_mint")
        fields["language"] = row.get("Language", "en")

        # Tagger tags (opcional)
        if tagger_session is not None:
            set_code = card_data.get("set", "")
            collector_number = card_data.get("collector_number", "")
            tags = get_tagger_tags(
                set_code, collector_number, tagger_session,
                verbose=verbose_tagger,
            )
            fields["tagger_tags"] = tags
            if tags:
                tagger_hits += 1
            else:
                tagger_misses += 1

        enriched.append(fields)

    if tagger_session:
        print(f"  Tagger: {tagger_hits} cartas con tags, {tagger_misses} sin tags")
    return enriched


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Enriquece colección ManaBox con datos de Scryfall (+ Tagger opcional)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--real",   required=True, help="Ruta al CSV de cartas reales")
    parser.add_argument("--fake",   required=True, help="Ruta al CSV de cartas fake")
    parser.add_argument("--output", default="collection_enriched.json")

    # Tagger options
    tagger_group = parser.add_argument_group("Scryfall Tagger (opcional)")
    tagger_group.add_argument(
        "--tagger", action="store_true",
        help="Activar descarga de Scryfall Tagger function tags",
    )
    tagger_group.add_argument(
        "--tagger-session", metavar="COOKIE",
        help=(
            "Valor de la cookie de sesión de tagger.scryfall.com. "
            "Obtener de DevTools → Application → Cookies → _scryfall_session"
        ),
    )
    tagger_group.add_argument(
        "--tagger-verbose", action="store_true",
        help="Mostrar errores detallados de Tagger (útil para debug de sesión)",
    )

    args = parser.parse_args()

    real_path   = Path(args.real)
    fake_path   = Path(args.fake)
    output_path = Path(args.output)

    for p in (real_path, fake_path):
        if not p.exists():
            print(f"ERROR: no existe {p}")
            sys.exit(1)

    CACHE_DIR.mkdir(exist_ok=True)
    print(f"Cache Scryfall: {CACHE_DIR}")

    # Sesión Scryfall
    scryfall_session = requests.Session()
    scryfall_session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })

    # Sesión Tagger (solo si --tagger)
    tagger_session: requests.Session | None = None
    if args.tagger:
        TAGGER_CACHE_DIR.mkdir(exist_ok=True)
        print(f"Cache Tagger:   {TAGGER_CACHE_DIR}")

        # Resolver cookie: prioridad --tagger-session > auto-detección de navegador
        cookie_value = args.tagger_session
        if cookie_value:
            print("  Usando cookie manual (--tagger-session).")
        else:
            print("  Buscando cookie en navegadores instalados...", end=" ", flush=True)
            cookie_value = _find_tagger_cookie_in_browser()
            if not cookie_value:
                print("no encontrada.")
                print("  [WARN] No se encontró cookie automáticamente.")
                print("         Opciones:")
                print("           1. pip install browser-cookie3  (si no está instalado)")
                print("           2. Asegúrate de estar logueado en tagger.scryfall.com en Chrome/Edge")
                print("           3. Pasa la cookie manualmente: --tagger-session 'VALOR'")
                print("         Continuando sin Tagger — se usarán heurísticas de oracle_text.")

        tagger_session = requests.Session()
        tagger_session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Referer": "https://tagger.scryfall.com/",
        })
        if cookie_value:
            tagger_session.cookies.set(
                "_scryfall_session", cookie_value,
                domain="tagger.scryfall.com",
            )
            # Verificación rápida con una carta conocida
            print("  Verificando sesión Tagger...", end=" ", flush=True)
            test_tags = get_tagger_tags("m21", "177", tagger_session, verbose=True)
            if test_tags:
                print(f"OK (Cultivate: {test_tags[:3]})")
            else:
                print("WARN — sin tags en test (la cookie puede haber expirado)")
        else:
            # Sin cookie válida, desactivamos tagger_session para usar solo fallback
            tagger_session = None

    real_cards = process_csv(
        real_path, "real", scryfall_session, tagger_session,
        verbose_tagger=args.tagger_verbose,
    )
    fake_cards = process_csv(
        fake_path, "fake", scryfall_session, tagger_session,
        verbose_tagger=args.tagger_verbose,
    )

    output = {
        "metadata": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tagger_enabled": args.tagger,
            "real_count_unique": len(real_cards),
            "fake_count_unique": len(fake_cards),
            "real_count_total": sum(c["quantity"] for c in real_cards),
            "fake_count_total": sum(c["quantity"] for c in fake_cards),
        },
        "real": real_cards,
        "fake": fake_cards,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Guardado en {output_path}")
    print(f"  Tamaño: {output_path.stat().st_size / 1024:.1f} KB")
    print(f"  Real: {output['metadata']['real_count_unique']} únicas, "
          f"Fake: {output['metadata']['fake_count_unique']} únicas")
    if args.tagger:
        real_with_tags = sum(1 for c in real_cards if c.get("tagger_tags"))
        print(f"  Tagger tags: {real_with_tags}/{len(real_cards)} cartas reales con tags")
    print(f"\nSube este archivo a Claude para construir mazos.")


if __name__ == "__main__":
    main()
