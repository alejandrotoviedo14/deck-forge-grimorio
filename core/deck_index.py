"""
deck_index.py — Índice persistente de mazos construidos con Deck Forge.

Guarda un registro de todos los mazos generados en un archivo JSON
dentro del output-dir. Permite listar mazos y recuperarlos para upgrade.

Estructura de decks_index.json:
    {
        "decks": {
            "teneb": {
                "commander": "Teneb, the Harvester",
                "archetype": "reanimator",
                "colors": "BGW",
                "bracket": 1,
                "bracket_score": 1.2,
                "built_at": "2026-05-13 18:30:00",
                "cards": [ {carta_dict}, ... ],   # sin básicas, sin comandante
                "commander_card": {carta_dict},
                "needed_basics": 22,
            },
            ...
        }
    }

El key del mazo es el safe_filename del comandante (ej. "teneb_the_harvester").
"""

import json
import time
from pathlib import Path


INDEX_FILENAME = "decks_index.json"


def _index_path(output_dir: Path) -> Path:
    return output_dir / INDEX_FILENAME


def load_index(output_dir: Path) -> dict:
    """Carga el índice. Devuelve dict vacío si no existe o está corrupto."""
    path = _index_path(output_dir)
    if not path.exists():
        return {"decks": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {"decks": {}}
            return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return {"decks": {}}


def save_index(index: dict, output_dir: Path) -> None:
    path = _index_path(output_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def register_deck(
    output_dir: Path,
    deck_key: str,
    commander_card: dict,
    archetype_key: str,
    colors: str,
    bracket: int,
    bracket_score: float,
    cards: list[dict],      # sin básicas, sin comandante
    needed_basics: int,
    html_data: dict | None = None,  # datos completos para el HTML
) -> None:
    """
    Registra un mazo recién construido en el índice.
    Sobrescribe si ya existe el mismo key (rebuild).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    index = load_index(output_dir)

    entry = {
        "commander": commander_card["name"],
        "archetype": archetype_key,
        "colors": colors,
        "bracket": bracket,
        "bracket_score": round(bracket_score, 2),
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "commander_card": commander_card,
        "cards": cards,
        "needed_basics": needed_basics,
    }
    if html_data:
        entry.update(html_data)

    index["decks"][deck_key] = entry
    save_index(index, output_dir)


def list_decks(output_dir: Path) -> list[dict]:
    """Devuelve lista de mazos registrados con su metadata."""
    index = load_index(output_dir)
    result = []
    for key, data in index["decks"].items():
        result.append({
            "key": key,
            "commander": data["commander"],
            "archetype": data["archetype"],
            "colors": data["colors"],
            "bracket": data["bracket"],
            "bracket_score": data["bracket_score"],
            "built_at": data["built_at"],
        })
    result.sort(key=lambda d: d["built_at"], reverse=True)
    return result


def get_deck(output_dir: Path, deck_key: str) -> dict | None:
    """
    Recupera un mazo por key. Hace fuzzy match parcial.
    Ej: "teneb" matchea "teneb_the_harvester".
    Devuelve None si no existe.
    """
    index = load_index(output_dir)
    decks = index.get("decks", {})

    # Match exacto
    if deck_key in decks:
        return decks[deck_key]

    # Match parcial (el key contiene la query)
    matches = [k for k in decks if deck_key.lower() in k.lower()]
    if len(matches) == 1:
        return decks[matches[0]]
    if len(matches) > 1:
        # Devolver el más reciente
        best = max(matches, key=lambda k: decks[k].get("built_at", ""))
        return decks[best]

    # Match por nombre de comandante
    name_matches = [
        k for k, v in decks.items()
        if deck_key.lower() in v.get("commander", "").lower()
    ]
    if name_matches:
        best = max(name_matches, key=lambda k: decks[k].get("built_at", ""))
        return decks[best]

    return None


def print_deck_list(output_dir: Path) -> None:
    """Imprime la lista de mazos de forma legible."""
    decks = list_decks(output_dir)
    if not decks:
        print("No hay mazos registrados en este directorio.")
        print(f"Ejecuta 'build' para crear uno.")
        return

    print(f"\n=== MAZOS GUARDADOS ({len(decks)}) ===")
    print(f"  {'Key':35s} {'Comandante':30s} {'Arquetipo':15s} {'Colores':8s} {'Bracket':8s} {'Fecha'}")
    print("  " + "-" * 115)
    for d in decks:
        print(
            f"  {d['key']:35s} "
            f"{d['commander']:30s} "
            f"{d['archetype']:15s} "
            f"{d['colors']:8s} "
            f"B{d['bracket']} ({d['bracket_score']:.2f})  "
            f"{d['built_at']}"
        )
    print()
    print(f"  Uso: python deck_forge.py upgrade --deck <key> --collection ...")
