"""
prompt_parser.py — Interpreta prompts en lenguaje natural y los convierte
en parámetros de build para el Deck Forge.

Solo trabaja con cartas de la colección del usuario.
"""
from __future__ import annotations
import re
from typing import TypedDict

# ── Colores: mono-pattern + nombres sueltos ────────────────────────────────
MONO_PATTERN = re.compile(
    r"mono[\s\-]?(blanco|azul|negro|rojo|verde|white|blue|black|red|green)\b",
    re.IGNORECASE,
)
MONO_COLOR_MAP: dict[str, str] = {
    "blanco": "W", "white": "W",
    "azul":   "U", "blue":  "U",
    "negro":  "B", "black": "B",
    "rojo":   "R", "red":   "R",
    "verde":  "G", "green": "G",
}
# Palabras de color sueltas (solo se usan si no hay mono ni guild)
COLOR_WORDS: dict[str, list[str]] = {
    "W": ["blanco", "white"],
    "U": ["azul", "blue"],
    "B": ["negro", "black"],
    "R": ["rojo", "red"],
    "G": ["verde", "green"],
}
COLOR_LABELS: dict[str, str] = {
    "W": "Blanco", "U": "Azul", "B": "Negro", "R": "Rojo", "G": "Verde",
}

# ── Guilds / combinaciones nombradas ──────────────────────────────────────
GUILD_KEYWORDS: dict[str, str] = {
    # 2-colores
    "azorius": "WU", "dimir": "UB", "rakdos": "BR",
    "gruul": "RG", "selesnya": "GW", "orzhov": "WB",
    "izzet": "UR", "golgari": "BG", "boros": "RW", "simic": "GU",
    # 3-colores
    "esper": "WUB", "grixis": "UBR", "jund": "BRG",
    "naya": "RGW", "bant": "GWU", "abzan": "WBG",
    "jeskai": "WUR", "sultai": "BGU", "mardu": "RWB", "temur": "GUR",
    # 4-colores
    "yore-tiller": "WUBR", "glint-eye": "UBRG", "dune-brood": "BRGW",
    "ink-treader": "RGWU", "witch-maw": "GWUB",
    # 5-colores
    "5 colores": "WUBRG", "cinco colores": "WUBRG", "5-colores": "WUBRG",
    "five color": "WUBRG", "five colours": "WUBRG", "rainbow": "WUBRG",
    "arco iris": "WUBRG", "5color": "WUBRG",
}

