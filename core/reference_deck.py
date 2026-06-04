"""
reference_deck.py — Mazo de referencia Bracket 2 para el constructor.

Analizado de: Jeskai Striker (Tarkir Dragonstorm Commander, 2025)
Comandante: Shiko and Narset, Unified — Jeskai (W/U/R)
Arquetipo: Spellslinger / Prowess

Este mazo es el ESTÁNDAR OFICIAL de Wizards para Bracket 2.
El builder y el LLM Critic deben usarlo como referencia de estructura,
proporciones y nivel de poder.
"""

# ────────────────────────────────────────────────────────────────────────────
# PROPORCIONES CANÓNICAS DE UN MAZO COMMANDER BRACKET 2
# (extraídas del análisis de Jeskai Striker)
# ────────────────────────────────────────────────────────────────────────────

BRACKET2_RATIOS = {
    "lands":             37,   # tierras totales
    "basics":            14,   # tierras básicas mínimas (para que funcionen las duales)
    "ramp":               8,   # aceleración de maná (rocas CMC≤2 prioritarias)
    "draw":              15,   # ventaja de cartas (mix cantrip + draw mediano + draw masivo)
    "payoffs":           12,   # cartas que implementan el plan principal
    "removal_single":     4,   # eliminación de objetivo único
    "removal_sweep":      2,   # barridos de campo
    "removal_permanent":  1,   # eliminación de permanentes no-criatura
    "finishers":          3,   # condiciones de victoria tardía
    "utility":           10,   # soporte, política, protección
    "avg_cmc":          2.8,   # CMC promedio de no-tierras (sin comandante)
}

# ────────────────────────────────────────────────────────────────────────────
# REGLAS DE ORO APRENDIDAS DEL JESKAI STRIKER
# ────────────────────────────────────────────────────────────────────────────

GOLDEN_RULES = [
    # RAMP
    "Sol Ring es obligatorio en TODOS los mazos Commander sin excepción.",
    "Incluye exactamente los Signets de los pares de colores de tu comandante (ej: Izzet+Azorius+Boros para Jeskai).",
    "Las rocas de maná deben ser CMC≤2. Rocas de CMC 3+ llegan demasiado tarde.",
    "Objetivo: 7-8 piezas de ramp para llegar con 1 roca en juego en turno 3.",

    # CARD DRAW
    "15 piezas de draw es el número correcto para Bracket 2 en 3 colores.",
    "5 de esas piezas deben ser cantrips de CMC 1 (Opt, Ponder, Preordain, Consider, Think Twice).",
    "Los cantrips de CMC 1 son el esqueleto que garantiza acción en los primeros turnos.",
    "Incluye al menos 2 draw de alto impacto (draw 3+ o draw permanente).",

    # REMOVAL
    "4 removal de objetivo único + 2 sweepers = el mínimo funcional de interacción.",
    "Swords to Plowshares es el mejor removal de blanco. Siempre inclúyelo si juegas blanco.",
    "Al menos 1 removal flexible que pueda destruir artefactos (Abrade, Prismari Command).",
    "Los sweepers asimétricos (Time Wipe, Vanquish the Horde) son mejores que los simétricos.",

    # MANABASE
    "37 tierras es el estándar. No menos de 35, no más de 38.",
    "14 tierras básicas como mínimo para que funcionen las check-lands (Glacial Fortress, etc.).",
    "Las temples (Temple of Enlightenment, etc.) con Scry compensan entrar tapeadas.",
    "Las check-lands son las mejores duales para Bracket 2 (sin coste de vida).",

    # CURVA
    "CMC promedio de 2.8-3.0 para Bracket 2. Más alto = mazo más lento.",
    "La curva debe tener su pico en CMC 2-3, no en 4-5.",
    "Finishers de CMC 7+ solo si el plan los necesita específicamente (Velomachus).",
    "Cada slot de CMC 5+ debe justificarse: ¿gana el juego o genera ventaja masiva?",

    # SINERGIA
    "10-12 piezas que implementen el plan principal. Más dilye, menos no funciona.",
    "El mazo ideal tiene 3-5 paquetes de 2-3 cartas que se refuerzan entre sí.",
    "Veyran = doblador de triggers. Busca el equivalente en cada arquetipo.",
    "Lier = recursión de conjuros. Siempre hay un equivalente en cada color.",

    # LO QUE NO TIENE UN BRACKET 2
    "Sin tutores específicos (Demonic Tutor, Imperial Seal, etc.).",
    "Sin mana rápido (Mana Crypt, Chrome Mox, Mox Diamond).",
    "Sin combos infinitos de 2 cartas.",
    "Sin cartas de extra turn (Time Walk, Temporal Manipulation en gran cantidad).",
    "Sin 'game changers' de Tier 1 (Rhystic Study, Smothering Tithe pueden subir a B3).",
]

# ────────────────────────────────────────────────────────────────────────────
# PAQUETES DE SINERGIA DEL JESKAI STRIKER (patrones replicables)
# ────────────────────────────────────────────────────────────────────────────

