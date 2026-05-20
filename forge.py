#!/usr/bin/env python3
"""
forge.py — Wrapper en lenguaje natural sobre deck_forge.py.

EJEMPLOS:
    python forge.py analizar
    python forge.py construir mazo rojo
    python forge.py construir goblins
    python forge.py construir reanimator negro verde
    python forge.py upgrade vorel
    python forge.py mejorar teneb hasta bracket 2
    python forge.py mazos
    python forge.py listar mazos

Mapea palabras sueltas a flags del CLI completo de deck_forge.py.
Si la frase es ambigua, te pregunta. Si no entiende, te enseña ejemplos.

DICCIONARIO:
    Acciones:  analizar, construir, mejorar, upgrade, mazos, listar
    Colores:   blanco (W), azul (U), negro (B), rojo (R), verde (G)
               + combos: simic (GU), izzet (UR), golgari (BG), etc.
    Arquetipos: counters, equipment, voltron, aristocrats, tokens, sacrifice,
                spellslinger, spells, tribal, kindred, goblins, elves,
                blink, flicker, landfall, lands, lifegain, life,
                reanimator, graveyard
"""

import sys
import subprocess
from pathlib import Path

# Defaults (puedes editar aquí si tu setup es distinto)
DEFAULT_COLLECTION = "collection_enriched.json"
DEFAULT_REAL_CSV   = "real.csv"
DEFAULT_OUTPUT_DIR = "./decks"

# ---------------------------------------------------------------------------
# Diccionarios de mapeo
# ---------------------------------------------------------------------------

ACTIONS = {
    "analizar": "analyze",
    "analyze":  "analyze",
    "analisis": "analyze",
    "análisis": "analyze",
    "construir": "build",
    "build":    "build",
    "crear":    "build",
    "hacer":    "build",
    "mejorar":  "upgrade",
    "upgrade":  "upgrade",
    "subir":    "upgrade",
    "mazos":    "decks",
    "listar":   "decks",
    "list":     "decks",
    "ver":      "decks",
}

# Colores individuales (ES + EN + simbolos)
COLOR_WORDS = {
    "blanco": "W", "white": "W", "w": "W",
    "azul":   "U", "blue":  "U", "u": "U",
    "negro":  "B", "black": "B", "b": "B",
    "rojo":   "R", "red":   "R", "r": "R",
    "verde":  "G", "green": "G", "g": "G",
}

# Pares y triples de colores con nombres conocidos (Magic guild/shard names)
COLOR_PAIRS = {
    # Dos colores (10 guilds)
    "azorius":  "UW", "dimir": "UB", "rakdos": "BR", "gruul":  "RG", "selesnya": "GW",
    "orzhov":   "WB", "izzet": "UR", "golgari":"BG", "boros":  "RW", "simic":    "GU",
    "azoroius": "UW",
    # Tres colores (10 shards/wedges)
    "esper":  "WUB", "grixis": "UBR", "jund":  "BRG", "naya":   "RGW", "bant":  "GWU",
    "abzan":  "WBG", "jeskai": "URW", "sultai":"BGU", "mardu":  "RWB", "temur": "GUR",
    # Cuatro colores
    "yore":   "WUBR", "glint": "UBRG", "dune":  "BRGW", "ink":   "RGWU", "witch": "GWUB",
    # Cinco
    "wubrg":  "WUBRG", "rainbow": "WUBRG", "domain": "WUBRG", "all":   "WUBRG",
}

