"""
tagger_cache.py — Índice de tags funcionales construido desde Scryfall.

Dado que la API del Tagger de Scryfall no es pública, construimos nuestro propio
índice de tags funcionales usando búsquedas de oracle text en la API de Scryfall.

Resultado: {oracle_id → [list_of_functional_tags]}
Cacheado en ~/.deck_forge_cache/tagger_index.json (TTL 7 días)

Los tags coinciden exactamente con los de TAG_TO_ROLES en classifier.py,
por lo que el clasificador los usará automáticamente.
"""

import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

CACHE_FILE = Path.home() / ".deck_forge_cache" / "tagger_index.json"
CACHE_TTL  = 7 * 24 * 3600   # 7 días
UA = "Mozilla/5.0 (compatible; DeckForge/1.0; +https://deckforge.up.railway.app)"

# ── Consultas Scryfall → tags funcionales ─────────────────────────────────
# Cada entrada: (tag_name, scryfall_query, max_pages)
# Los tags coinciden con los keys de TAG_TO_ROLES en classifier.py
FUNCTIONAL_TAG_QUERIES: list[tuple[str, str, int]] = [
    # RAMP
    ("mana-rock",
     "type:artifact cmc<=3 oracle:\"add {\" -type:land",
     4),
    ("mana-dork",
     "type:creature cmc<=3 oracle:\"{T}: add\" -type:land",
     3),
    ("land-ramp",
     "oracle:\"search your library\" (oracle:\"land card\" or oracle:\"basic land\") -type:land",
     4),
    ("ramp",
     "(oracle:\"add {c}{c}\" or oracle:\"add {c}{c}{c}\" or oracle:\"adds an additional mana\""
     " or oracle:\"cost {2} less\" or oracle:\"costs {2} less\") -type:land cmc<=4",
     2),
    ("cost-reduction",
     "(oracle:\"spells you cast cost\" oracle:\"less to cast\") or"
     " (oracle:\"instant and sorcery spells you cast cost\") -type:land",
     2),

    # CARD DRAW
    ("card-draw",
     "(type:instant or type:sorcery) (oracle:\"draw two cards\" or oracle:\"draw three cards\""
     " or oracle:\"draw four cards\" or oracle:\"draw X cards\") cmc<=6",
     4),
    ("cantrip",
     "(type:instant or type:sorcery) cmc<=2 oracle:\"draw a card\" -oracle:\"draw two\"",
     4),
    ("looting",
     "(oracle:\"draw\" oracle:\"discard\") (type:instant or type:sorcery) cmc<=4",
     3),
    ("impulse-draw",
     "oracle:\"exile the top\" (oracle:\"cast it\" or oracle:\"play it\") -type:land",
     2),

    # REMOVAL
    ("single-target-removal",
     "(type:instant or type:sorcery) (oracle:\"destroy target\" or oracle:\"exile target creature\""
     " or oracle:\"exile target nonland\") cmc<=5",
     5),
    ("bounce",
     "(type:instant or type:sorcery) oracle:\"return target\" oracle:\"to its owner's hand\" cmc<=4",
     3),
    ("board-wipe",
     "(oracle:\"destroy all\" or oracle:\"exile all creatures\""
     " or oracle:\"deals damage to each creature\") (type:instant or type:sorcery)",
     3),
    ("spot-removal",
     "(type:instant or type:sorcery) oracle:\"destroy target\" cmc<=4",
     4),

    # COUNTERSPELLS
    ("counterspell",
     "type:instant oracle:\"counter target\" cmc<=4",
     3),

    # TUTORS
    ("tutor",
     "oracle:\"search your library for\" (oracle:\"put it into your hand\""
     " or oracle:\"put that card into your hand\") -type:land",
     4),

    # PROTECTION
    ("protection",
     "(oracle:\"gains hexproof\" or oracle:\"have hexproof\" or oracle:\"gains indestructible\""
     " or oracle:\"have indestructible\") (type:instant or type:sorcery) cmc<=4",
     2),

    # RECURSION & GRAVEYARD
    ("recursion",
     "(oracle:\"return target\" oracle:\"from your graveyard\""
     " or oracle:\"return target creature card from your graveyard\")"
     " (type:instant or type:sorcery) cmc<=6",
     3),
    ("reanimator",
     "(oracle:\"return target creature card\" oracle:\"graveyard to the battlefield\""
     " or oracle:\"put target creature card from a graveyard onto the battlefield\") cmc<=7",
     3),
    ("self-mill",
     "(oracle:\"mill\" or oracle:\"put the top\" oracle:\"into your graveyard\") cmc<=4",
     2),
    ("graveyard-matters",
     "oracle:\"from your graveyard\" (oracle:\"whenever a creature\" or oracle:\"dies\")"
     " -type:land",
     2),

    # TOKEN MAKERS
    ("token-maker",
     "(oracle:\"create\" oracle:\"token\") (type:instant or type:sorcery or type:enchantment"
     " or type:artifact) cmc<=5",
     4),

    # HASTE & COMBAT
    ("haste-enabler",
     "oracle:\"creatures you control have haste\" -type:land",
     1),

    # EXTRA CARDS / CARD ADVANTAGE
    ("investigate",
     "oracle:\"investigate\"",
     2),
    ("cycling",
     "keyword:cycling",
     3),
]

