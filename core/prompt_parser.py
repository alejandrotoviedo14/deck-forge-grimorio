"""
prompt_parser.py — Interpreta prompts en lenguaje natural y los convierte
en parámetros de build para el Deck Forge.

Solo trabaja con cartas de la colección del usuario.
"""
from __future__ import annotations
import re
from typing import TypedDict

# ── Colores ────────────────────────────────────────────────────────────────
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
    # 4-colores (sin un color)
    "yore-tiller": "WUBR", "glint-eye": "UBRG", "dune-brood": "BRGW",
    "ink-treader": "RGWU", "witch-maw": "GWUB",
    # 5-colores
    "5 colores": "WUBRG", "cinco colores": "WUBRG", "5-colores": "WUBRG",
    "five color": "WUBRG", "five colour": "WUBRG", "rainbow": "WUBRG",
    "arco iris": "WUBRG", "5color": "WUBRG", "5c": "WUBRG",
}

# ── Tribus (ES + EN) → canonical (como en type_line de Scryfall) ───────────
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
    "serpiente": "Serpent", "serpientes": "Serpent",
    "serpent": "Serpent", "serpents": "Serpent",
    "kraken": "Kraken", "krakens": "Kraken",
    "leviatán": "Leviathan", "leviathan": "Leviathan",
    "pulpo": "Octopus", "octopus": "Octopus",
    "tritón": "Merfolk",
    "rata": "Rat", "ratas": "Rat", "rat": "Rat", "rats": "Rat",
    "murciélago": "Bat", "bat": "Bat", "bats": "Bat",
    "esqueleto": "Skeleton", "skeleton": "Skeleton", "skeletons": "Skeleton",
    "ogro": "Ogre", "ogros": "Ogre", "ogre": "Ogre", "ogres": "Ogre",
    "troll": "Troll", "trolls": "Troll",
    "orco": "Orc", "orcos": "Orc", "orc": "Orc", "orcs": "Orc",
    "gnomo": "Gnome", "gnomes": "Gnome",
    "gnoll": "Gnoll", "gnolls": "Gnoll",
    "tiefling": "Tiefling", "tieflings": "Tiefling",
    "eldrazi": "Eldrazi",
    "phyrexian": "Phyrexian", "phyrexiano": "Phyrexian",
    "vedalken": "Vedalken",
    "viashino": "Viashino",
    "kithkin": "Kithkin",
    "llorón": "Cephalid", "cephalid": "Cephalid",
    "rhino": "Rhino", "rhinoceros": "Rhino",
    "hippo": "Hippo", "hipopótamo": "Hippo",
    "pegaso": "Pegasus", "pegasus": "Pegasus",
    "unicornio": "Unicorn", "unicorn": "Unicorn",
    "drake": "Drake",
    "worm": "Worm", "gusano": "Worm",
    "salamander": "Salamander", "salamandra": "Salamander",
}

# ── Arquetipos — keywords y aliases ──────────────────────────────────────
ARCHETYPE_KEYWORDS: dict[str, list[str]] = {
    "counters": [
        "+1/+1", "counters", "contadores", "proliferate", "proliferar",
        "infect", "veneno", "poison", "crecer", "growth counters",
        "poison counters", "oil counters",
    ],
    "equipment": [
        "equipo", "equipment", "voltron", "equipamiento",
        "espada", "armadura", "armor", "sword", "hammer", "shield",
        "espadachín", "swordsman",
    ],
    "aristocrats": [
        "tokens", "sacrificio", "sacrifice", "aristocrats",
        "morir", "death trigger", "sac outlet", "fodder",
        "altar", "blood artist", "die trigger",
    ],
    "spellslinger": [
        "control", "hechizos", "spells", "instantes", "sorceries",
        "conjuros", "copias", "copies", "contrahechizo", "counterspell",
        "robar cartas", "draw spells", "izzet spells", "storm",
        "tormenta", "prowess",
    ],
    "blink": [
        "blink", "parpadeo", "flickering", "etb",
        "enters the battlefield", "entra al campo", "flickear",
        "flicker", "bounce", "rebotar",
    ],
    "landfall": [
        "tierras", "lands", "landfall", "caída de tierra",
        "rampear", "ramp", "fetch", "terramorfos", "mana ramp",
        "extra lands", "tierras adicionales",
    ],
    "lifegain": [
        "vida", "lifegain", "ganar vida", "curación", "heal",
        "life total", "extorsionar", "extort",
    ],
    "reanimator": [
        "reanimator", "reanimador", "cementerio", "graveyard",
        "revivir", "resurrect", "reanimar", "mill", "moler",
        "entierro", "bury", "self-mill",
    ],
    # Arquetipos extra que mapean a los existentes
    "tribal": [
        # solo se activa si hay tribu detectada
    ],
}

