"""
pool.py — Carga y filtrado del pool de cartas.

Garantiza que NUNCA se usen cartas que aparecen en `fake.csv`, incluso si
también están en `real.csv` (caso "fake disfrazada de real" detectado en
sesión 1).
"""

import json
from pathlib import Path
from typing import Iterable


def load_collection(path: str | Path) -> dict:
    """
    Carga collection_enriched.json. Espera estructura:
        {
            "metadata": {...},
            "real": [...],
            "fake": [...]
        }
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_real_pool(collection: dict) -> list[dict]:
    """
    Devuelve el pool REAL VERDADERO: cartas de `real` cuyo nombre NO aparece
    en `fake`. Aplica deduplicación por nombre (singleton-ready).

    Esto es crítico: el CSV `real.csv` contiene cartas que también están en
    `fake.csv`. Cualquier carta en ambos pools se considera FAKE y se excluye.
    """
    fake_names = {c["name"] for c in collection.get("fake", [])}
    seen: set[str] = set()
    pool: list[dict] = []
    for card in collection.get("real", []):
        name = card["name"]
        if name in fake_names:
            continue
        if name in seen:
            continue
        seen.add(name)
        pool.append(card)
    return pool


def fits_color_identity(card: dict, deck_ci: Iterable[str]) -> bool:
    """¿La color identity de la carta cabe en la del mazo?"""
    deck_set = set(deck_ci)
    return set(card.get("color_identity", [])).issubset(deck_set)


def filter_by_identity(pool: list[dict], deck_ci: Iterable[str]) -> list[dict]:
    """Subconjunto del pool que es jugable en una identidad de color."""
    return [c for c in pool if fits_color_identity(c, deck_ci)]


def index_by_name(pool: list[dict]) -> dict[str, dict]:
    """Lookup rápido carta -> dict por nombre."""
    return {c["name"]: c for c in pool}


def is_legal_in_commander(card: dict) -> bool:
    """
    ¿La carta puede ser comandante técnicamente?

    NOTA: Esto NO consulta la banlist de Commander. El campo `can_be_commander`
    de la colección ya marca cartas técnicamente válidas (legendary creatures,
    planeswalkers con "can be your commander", partners). Si una carta está
    baneada en formato Commander oficial pero técnicamente cumple el rol
    (ej. Erayo, Channel-en-comandante, etc.), se permite.

    Decisión de diseño: la legalidad de Commander varía por playgroup y
    no queremos descartar cartas válidas por reglas oficiales que el
    usuario puede o no respetar en su mesa.
    """
    return bool(card.get("can_be_commander"))


def is_basic_land(card: dict) -> bool:
    name = card.get("name", "")
    return name in ("Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes")


# Convenience predicates -----------------------------------------------------

def has_text(card: dict, *terms: str) -> bool:
    """¿El oracle text contiene alguna de las frases (case-insensitive)?"""
    text = (card.get("oracle_text") or "").lower()
    return any(t.lower() in text for t in terms)


def has_type(card: dict, *types: str) -> bool:
    """¿El type line contiene alguna de las palabras (case-insensitive)?"""
    tl = (card.get("type_line") or "").lower()
    return any(t.lower() in tl for t in types)


def cmc(card: dict) -> int:
    return int(card.get("cmc") or 0)


def edhrec_rank(card: dict) -> int:
    """Rank EDHREC, o un valor alto si no hay (cartas obscuras)."""
    return card.get("edhrec_rank") or 999_999