# ── Core ──────────────────────────────────────────────────────────────────

def _cache_fresh() -> bool:
    if not CACHE_FILE.exists():
        return False
    try:
        d = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return (time.time() - d.get("built_at", 0)) < CACHE_TTL
    except Exception:
        return False


def _load_cache() -> dict[str, list[str]]:
    try:
        d = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return d.get("index", {})
    except Exception:
        return {}


def _scryfall_search_all(query: str, max_pages: int = 4,
                         verbose: bool = False) -> list[dict]:
    """Descarga todas las páginas de una búsqueda Scryfall."""
    cards: list[dict] = []
    url = ("https://api.scryfall.com/cards/search?"
           + urllib.parse.urlencode({"q": query, "format": "json"}))

    for page in range(1, max_pages + 1):
        if page > 1:
            url = ("https://api.scryfall.com/cards/search?"
                   + urllib.parse.urlencode({"q": query, "format": "json", "page": page}))

        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
        except Exception as e:
            if verbose:
                print(f"    [TAGGER] pag {page} error: {e}")
            break

        batch = data.get("data", [])
        cards.extend(batch)

        if not data.get("has_more", False):
            break

        time.sleep(0.12)   # rate-limit friendly

    return cards


def build_tag_index(verbose: bool = True, force: bool = False) -> dict[str, list[str]]:
    """
    Construye el índice {oracle_id → [tags]} descargando cartas por categoría.
    Usa caché de 7 días. Llama con force=True para forzar reconstrucción.

    El índice usa oracle_id (no nombre) para ser robusto ante cartas con
    nombres idénticos en distintos sets.
    """
    if not force and _cache_fresh():
        if verbose:
            print("  [TAGGER] Índice en caché (< 7 días)")
        return _load_cache()

    if verbose:
        print(f"  [TAGGER] Construyendo índice de {len(FUNCTIONAL_TAG_QUERIES)} categorías...")

    # oracle_id → set de tags
    index: dict[str, set[str]] = {}
    # También guardamos oracle_id → name para debug
    names: dict[str, str] = {}

    for tag, query, max_pages in FUNCTIONAL_TAG_QUERIES:
        cards = _scryfall_search_all(query, max_pages, verbose=verbose)
        for card in cards:
            oid = card.get("oracle_id", "")
            if not oid:
                continue
            if oid not in index:
                index[oid] = set()
                names[oid] = card.get("name", "")
            index[oid].add(tag)

        if verbose:
            print(f"    [{tag}] {len(cards)} cartas")
        time.sleep(0.08)

    # Convertir sets a listas para JSON
    index_list: dict[str, list[str]] = {k: list(v) for k, v in index.items()}

    # Guardar
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps({
            "built_at": time.time(),
            "card_count": len(index_list),
            "index": index_list,
            "names": names,   # opcional, para debug
        }, ensure_ascii=False),
        encoding="utf-8"
    )

    if verbose:
        print(f"  [TAGGER] Índice guardado: {len(index_list)} cartas únicas con tags")

    return index_list


def get_tags_for_oracle_id(oracle_id: str) -> list[str]:
    """Devuelve los tags para un oracle_id concreto desde el caché."""
    idx = _load_cache()
    return idx.get(oracle_id, [])


def enrich_card_with_tags(card: dict, index: dict[str, list[str]] | None = None) -> dict:
    """
    Añade/actualiza tagger_tags en un dict de carta usando el índice.
    Si index=None, carga desde caché.
    """
    if index is None:
        index = _load_cache()
    oracle_id = card.get("oracle_id", "")
    if oracle_id and oracle_id in index:
        # Combinar con tags ya existentes (por si acaso)
        existing = set(card.get("tagger_tags") or [])
        new_tags = set(index[oracle_id])
        card["tagger_tags"] = list(existing | new_tags)
    return card


# ── CLI standalone ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Construir índice de tags funcionales de Scryfall")
    p.add_argument("--force", action="store_true", help="Forzar reconstrucción aunque el caché sea fresco")
    p.add_argument("--stats", action="store_true", help="Mostrar estadísticas del caché actual")
    args = p.parse_args()

    if args.stats:
        if CACHE_FILE.exists():
            d = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            age_h = (time.time() - d.get("built_at", 0)) / 3600
            idx = d.get("index", {})
            # Contar distribución de tags
            from collections import Counter
            tag_counter: Counter = Counter()
            for tags in idx.values():
                for t in tags:
                    tag_counter[t] += 1
            print(f"Índice: {d.get('card_count')} cartas | Edad: {age_h:.1f}h")
            print("\nDistribución de tags:")
            for tag, cnt in tag_counter.most_common():
                print(f"  {tag:<30} {cnt} cartas")
        else:
            print("Sin caché. Ejecuta sin --stats para construir.")
    else:
        build_tag_index(verbose=True, force=args.force)