# Arquetipos "alias" → mapean a un arquetipo válido del backend
ARCHETYPE_ALIASES: dict[str, tuple[str, str]] = {
    # keyword → (archetype_key, label)
    "group hug":    ("spellslinger", "Group Hug (base: Spellslinger)"),
    "group-hug":    ("spellslinger", "Group Hug (base: Spellslinger)"),
    "gruphug":      ("spellslinger", "Group Hug (base: Spellslinger)"),
    "pillowfort":   ("spellslinger", "Pillowfort (base: Spellslinger)"),
    "pillow fort":  ("spellslinger", "Pillowfort (base: Spellslinger)"),
    "stax":         ("spellslinger", "Stax (base: Spellslinger)"),
    "superfriends": ("counters",     "Superfriends/Planeswalkers (base: Counters)"),
    "planeswalkers":("counters",     "Planeswalkers (base: Counters)"),
    "walkers":      ("counters",     "Planeswalkers (base: Counters)"),
    "combo":        ("spellslinger", "Combo (base: Spellslinger)"),
    "aggro":        ("aristocrats",  "Aggro Tokens (base: Aristocrats)"),
    "agresivo":     ("aristocrats",  "Aggro (base: Aristocrats)"),
    "aggresivo":    ("aristocrats",  "Aggro (base: Aristocrats)"),
    "stompy":       ("counters",     "Stompy (base: Counters)"),
    "big mana":     ("landfall",     "Big Mana (base: Landfall)"),
    "turbo lands":  ("landfall",     "Turbo Lands (base: Landfall)"),
    "turbo-lands":  ("landfall",     "Turbo Lands (base: Landfall)"),
    "voltron":      ("equipment",    "Voltron (base: Equipment)"),
    "auras":        ("equipment",    "Auras/Voltron (base: Equipment)"),
    "enchantress":  ("blink",        "Enchantress (base: Blink/ETB)"),
    "aristocratas": ("aristocrats",  "Aristócratas"),
    "tokens aggro": ("aristocrats",  "Tokens Aggro"),
    "storm":        ("spellslinger", "Storm (base: Spellslinger)"),
    "mill":         ("reanimator",   "Mill/Reanimator"),
}


# ── TypedDict de salida ────────────────────────────────────────────────────
class ParsedPrompt(TypedDict):
    colors: str | None
    archetype: str | None
    tribe: str | None
    commander_hint: str | None
    interpretation: str
    is_mono: bool