SYNERGY_PACKAGES = {
    "token_generation": {
        "description": "Generar tokens con cada hechizo lanzado",
        "pieces": ["Young Pyromancer", "Monastery Mentor", "Third Path Iconoclast"],
        "multiplier": "Veyran, Voice of Duality",
        "lesson": "3 generadores de tokens diferentes = redundancia. Si quitan uno, los otros siguen."
    },
    "cost_reduction": {
        "description": "Reducir el coste de instantes/conjuros",
        "pieces": ["Goblin Electromancer"],
        "lesson": "1 piezas de reducción de coste desbloquea turns donde puedes lanzar 2-3 hechizos."
    },
    "spell_recursion": {
        "description": "Reutilizar conjuros del cementerio",
        "pieces": ["Lier, Disciple of the Drowned", "Deep Analysis (Flashback)", "Think Twice (Flashback)", "Faithless Looting (Flashback)"],
        "lesson": "El Flashback convierte cada hechizo en dos. Diseña para reutilizar."
    },
    "draw_engine": {
        "description": "Motor de robo sostenido",
        "pieces": ["Whirlwind of Thought", "Archmage Emeritus"],
        "lesson": "2 draw engines permanentes son suficientes. Más de 3 es redundante."
    },
    "combat_finisher": {
        "description": "Cerrar partidas desde el combate",
        "pieces": ["Velomachus Lorehold"],
        "lesson": "Un finisher que gana por sí solo al atacar. Cada mazo necesita 1-2 así."
    },
}

# ────────────────────────────────────────────────────────────────────────────
# DISTRIBUCIÓN REAL DE JESKAI STRIKER (para validación del builder)
# ────────────────────────────────────────────────────────────────────────────

JESKAI_STRIKER_CARDS = {
    "commander": "Shiko and Narset, Unified",
    "colors": "WUR",
    "bracket": 2,
    "avg_cmc": 2.8,

    "ramp": [
        "Sol Ring", "Arcane Signet", "Azorius Signet", "Boros Signet",
        "Izzet Signet", "Fellwar Stone", "Talisman of Progress", "Mana Geyser"
    ],

    "draw": [
        "Opt", "Ponder", "Preordain", "Consider", "Think Twice",
        "Faithless Looting", "Frantic Search", "Expressive Iteration",
        "Compulsive Research", "Deep Analysis", "Ancestral Vision",
        "Whirlwind of Thought", "Archmage Emeritus",
        "Mangara, the Diplomat", "Voracious Bibliophile"
    ],

    "payoffs": [
        "Young Pyromancer", "Monastery Mentor", "Third Path Iconoclast",
        "Goblin Electromancer", "Guttersnipe", "Storm-Kiln Artist",
        "Manaform Hellkite", "Haughty Djinn", "Transcendent Dragon",
        "Veyran, Voice of Duality", "Lier, Disciple of the Drowned",
        "Elsha, Threefold Master"
    ],

    "removal": [
        "Swords to Plowshares", "Abrade", "Pongify", "Curse of the Swine",
        "Dismantling Wave", "Time Wipe", "Vanquish the Horde"
    ],

    "spell_manipulation": [
        "Narset's Reversal", "Expansion // Explosion", "Electrodominance",
        "Prismari Command", "Rite of Replication", "Sublime Epiphany"
    ],

    "finishers": [
        "Velomachus Lorehold", "Magma Opus", "Baral and Kari Zev"
    ],

    "lands": [
        "Command Tower", "Path of Ancestry", "Adarkar Wastes",
        "Battlefield Forge", "Shivan Reef", "Glacial Fortress",
        "Clifftop Retreat", "Sulfur Falls", "Skycloud Expanse",
        "Cascade Bluffs", "Rugged Prairie", "Irrigated Farmland",
        "Prairie Stream", "Temple of Enlightenment", "Temple of Epiphany",
        "Temple of Triumph", "Evolving Wilds", "Ash Barrens",
        "Exotic Orchard", "Ferrous Lake", "Perilous Landscape",
        "Reliquary Tower", "Mystic Monastery",
        # Básicas
        "Plains", "Plains", "Plains", "Plains",
        "Island", "Island", "Island", "Island", "Island",
        "Mountain", "Mountain", "Mountain", "Mountain", "Mountain"
    ],
}

# ────────────────────────────────────────────────────────────────────────────
# FUNCIÓN DE VALIDACIÓN: compara un mazo construido con el estándar
# ────────────────────────────────────────────────────────────────────────────

def validate_against_standard(deck_stats: dict) -> list[str]:
    """
    Recibe estadísticas de un mazo y devuelve advertencias si se aleja
    demasiado del estándar Bracket 2.

    deck_stats keys esperados:
        lands, ramp, draw, payoffs, removal_single, removal_sweep, avg_cmc
    """
    warnings = []
    r = BRACKET2_RATIOS

    if deck_stats.get("lands", 0) < 35:
        warnings.append(f"Pocas tierras ({deck_stats['lands']}). Mínimo recomendado: 37.")
    if deck_stats.get("ramp", 0) < 6:
        warnings.append(f"Ramp insuficiente ({deck_stats['ramp']} piezas). Mínimo: 7-8.")
    if deck_stats.get("draw", 0) < 10:
        warnings.append(f"Draw insuficiente ({deck_stats['draw']} piezas). Recomendado: 15.")
    if deck_stats.get("removal_single", 0) < 3:
        warnings.append(f"Poco removal single-target ({deck_stats['removal_single']}). Mínimo: 4.")
    if deck_stats.get("removal_sweep", 0) < 1:
        warnings.append("Sin board wipes. Necesitas al menos 1-2 sweepers.")
    if deck_stats.get("avg_cmc", 0) > 3.5:
        warnings.append(f"CMC promedio muy alto ({deck_stats['avg_cmc']:.1f}). Objetivo: ≤3.0.")
    if deck_stats.get("avg_cmc", 0) < 1.8:
        warnings.append(f"CMC promedio muy bajo ({deck_stats['avg_cmc']:.1f}). ¿Falta amenazas?")

    return warnings