ARCHETYPES = {
    # Counters
    "counters": "counters", "proliferate": "counters", "contadores": "counters", "1plus1": "counters",
    # Equipment
    "equipment": "equipment", "voltron": "equipment", "equipos": "equipment", "armas": "equipment",
    # Aristocrats
    "aristocrats": "aristocrats", "tokens": "aristocrats", "sacrifice": "aristocrats",
    "sacrificio": "aristocrats", "tokenes": "aristocrats", "fichas": "aristocrats",
    # Spellslinger
    "spellslinger": "spellslinger", "spells": "spellslinger", "magecraft": "spellslinger",
    "hechizos": "spellslinger", "cantrips": "spellslinger",
    # Tribal
    "tribal": "tribal", "kindred": "tribal", "tribu": "tribal",
    "goblins": "tribal", "elves": "tribal", "elfos": "tribal", "vampires": "tribal",
    "vampiros": "tribal", "dragons": "tribal", "dragones": "tribal", "zombies": "tribal",
    "cats": "tribal", "gatos": "tribal", "humans": "tribal", "humanos": "tribal",
    # Blink
    "blink": "blink", "flicker": "blink", "etb": "blink", "parpadeo": "blink",
    # Landfall
    "landfall": "landfall", "lands": "landfall", "tierras": "landfall",
    # Lifegain
    "lifegain": "lifegain", "life": "lifegain", "vida": "lifegain",
    # Reanimator
    "reanimator": "reanimator", "graveyard": "reanimator", "cementerio": "reanimator",
    "reanimate": "reanimator", "reanimar": "reanimator",
}

# Stopwords que ignoramos al parsear
STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "y", "o", "con", "para", "en", "a",
    "mazo", "deck", "the", "of", "and", "or", "with", "for", "in",
    "bracket", "objetivo", "hasta", "to",
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse(words: list[str]) -> dict:
    """
    Parsea una lista de palabras y devuelve un dict con la intención:
        {
            "action":    "analyze" | "build" | "upgrade" | "decks",
            "colors":    "GU" | None,
            "archetype": "counters" | None,
            "deck_name": "vorel" | None,
            "bracket":   2 | None,
            "extra":     [palabras no reconocidas],
        }
    """
    words = [w.lower().strip() for w in words if w.strip()]

    action = None
    colors_set: set[str] = set()
    archetype = None
    deck_name_parts: list[str] = []
    bracket = None
    extra: list[str] = []

    i = 0
    while i < len(words):
        w = words[i]

        # Acción
        if action is None and w in ACTIONS:
            action = ACTIONS[w]
            i += 1
            continue

        # Bracket: "bracket 2" o "hasta 2"
        if w in ("bracket", "hasta", "to") and i + 1 < len(words):
            try:
                bracket = int(words[i + 1])
                i += 2
                continue
            except ValueError:
                pass

        # Color individual
        if w in COLOR_WORDS:
            colors_set.add(COLOR_WORDS[w])
            i += 1
            continue

        # Combo de colores
        if w in COLOR_PAIRS:
            for c in COLOR_PAIRS[w]:
                colors_set.add(c)
            i += 1
            continue

        # Arquetipo
        if archetype is None and w in ARCHETYPES:
            archetype = ARCHETYPES[w]
            i += 1
            continue

        # Stopword: ignorar
        if w in STOPWORDS:
            i += 1
            continue

        # Si la acción es upgrade y queda algo, asumimos que es el nombre del deck
        if action == "upgrade" and not deck_name_parts:
            deck_name_parts.append(w)
            i += 1
            continue

        # Si no es nada conocido, lo guardamos como "extra" para diagnóstico
        extra.append(w)
        i += 1

    # Si no encontró acción pero hay deck_name_parts, asumimos upgrade
    if action is None and deck_name_parts:
        action = "upgrade"

    return {
        "action":    action,
        "colors":    "".join(sorted(colors_set)) if colors_set else None,
        "archetype": archetype,
        "deck_name": "_".join(deck_name_parts) if deck_name_parts else None,
        "bracket":   bracket,
        "extra":     extra,
    }


# ---------------------------------------------------------------------------
# Ejecutor — traduce intención a comando de deck_forge.py
# ---------------------------------------------------------------------------