# ── Tribus (ES + EN) → canonical (como aparece en type_line de Scryfall) ───
TRIBES: dict[str, str] = {
    "goblin": "Goblin", "goblins": "Goblin",
    "elfo": "Elf", "elfos": "Elf", "elf": "Elf", "elves": "Elf",
    "vampiro": "Vampire", "vampiros": "Vampire",
    "vampire": "Vampire", "vampires": "Vampire",
    "dragón": "Dragon", "dragon": "Dragon",
    "dragons": "Dragon", "dragones": "Dragon",
    "zombie": "Zombie", "zombies": "Zombie", "zombi": "Zombie",
    "soldado": "Soldier", "soldados": "Soldier",
    "soldier": "Soldier", "soldiers": "Soldier",
    "mago": "Wizard", "magos": "Wizard",
    "wizard": "Wizard", "wizards": "Wizard",
    "humano": "Human", "humanos": "Human",
    "human": "Human", "humans": "Human",
    "merfolk": "Merfolk", "tritón": "Merfolk", "tritones": "Merfolk",
    "pirata": "Pirate", "piratas": "Pirate",
    "pirate": "Pirate", "pirates": "Pirate",
    "dinosaurio": "Dinosaur", "dinosaurios": "Dinosaur",
    "dinosaur": "Dinosaur", "dinosaurs": "Dinosaur",
    "ángel": "Angel", "angel": "Angel", "angels": "Angel", "ángeles": "Angel",
    "demonio": "Demon", "demonios": "Demon",
    "demon": "Demon", "demons": "Demon",
    "espíritu": "Spirit", "spirit": "Spirit", "spirits": "Spirit",
    "caballero": "Knight", "caballeros": "Knight",
    "knight": "Knight", "knights": "Knight",
    "guerrero": "Warrior", "guerreros": "Warrior",
    "warrior": "Warrior", "warriors": "Warrior",
    "druida": "Druid", "druidas": "Druid",
    "druid": "Druid", "druids": "Druid",
    "chamán": "Shaman", "shamán": "Shaman",
    "shaman": "Shaman", "shamans": "Shaman",
    "lobo": "Wolf", "lobos": "Wolf", "wolf": "Wolf", "wolves": "Wolf",
    "insecto": "Insect", "insectos": "Insect",
    "insect": "Insect", "insects": "Insect",
    "elemental": "Elemental", "elementales": "Elemental", "elementals": "Elemental",
    "golem": "Golem", "golems": "Golem",
    "horror": "Horror", "horrores": "Horror", "horrors": "Horror",
    "gato": "Cat", "gatos": "Cat", "cat": "Cat", "cats": "Cat",
    "pájaro": "Bird", "pájaros": "Bird", "bird": "Bird", "birds": "Bird",
    "bestia": "Beast", "bestias": "Beast", "beast": "Beast", "beasts": "Beast",
    "planta": "Plant", "plantas": "Plant", "plant": "Plant", "plants": "Plant",
    "hongo": "Fungus", "hongos": "Fungus", "fungus": "Fungus",
    "clérigo": "Cleric", "clérico": "Cleric",
    "cleric": "Cleric", "clerics": "Cleric",
    "explorador": "Scout", "scout": "Scout", "scouts": "Scout",
    "pícaro": "Rogue", "rogue": "Rogue", "rogues": "Rogue",
    "gigante": "Giant", "gigantes": "Giant", "giant": "Giant", "giants": "Giant",
    "faerie": "Faerie", "faeries": "Faerie", "hada": "Faerie", "hadas": "Faerie",
    "hydra": "Hydra", "hydras": "Hydra",
    "sliver": "Sliver", "slivers": "Sliver",
    "minotauro": "Minotaur", "minotauros": "Minotaur",
    "minotaur": "Minotaur", "minotaurs": "Minotaur",
    "fantasma": "Specter", "espectro": "Specter",
    "specter": "Specter", "specters": "Specter",
    "serpiente": "Serpent", "serpientes": "Serpent",
    "serpent": "Serpent", "serpents": "Serpent",
}

# ── Arquetipos (sin tribal, que se detecta por tribu) ─────────────────────
ARCHETYPE_KEYWORDS: dict[str, list[str]] = {
    "counters": [
        "+1/+1", "counters", "contadores", "proliferate", "proliferar",
        "infect", "veneno", "poison", "crecer",
    ],
    "equipment": [
        "equipo", "equipment", "voltron", "equipamiento",
        "espada", "armadura", "armor", "sword",
    ],
    "aristocrats": [
        "tokens", "sacrificio", "sacrifice", "aristocrats",
        "morir", "death trigger", "sac outlet", "fodder",
    ],
    "spellslinger": [
        "control", "hechizos", "spells", "instantes", "sorceries",
        "conjuros", "copias", "copies", "contrahechizo", "counterspell",
        "robar cartas", "draw spells",
    ],
    "blink": [
        "blink", "parpadeo", "flickering", "etb",
        "enters the battlefield", "entra al campo",
    ],
    "landfall": [
        "tierras", "lands", "landfall", "caída de tierra",
        "rampear", "ramp", "fetch", "terramorfos",
    ],
    "lifegain": [
        "vida", "lifegain", "ganar vida", "curación", "heal",
    ],
    "reanimator": [
        "reanimator", "reanimador", "cementerio", "graveyard",
        "revivir", "resurrect", "reanimar", "mill", "moler",
    ],
}


# ── TypedDict de salida ────────────────────────────────────────────────────
class ParsedPrompt(TypedDict):
    colors: str | None          # "R", "GU", "WUBRG" o None
    archetype: str | None       # clave de ARCHETYPES o None
    tribe: str | None           # nombre canónico de tribu o None
    commander_hint: str | None  # nombre de carta detectado en el prompt
    interpretation: str         # texto legible para mostrar al usuario
    is_mono: bool


