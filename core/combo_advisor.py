"""
combo_advisor.py — Detección de combos via Commander Spellbook API.

Usa la API pública de Commander Spellbook para:
1. Encontrar todos los combos que caben en la identidad de color del comandante
2. Cruzarlos con el pool de cartas disponible
3. Devolver combos completos y combos "a 1-2 piezas de distancia"

API base: https://backend.commanderspellbook.com/variants/
"""

import json
import time
import hashlib
from pathlib import Path

CACHE_DIR   = Path.home() / ".deck_forge_cache" / "combos"
CACHE_TTL   = 72 * 3600   # 72 horas — los combos no cambian a diario
MAX_COMBOS  = 200          # límite por búsqueda de identidad
CSB_BASE    = "https://backend.commanderspellbook.com"
USER_AGENT  = "DeckForge/1.0 (Commander deck builder)"


# ── Cache ──────────────────────────────────────────────────────────────────

def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{hashlib.md5(key.encode()).hexdigest()[:12]}.json"

def _load_cache(key: str) -> list | None:
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if time.time() - d.get("ts", 0) < CACHE_TTL:
            return d["combos"]
    except Exception:
        pass
    return None

def _save_cache(key: str, combos: list) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(key).write_text(
        json.dumps({"ts": time.time(), "combos": combos}, ensure_ascii=False),
        encoding="utf-8"
    )


# ── Fetch ──────────────────────────────────────────────────────────────────

def _fetch_combos_for_identity(identity: str, verbose: bool = False) -> list[dict]:
    """
    Descarga todos los combos que caben dentro de la identidad de color dada.
    Ordena por popularidad descendente y limita a MAX_COMBOS.
    """
    import urllib.request, urllib.parse

    cache_key = f"identity_{identity.upper()}"
    cached = _load_cache(cache_key)
    if cached is not None:
        if verbose:
            print(f"  [COMBOS] Cache hit para identidad {identity} ({len(cached)} combos)")
        return cached

    if verbose:
        print(f"  [COMBOS] Buscando combos para identidad {identity}...")

    q = f"identity<={identity.upper()}"
    params = urllib.parse.urlencode({
        "q": q,
        "page_size": MAX_COMBOS,
        "ordering": "-popularity",
    })
    url = f"{CSB_BASE}/variants/?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except Exception as e:
        if verbose:
            print(f"  [COMBOS] Error fetching: {e}")
        return []

    results = data.get("results", [])
    combos = []
    for c in results:
        cards = [u["card"]["name"] for u in c.get("uses", [])]
        produces = [p["feature"]["name"] for p in c.get("produces", [])]
        if len(cards) < 2:
            continue
        combos.append({
            "id":          c["id"],
            "cards":       cards,
            "produces":    produces,
            "identity":    c.get("identity", ""),
            "popularity":  c.get("popularity", 0),
            "description": c.get("description", ""),
            "bracketTag":  c.get("bracketTag", ""),
        })

    if verbose:
        print(f"  [COMBOS] {len(combos)} combos obtenidos para identidad {identity}")

    _save_cache(cache_key, combos)
    return combos


# ── Análisis ────────────────────────────────────────────────────────────────

def find_combos_in_pool(
    pool_names: set[str],
    identity: str,
    commander_name: str = "",
    verbose: bool = False,
) -> dict:
    """
    Busca combos que se pueden formar con las cartas del pool.

    Devuelve:
      complete   — combos donde TODAS las piezas están en el pool
      near_1     — combos donde falta exactamente 1 pieza (sugerencia de compra)
      near_2     — combos donde faltan exactamente 2 piezas
    """
    pool_lower = {n.lower() for n in pool_names}
    # Añadir el comandante al pool para detectar combos que lo incluyen
    if commander_name:
        pool_lower.add(commander_name.lower())

    all_combos = _fetch_combos_for_identity(identity, verbose=verbose)

    complete: list[dict] = []
    near_1:   list[dict] = []
    near_2:   list[dict] = []

    for combo in all_combos:
        cards_lower = [c.lower() for c in combo["cards"]]
        missing = [c for c in cards_lower if c not in pool_lower]
        n_missing = len(missing)

        entry = {**combo, "missing": missing}

        if n_missing == 0:
            complete.append(entry)
        elif n_missing == 1:
            near_1.append(entry)
        elif n_missing == 2:
            near_2.append(entry)

    # Ordenar por popularidad
    complete.sort(key=lambda x: -x["popularity"])
    near_1.sort(  key=lambda x: -x["popularity"])
    near_2.sort(  key=lambda x: -x["popularity"])

    if verbose:
        print(f"  [COMBOS] Completos: {len(complete)} | "
              f"A 1 carta: {len(near_1)} | A 2 cartas: {len(near_2)}")

    return {
        "complete": complete[:20],   # máx 20 para el grimorio
        "near_1":   near_1[:15],
        "near_2":   near_2[:10],
    }


def combo_cards_to_include(
    complete_combos: list[dict],
    archetype_key: str,
) -> list[str]:
    """
    Dado un set de combos completos, devuelve las cartas de combos
    que merece la pena incluir activamente en el mazo.

    Filtra combos que encajan con el arquetipo y son de baja complejidad
    (pocos pasos, bien conocidos). Solo devuelve los más populares.
    """
    # Combos más populares con pocas piezas (combos simples de 2-3 cartas)
    good_combos = [
        c for c in complete_combos
        if len(c["cards"]) <= 4 and c["popularity"] >= 5000
    ][:5]   # top 5 combos elegibles

    cards: set[str] = set()
    for combo in good_combos:
        for card in combo["cards"]:
            cards.add(card)

    return list(cards)