# ── Parser principal ───────────────────────────────────────────────────────
def parse_prompt(prompt: str, pool: list[dict] | None = None) -> ParsedPrompt:
    text = prompt.strip().lower()
    # normalizar tildes comunes para mayor tolerancia
    for a, b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")]:
        text = text.replace(a, b)

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
        # ordenar por longitud descendente para capturar "5 colores" antes que "colores"
        for guild, ci in sorted(GUILD_KEYWORDS.items(), key=lambda x: -len(x[0])):
            if re.search(r"\b" + re.escape(guild) + r"\b", text):
                colors = ci
                is_mono = len(ci) == 1
                label = guild.title()
                if is_mono:
                    label = f"Monocolor {COLOR_LABELS[ci]}"
                notes.append(label)
                break

    # 3. Colores sueltos
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

    # 4. Tribu — normalizar texto sin tildes para comparar
    for kw, canonical in TRIBES.items():
        kw_norm = kw
        for a, b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")]:
            kw_norm = kw_norm.replace(a, b)
        if re.search(r"\b" + re.escape(kw_norm) + r"\b", text):
            tribe = canonical
            archetype = "tribal"
            notes.append(f"Tribal {canonical}")
            break

    # 5. Arquetipos alias (group hug, voltron, combo, etc.) — primero los más largos
    if not archetype:
        for alias, (arch_key, label) in sorted(
            ARCHETYPE_ALIASES.items(), key=lambda x: -len(x[0])
        ):
            if alias in text:
                archetype = arch_key
                notes.append(label)
                break

    # 6. Arquetipos directos
    if not archetype:
        for arch_key, keywords in ARCHETYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    archetype = arch_key
                    notes.append(f"Arquetipo: {arch_key.title()}")
                    break
            if archetype:
                break

    # 7. Commander name desde la colección
    if pool:
        cmds = [c for c in pool if c.get("can_be_commander")]
        # Exact substring match (normalizado)
        for c in cmds:
            name_norm = c["name"].lower()
            for a, b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")]:
                name_norm = name_norm.replace(a, b)
            if name_norm in text:
                commander_hint = c["name"]
                notes.append(f"Comandante: {c['name']}")
                break
        # Word-overlap (≥2 palabras del nombre coinciden)
        if not commander_hint:
            for c in cmds:
                name_words = c["name"].lower().split()
                if len(name_words) >= 2:
                    hits = sum(1 for w in name_words if w in text and len(w) > 2)
                    if hits >= min(2, len(name_words)):
                        commander_hint = c["name"]
                        notes.append(f"Comandante (similar): {c['name']}")
                        break

    interpretation = " · ".join(notes) if notes else "Sin restricciones — mostrando los más populares de tu colección"
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
    is_mono: bool = False,
    top_n: int = 9,
) -> list[dict]:
    """
    Devuelve hasta `top_n` comandantes de la colección que encajan.

    Lógica de color:
    - is_mono=True  → identidad EXACTA (solo ese color)
    - guild/multi   → identidad EXACTA (exactamente esos colores)
    - color suelto  → identidad CONTIENE el color (puede tener más)
    Si el filtro estricto no da resultados, se relaja automáticamente.
    """
    candidates = [c for c in pool if c.get("can_be_commander")]

    if colors:
        target = set(colors.upper())

        if is_mono or len(target) >= 2:
            # Intento estricto: identidad exacta
            strict = [
                c for c in candidates
                if set(c.get("color_identity") or []) == target
            ]
            if strict:
                candidates = strict
            else:
                # Relajado: CI contiene todos los colores pedidos
                relaxed = [
                    c for c in candidates
                    if target.issubset(set(c.get("color_identity") or []))
                ]
                candidates = relaxed if relaxed else candidates
        else:
            # Un color suelto: CI contiene ese color
            candidates = [
                c for c in candidates
                if target.issubset(set(c.get("color_identity") or []))
            ]

    if tribe:
        tribe_lc = tribe.lower()
        tribal = [
            c for c in candidates
            if tribe_lc in (c.get("type_line") or "").lower()
            or tribe_lc in (c.get("oracle_text") or "").lower()
        ]
        # Si hay coincidencias tribales, úsalas; si no, mantener filtro de color
        if tribal:
            candidates = tribal

    # Ordenar por popularidad EDHREC (rank más bajo = más popular)
    candidates.sort(key=lambda c: c.get("edhrec_rank") or 999_999)
    return candidates[:top_n]