def build_command(intent: dict) -> list[str] | None:
    """Construye el comando deck_forge.py a partir de la intención."""
    action = intent["action"]
    if not action:
        return None

    base = ["python", "deck_forge.py", action]

    if action == "analyze":
        base += ["--collection", DEFAULT_COLLECTION]

    elif action == "build":
        base += [
            "--collection", DEFAULT_COLLECTION,
            "--real-csv",   DEFAULT_REAL_CSV,
            "--output-dir", DEFAULT_OUTPUT_DIR,
        ]
        if intent["colors"]:
            base += ["--colors", intent["colors"]]
        if intent["archetype"]:
            base += ["--archetype", intent["archetype"]]
        # Si no hay ni colores ni arquetipo, no se puede construir
        if not intent["colors"] and not intent["archetype"]:
            return "NEED_INFO"

    elif action == "upgrade":
        if not intent["deck_name"]:
            return "NEED_DECK"
        base += [
            "--deck", intent["deck_name"],
            "--collection", DEFAULT_COLLECTION,
            "--output-dir", DEFAULT_OUTPUT_DIR,
        ]
        if intent["bracket"]:
            base += ["--target-bracket", str(intent["bracket"])]

    elif action == "decks":
        base += ["--output-dir", DEFAULT_OUTPUT_DIR]

    return base


# ---------------------------------------------------------------------------
# Ayuda
# ---------------------------------------------------------------------------

EXAMPLES = """
Ejemplos:
  python forge.py analizar
  python forge.py mazos
  python forge.py construir mazo rojo
  python forge.py construir simic counters
  python forge.py construir goblins
  python forge.py construir reanimator negro verde
  python forge.py upgrade vorel
  python forge.py mejorar teneb hasta bracket 2

Acciones:    analizar, construir, mejorar, mazos
Colores:     blanco, azul, negro, rojo, verde
             + guilds: simic, izzet, golgari, boros, dimir, rakdos, gruul,
                       selesnya, orzhov, azorius
             + shards: esper, grixis, jund, naya, bant, abzan, jeskai,
                       sultai, mardu, temur
Arquetipos:  counters, equipment, aristocrats, spellslinger, tribal,
             blink, landfall, lifegain, reanimator
             + alias: goblins, elves, voltron, tokens, graveyard, etc.
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Uso: python forge.py <accion> [palabras...]")
        print(EXAMPLES)
        sys.exit(1)

    intent = parse(sys.argv[1:])
    cmd = build_command(intent)

    # Diagnóstico si no se pudo construir
    if cmd is None:
        print(f"No entendí la acción. Palabras leídas: {sys.argv[1:]}")
        print(EXAMPLES)
        sys.exit(1)

    if cmd == "NEED_INFO":
        print("Para construir un mazo necesito al menos colores o arquetipo.")
        print("Ejemplos:")
        print("  python forge.py construir mazo rojo")
        print("  python forge.py construir goblins")
        print("  python forge.py construir simic counters")
        sys.exit(1)

    if cmd == "NEED_DECK":
        print("¿Qué mazo quieres mejorar?")
        print("Ejemplo: python forge.py upgrade vorel")
        print("\nPara ver tus mazos disponibles:")
        print("  python forge.py mazos")
        sys.exit(1)

    # Mostrar interpretación
    print(f"➜ Interpreto: {intent['action']}", end="")
    if intent["colors"]:
        print(f" | colores: {intent['colors']}", end="")
    if intent["archetype"]:
        print(f" | arquetipo: {intent['archetype']}", end="")
    if intent["deck_name"]:
        print(f" | deck: {intent['deck_name']}", end="")
    if intent["bracket"]:
        print(f" | bracket objetivo: {intent['bracket']}", end="")
    print()

    if intent["extra"]:
        print(f"  (palabras no reconocidas: {intent['extra']})")

    print(f"➜ Ejecutando: {' '.join(cmd)}\n")

    # Ejecutar
    try:
        result = subprocess.run(cmd, check=False)
        sys.exit(result.returncode)
    except FileNotFoundError:
        print("ERROR: no se encontró 'python' o 'deck_forge.py' en el PATH actual.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(130)


if __name__ == "__main__":
    main()