# ── Parser principal ───────────────────────────────────────────────────────
def parse_prompt(prompt: str, pool: list[dict] | None = None) -> ParsedPrompt:
    """
    Convierte un prompt en lenguaje natural a parámetros de build.
    Si se pasa `pool`, intenta detectar nombres de comandantes en el texto.
    """
    text = prompt.strip().lower()
    colors: str | None = None
    archetype: str | None = None
    tribe: str | None = None
    commander_hint: str | None = None
    is_mono = False
    notes: list[str] = []

    # 1. Mono-color explícito
    mono_m = MONO_PATTERN.search(text)
    if mono_m:
        colors = MONO_COLOR_MAP.get(mono_m.group(1).lower())
        is_mono = True
        if colors:
            notes.append(f"Monocolor {COLOR_LABELS[colors]}")

    # 2. Guild / combinaciones nombradas
    if not colors:
        for guild, ci in GUILD_KEYWORDS.items():
            if re.search(r"\b" + re.escape(guild) + r"\b", text):
                colors = ci
                is_mono = len(ci) == 1
                label = guild.title()
                if is_mono:
                    label = f"Monocolor {COLOR_LABELS[ci]}"
                notes.append(label)
                break

    # 3. Colores sueltos (solo si no se detectó nada aún)
    if not colors:
        found: list[str] = []
        for letter, words in COLOR_WORDS.items():
            for w in words:
                if re.search(r"\b" + re.escape(w) + r"\b", text):
                    if letter not in found:
                        found.append(letter)
                    break
        if found:
            colors = "".join(sorted(found, key=lambda c: "WUBRG".index(c)))
            is_mono = len(found) == 1
            if is_mono:
                notes.append(f"Monocolor {COLOR_LABELS[colors]}")
            else:
                notes.append(f"Colores: {colors}")

    # 4. Tribu
    for kw, canonical in TRIBES.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE):
            tribe = canonical
            archetype = "tribal"
            notes.append(f"Tribal {canonical}")
            break

    # 5. Arquetipo (solo si no hay tribu)
    if not archetype:
        for arch_key, keywords in ARCHETYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    archetype = arch_key
                    notes.append(f"Arquetipo: {arch_key.title()}")
                    break
            if archetype:
                break

    # 6. Commander name en el texto (solo desde la colección)
    if pool:
        cmds = [c for c in pool if c.get("can_be_commander")]
        # Exact substring match
        for c in cmds:
            if c["name"].lower() in text:
                commander_hint = c["name"]
                notes.append(f"Comandante: {c['name']}")
                break
        # Word-overlap fuzzy match (≥2 palabras del nombre coinciden)
        if not commander_hint:
            for c in cmds:
                name_words = c["name"].lower().split()
                if len(name_words) >= 2:
                    hits = sum(1 for w in name_words if w in text)
                    if hits >= 2:
                        commander_hint = c["name"]
                        notes.append(f"Comandante (similar): {c['name']}")
                        break

    interpretation = " · ".join(notes) if notes else "Sin restricciones detectadas"
    return ParsedPrompt(
        colors=colors,
        archetype=archetype,
        tribe=tribe,
        commander_hint=commander_hint,
        interpretation=interpretation,
        is_mono=is_mono,
    )


# ── Selector de comandantes candidatos ────────────────────────────────────
def find_matching_commanders(
    pool: list[dict],
    colors: str | None = None,
    tribe: str | None = None,
    top_n: int = 6,
) -> list[dict]:
    """
    Devuelve hasta `top_n` comandantes de la colección que encajan
    con los criterios de color e identidad tribal.
    """
    candidates = [c for c in pool if c.get("can_be_commander")]

    # Filtro por identidad de color (exacto)
    if colors:
        target_ci = set(colors.upper())
        candidates = [
            c for c in candidates
            if set(c.get("color_identity") or []) == target_ci
        ]

    # Filtro por tribu (type_line o oracle_text)
    if tribe:
        tribe_lc = tribe.lower()
        tribal_matches = [
            c for c in candidates
            if tribe_lc in (c.get("type_line") or "").lower()
            or tribe_lc in (c.get("oracle_text") or "").lower()
        ]
        # Si hay suficientes resultados tribales, úsalos; si no, muestra todos los de color
        if tribal_matches:
            candidates = tribal_matches

    # Ordenar por edhrec_rank (más popular primero)
    candidates.sort(key=lambda c: c.get("edhrec_rank") or 999_999)
    return candidates[:top_n]
