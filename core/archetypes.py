"""
archetypes.py — v2 con 9 arquetipos.

Sesión 4 añade:
  - tribal       (cualquier commander con sinergia de tipo de criatura)
  - blink        (ETB abuse / flickering)
  - landfall     (triggers de tierras que entran)
  - lifegain     (acumular vida como recurso)
  - reanimator   (criaturas grandes desde el cementerio)

Los 4 originales permanecen sin cambios de API:
  - counters, equipment, aristocrats, spellslinger

AÑADIR UN ARQUETIPO NUEVO:
    1. Definir is_X_commander(card) → bool
    2. Definir el Archetype con sus Slots
    3. Añadirlo a ARCHETYPES dict
    4. Actualizar detect_archetype() con su prioridad
"""

from dataclasses import dataclass, field
from typing import Callable

from . import classifier as cls
from .pool import has_text, has_type, cmc, edhrec_rank


@dataclass
class Slot:
    """Un slot en el mazo: nombre + cuántas cartas + cómo elegirlas."""
    name: str
    target_count: int
    predicate: Callable[[dict], bool]
    scorer: Callable[[dict], float] = field(default=lambda c: edhrec_rank(c))
    role_label: str = "Synergy"
    justification: str = "Sinergia con el arquetipo."


@dataclass
class Archetype:
    """Plantilla completa de un arquetipo."""
    key: str
    name: str
    description: str
    commander_predicate: Callable[[dict], bool]
    slots: list[Slot]
    auto_includes: list[str] = field(default_factory=list)


# === Helpers de score ======================================================

def score_low_cmc_then_rank(card: dict) -> float:
    return cmc(card) * 100_000 + edhrec_rank(card)


def score_rank(card: dict) -> float:
    return edhrec_rank(card)


# ===========================================================================
# ARQUETIPOS ORIGINALES (v1 — sin cambios de API)
# ===========================================================================

# === COUNTERS ==============================================================

def is_counters_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "double the number", "+1/+1 counter", "proliferate",
        "for each +1/+1 counter",
    )
    return any(s in text for s in signals)


COUNTERS = Archetype(
    key="counters",
    name="+1/+1 Counters / Proliferate",
    description=(
        "Acumulamos +1/+1 counters en criaturas grandes. El comandante "
        "duplica counters o los reparte. Wincons: una criatura monstruosa, "
        "Simic Ascendancy a 20, Craterhoof-style alpha strike."
    ),
    commander_predicate=is_counters_commander,
    auto_includes=[
        "Simic Ascendancy", "Forgotten Ancient", "Hardened Scales",
        "Doubling Season", "Branching Evolution", "Inexorable Tide",
        "Tanazir Quandrix", "Ivy Lane Denizen", "Death's Presence",
        "Opal Palace",
    ],
    slots=[
        Slot("Ramp", 9, cls.is_ramp, score_low_cmc_then_rank,
             "Ramp", "Acelera el plan."),
        Slot("Card Draw", 9, cls.is_draw, score_rank,
             "Draw", "Mantiene cartas en mano."),
        Slot("Removal & Interaction", 8,
             lambda c: cls.is_removal(c) or cls.is_counterspell(c),
             score_rank, "Interaction", "Responde a amenazas."),
        Slot("Counter Doublers & Payoffs", 14, cls.is_counter_payoff,
             score_rank, "Payoff", "Payoff de counters: el comandante lo amplifica."),
        Slot("Wincons & Big Threats", 5, cls.is_threat, score_rank,
             "Threat", "Amenaza grande que cierra partidas."),
    ],
)


# === EQUIPMENT =============================================================

def is_equipment_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    if not card.get("is_creature"):
        return False
    signals = (
        "equipment", "equipped creature", "attach", "historic",
        "for each artifact", "voltron",
    )
    return any(s in text for s in signals)


EQUIPMENT = Archetype(
    key="equipment",
    name="Equipment Voltron",
    description=(
        "Equipamos al comandante con armas y armaduras. Lo protegemos y "
        "atacamos. Wincons: voltron damage (21 commander damage) o oneshot "
        "con Sword of stack + evasión."
    ),
    commander_predicate=is_equipment_commander,
    auto_includes=[
        "Sigarda's Aid", "Stoneforge Mystic", "Puresteel Paladin",
        "Sword of Feast and Famine", "Sword of Light and Shadow",
        "Sword of Fire and Ice", "Sword of War and Peace",
        "Blackblade Reforged", "Blade of Selves", "Skullclamp",
    ],
    slots=[
        # Ramp y removal PRIMERO para garantizar la base funcional
        Slot("Ramp", 9, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera el plan."),
        Slot("Removal & Interaction", 8,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c) or cls.is_counterspell(c),
             score_rank, "Removal", "Responde a amenazas."),
        Slot("Card Draw", 7, cls.is_draw, score_rank, "Draw", "Mantiene cartas en mano."),
        # Ahora los slots específicos del arquetipo
        Slot("Equipment", 12, cls.is_equipment, score_low_cmc_then_rank,
             "Equipment", "Arma para el comandante."),
        Slot("Equipment Synergy", 6,
             lambda c: has_text(c, "equipped creature", "equipment you control",
                                "for each equipment", "attaches to",
                                "whenever equipped creature", "equip") and not cls.is_equipment(c),
             score_rank, "Equip Care", "Premia tener muchos equipment en juego."),
        # Criaturas con sinergia real: utilidad + bajo coste + rank conocido
        Slot("Soporte & Cuerpos", 5,
             lambda c: c.get("is_creature") and cmc(c) <= 3
             and c.get("edhrec_rank") is not None
             and c.get("edhrec_rank") <= 15000
             and (
                 cls.is_draw(c) or cls.is_ramp(c) or cls.is_removal(c) or
                 has_text(c, "equipment", "equipped", "artifact",
                          "whenever this creature attacks", "whenever equipped",
                          "when this creature enters", "first strike", "double strike",
                          "vigilance", "haste", "lifelink", "deathtouch")
             ),
             score_rank, "Beater", "Cuerpo con sinergia para equipar."),
        Slot("Wincons & Amenazas", 5,
             lambda c: c.get("is_creature")
             and c.get("edhrec_rank") is not None
             and cmc(c) >= 4
             and (
                 # Alta sinergia EDHREC con este comandante específico
                 c.get("edhrec_score", 0) >= 0.4
                 # O criatura con evasión o sinergia combat relevante
                 or has_text(c, "flying", "trample", "menace", "double strike",
                             "first strike", "unblockable", "can't be blocked",
                             "deals combat damage", "whenever this creature attacks",
                             "whenever equipped", "equipment", "artifact")
                 # O rank muy alto (top 1500 = jugada en muchos mazos RW)
                 or (c.get("edhrec_rank") or 999999) <= 1500
             ),
             score_rank, "Wincon", "Amenaza que cierra partidas."),
    ],
)


# === ARISTOCRATS ===========================================================

def is_aristocrats_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "whenever a creature you control dies",
        "whenever another creature dies",
        "sacrifice a creature",
        "creature tokens", "create a 1/1",
    )
    return any(s in text for s in signals)


ARISTOCRATS = Archetype(
    key="aristocrats",
    name="Tokens / Sacrifice / Drain",
    description=(
        "Generamos tokens, los sacrificamos, beneficios al morir. Drain "
        "incremental como wincon. Engine de cementerio."
    ),
    commander_predicate=is_aristocrats_commander,
    auto_includes=[
        "Blood Artist", "Zulaport Cutthroat", "Skullclamp",
        "Phyrexian Altar", "Ashnod's Altar", "Pitiless Plunderer",
        "Bastion of Remembrance", "Black Market Connections",
    ],
    slots=[
        Slot("Ramp", 8, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera."),
        Slot("Card Draw", 7, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Removal", 6, lambda c: cls.is_removal(c) or cls.is_sweeper(c),
             score_rank, "Removal", "Responde."),
        Slot("Token Generators", 10, cls.is_token_maker, score_rank,
             "Tokens", "Genera cuerpos sacrificables."),
        Slot("Sacrifice Outlets", 5, cls.is_sac_outlet, score_low_cmc_then_rank,
             "Sac Outlet", "Convierte criaturas en valor."),
        Slot("Death Triggers / Drain", 9, cls.is_death_trigger, score_rank,
             "Death Payoff", "Premia que mueran criaturas."),
        Slot("Big Wincons", 3,
             lambda c: cls.is_drain(c) or (cls.is_threat(c) and cmc(c) >= 5),
             score_rank, "Wincon", "Cierra partidas."),
    ],
)


# === SPELLSLINGER ==========================================================

def is_spellslinger_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    if not card.get("is_creature"):
        return False
    signals = (
        "whenever you cast an instant", "whenever you cast a sorcery",
        "whenever you cast a noncreature", "magecraft", "copy target",
        "copy that spell", "whenever you copy", "demonstrate",
        "instant and sorcery spells you cast", "instant or sorcery",
    )
    return any(s in text for s in signals)


SPELLSLINGER = Archetype(
    key="spellslinger",
    name="Spellslinger / Cantrips",
    description=(
        "Lanzamos instantes y conjuros para potenciar payoffs (tokens, daño, draw). "
        "Referencia: Jeskai Striker (WotC precon 2025) — 15 draw, 12 payoffs, 8 ramp, 7 removal. "
        "Wincons: ejército de tokens, daño incremental, finisher de combate (Velomachus-style)."
    ),
    commander_predicate=is_spellslinger_commander,
    auto_includes=[
        # Core payoffs que deben estar si están disponibles
        "Young Pyromancer", "Guttersnipe", "Monastery Mentor",
        "Goblin Electromancer", "Veyran, Voice of Duality",
    ],
    slots=[
        # RAMP PRIMERO — base funcional antes que el plan específico
        Slot("Ramp", 8,
             lambda c: cls.is_ramp(c) and has_type(c, "Artifact"),
             score_low_cmc_then_rank, "Ramp",
             "Roca de maná — garantiza curva fluida. Sol Ring + Signets son obligatorios."),

        # DRAW — 15 piezas es el estándar (Jeskai Striker)
        # Split: 5 cantrips CMC≤1 + 10 draw restante
        Slot("Cantrips CMC 1", 5,
             lambda c: cls.is_draw(c) and not c.get("is_land") and int(c.get("cmc") or 0) <= 1,
             score_low_cmc_then_rank, "Cantrip",
             "Cantrip de CMC 1 — columna vertebral de consistencia (Opt, Ponder, Preordain)."),
        Slot("Card Draw", 10,
             lambda c: cls.is_draw(c) and not c.get("is_land") and int(c.get("cmc") or 0) >= 2,
             score_rank, "Draw",
             "Draw sostenido — mantiene la mano llena en turnos medios y tardíos."),

        # PAYOFFS — 12 criaturas/permanentes que se benefician de lanzar hechizos
        Slot("Spellslinger Payoffs", 12, cls.is_spellslinger_payoff, score_rank,
             "Payoff",
             "Permanente que genera ventaja por cada hechizo lanzado."),

        # REMOVAL — 4 single + 2 sweepers según estándar Jeskai Striker
        Slot("Removal & Interaction", 7,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c) or cls.is_counterspell(c),
             score_low_cmc_then_rank, "Removal",
             "Eliminación — responde amenazas y limpia el campo cuando sea necesario."),
    ],
)


# ===========================================================================
# ARQUETIPOS NUEVOS (sesión 4)
# ===========================================================================

# === TRIBAL ================================================================

def is_tribal_commander(card: dict) -> bool:
    """
    Comandante con sinergia tribal: premian un tipo de criatura específico.
    Señales: "creatures you control of the chosen type", "other [Type]s you control",
    "as long as you control", o keyword Kindred.
    """
    text = (card.get("oracle_text") or "").lower()
    keywords = [k.lower() for k in (card.get("keywords") or [])]
    if "kindred" in keywords:
        return True
    signals = (
        "creatures you control of the chosen type",
        "other creatures you control get +",
        "other creatures you control have",
        "each other creature you control",
        "choose a creature type",
        "of that creature type",
        "share a creature type with",
        # Lords con tipo específico: "other Cats you control", "other Elves you control"
        "you control get +",   # "other [Type]s you control get +"
        "you control have",    # "other [Type]s you control have"
    )
    return any(s in text for s in signals)


TRIBAL = Archetype(
    key="tribal",
    name="Tribal / Kindred",
    description=(
        "Construimos en torno a un tipo de criatura. El comandante amplifica "
        "a todos los de ese tipo. Wincons: board wide, lords acumulados, "
        "attackers con anthems."
    ),
    commander_predicate=is_tribal_commander,
    auto_includes=[
        "Vanquisher's Banner", "Herald's Horn", "Coat of Arms",
        "Kindred Discovery", "Kindred Summons", "Door of Destinies",
        "Shared Animosity", "Heirloom Blade",
    ],
    slots=[
        Slot("Ramp", 8, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera."),
        Slot("Card Draw", 8, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Removal & Interaction", 7,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c),
             score_rank, "Removal", "Responde."),
        Slot("Tribal Payoffs & Lords", 12, cls.is_tribal_payoff,
             score_rank, "Tribal", "Lord o payoff tribal."),
        Slot("Criaturas del mismo tipo", 12,
             lambda c: c.get("is_creature") and cmc(c) <= 5,
             score_low_cmc_then_rank, "Tribe Member", "Cuerpo del tipo correcto."),
    ],
)


# === BLINK =================================================================

def is_blink_commander(card: dict) -> bool:
    """
    Comandante que flickea o se beneficia de ETB.
    Señales: "exile ~ return", "whenever ~ enters", "leaves the battlefield".
    """
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "exile target creature you control, then return",
        "exile target permanent you control, then return",
        "exile any number of target",  # Brago: "exile any number of target nonland permanents"
        "then return those cards to the battlefield",
        "when this creature enters the battlefield",
        "whenever a creature enters the battlefield under your control",
        "whenever another creature enters",
        "leaves the battlefield",
        "blink",
    )
    return any(s in text for s in signals)


BLINK = Archetype(
    key="blink",
    name="Blink / ETB Abuse",
    description=(
        "Exiliamos y retornamos criaturas para repetir sus ETBs. "
        "El comandante flickea o premia entradas al campo. "
        "Wincons: value engine infinito, ETB combos, acumulación de ventaja."
    ),
    commander_predicate=is_blink_commander,
    auto_includes=[
        "Ephemerate", "Conjurer's Closet", "Teleportation Circle",
        "Panharmonicon", "Brago, King Eternal", "Restoration Angel",
        "Eerie Interlude", "Soulherder",
    ],
    slots=[
        Slot("Ramp", 8, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera."),
        Slot("Card Draw", 8, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Removal & Interaction", 7,
             lambda c: cls.is_removal(c) or cls.is_counterspell(c),
             score_rank, "Interaction", "Responde."),
        Slot("ETB Payoffs (criaturas con ETB fuerte)", 14, cls.is_blink_payoff,
             score_rank, "ETB Target", "ETB valioso al flickear."),
        Slot("Blink Enablers", 8,
             lambda c: has_text(c, "exile target creature you control",
                                "exile target permanent you control, then return",
                                "blink", "flicker"),
             score_low_cmc_then_rank, "Blink Spell", "Exilia y retorna criaturas."),
    ],
)


# === LANDFALL ==============================================================

def is_landfall_commander(card: dict) -> bool:
    """Comandante con landfall trigger o que permite extra land drops."""
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "landfall", "whenever a land enters the battlefield",
        "whenever a land you control enters",
        "play an additional land", "put a land card from your hand",
        "land cards from your library",
    )
    return any(s in text for s in signals)


LANDFALL = Archetype(
    key="landfall",
    name="Landfall / Land Matters",
    description=(
        "Ponemos tierras en juego lo más rápido posible. Cada tierra "
        "dispara efectos. Wincons: criaturas masivas por landfall, "
        "Scapeshift combo, advantage aplastante."
    ),
    commander_predicate=is_landfall_commander,
    auto_includes=[
        "Scute Swarm", "Avenger of Zendikar", "Lotus Cobra",
        "Tireless Tracker", "Explore", "Cultivate", "Kodama's Reach",
        "Horn of Greed", "Azusa, Lost but Seeking",
    ],
    slots=[
        Slot("Land Ramp (fetch extra lands)", 14, cls.is_ramp,
             score_low_cmc_then_rank, "Ramp", "Pone tierras adicionales."),
        Slot("Card Draw", 7, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Removal & Interaction", 7,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c),
             score_rank, "Removal", "Responde."),
        Slot("Landfall Payoffs", 12, cls.is_landfall_payoff,
             score_rank, "Landfall", "Trigger o payoff de landfall."),
        Slot("Wincon Threats", 5, cls.is_threat, score_rank,
             "Wincon", "Cierra partidas."),
    ],
)


# === LIFEGAIN ==============================================================

def is_lifegain_commander(card: dict) -> bool:
    """Comandante que premia ganar vida o que genera vida como recurso."""
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "whenever you gain life",
        "whenever a player gains life",
        "gain life equal",
        "you gain life",
        "life link",
        "lifelink",
        "whenever this deals combat damage",  # + lifelink combo
    )
    has_lifegain = any(s in text for s in signals)
    # Debe premiar la vida ganada, no solo ganarla
    payoff_signals = (
        "whenever you gain life",
        "for each life you gained",
        "you have more life than",
        "equal to your life total",
    )
    return any(s in text for s in payoff_signals) or (
        has_lifegain and "you gain" in text and "you may" in text
    )


LIFEGAIN = Archetype(
    key="lifegain",
    name="Lifegain / Life Matters",
    description=(
        "Ganamos vida masivamente y convertimos esa vida en ventaja. "
        "El comandante premia cada punto ganado. Wincons: Aetherflux "
        "Reservoir, criaturas gigantes por life total, drain loop."
    ),
    commander_predicate=is_lifegain_commander,
    auto_includes=[
        "Aetherflux Reservoir", "Soul Warden", "Soul's Attendant",
        "Essence Warden", "Vito, Thorn of the Dusk Rose",
        "Sanguine Bond", "Exquisite Blood",
        "Dawn of Hope", "Heliod, Sun-Crowned",
    ],
    slots=[
        Slot("Ramp", 7, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera."),
        Slot("Card Draw", 7, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Removal & Interaction", 7,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c),
             score_rank, "Removal", "Responde."),
        Slot("Lifegain Payoffs", 12, cls.is_lifegain_payoff,
             score_rank, "Lifegain Payoff", "Premia ganar vida."),
        Slot("Lifegain Sources", 9,
             lambda c: has_text(c, "you gain", "lifelink", "gain life") and not c.get("is_land"),
             score_low_cmc_then_rank, "Life Source", "Fuente de vida."),
        Slot("Wincon", 3,
             lambda c: has_text(c, "aetherflux", "sanguine bond", "exquisite") or cls.is_threat(c),
             score_rank, "Wincon", "Cierra partidas."),
    ],
)


# === REANIMATOR ============================================================

def is_reanimator_commander(card: dict) -> bool:
    """
    Comandante que reanima o que facilita llenar el cementerio.
    """
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "from your graveyard to the battlefield",
        "return target creature card from a graveyard",
        "put target creature card from a graveyard",
        "whenever a creature card is put into a graveyard",
        "mill", "discard a card", "discard up to",
        "from your library into your graveyard",
        "graveyard as though it had flash",
    )
    return any(s in text for s in signals)


REANIMATOR = Archetype(
    key="reanimator",
    name="Reanimator / Graveyard",
    description=(
        "Llenamos el cementerio de criaturas grandes y las devolvemos "
        "al campo gratis. El comandante facilita el discard/mill o "
        "reanimates directamente. Wincons: criatura 8+ en turno 3-4."
    ),
    commander_predicate=is_reanimator_commander,
    auto_includes=[
        "Reanimate", "Animate Dead", "Dance of the Dead",
        "Entomb", "Buried Alive", "Victimize",
        "Sheoldred, Whispering One", "Grave Titan",
    ],
    slots=[
        Slot("Ramp", 8, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera."),
        Slot("Card Draw", 6, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Removal & Interaction", 6,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c),
             score_rank, "Removal", "Responde."),
        Slot("Reanimation Spells", 9, cls.is_recursion,
             score_low_cmc_then_rank, "Reanimate", "Devuelve cartas del cementerio."),
        Slot("Enablers (discard / mill)", 7,
             lambda c: has_text(c, "discard", "mill", "put the top",
                                "into your graveyard") and not c.get("is_land"),
             score_low_cmc_then_rank, "Enabler", "Llena el cementerio."),
        Slot("Reanimator Targets (criaturas 6+)", 9, cls.is_reanimator_payoff,
             score_rank, "Target", "Criatura grande para reanimar."),
    ],
)


# ===========================================================================
# ARQUETIPOS v3 — basados en EDHREC / Scryfall (10 nuevos)
# ===========================================================================

# === TOKENS (go-wide) ======================================================

def is_tokens_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "create a 1/1", "create two 1/1", "create three 1/1",
        "create x 1/1", "create a 2/2", "create a token",
        "whenever you attack, create",
        "whenever you cast a spell, create a",
        "populate",
        "double the number of tokens",
        "creates a token",
    )
    return any(s in text for s in signals)


TOKENS = Archetype(
    key="tokens",
    name="Tokens / Go-Wide",
    description=(
        "Generamos oleadas de tokens para dominar el campo de batalla. "
        "El comandante fabrica o duplica tokens. Potenciamos el ejército "
        "con anthems y lo mandamos todo a atacar. Wincons: combate amplio, "
        "Overrun effects, Anointed Procession loops."
    ),
    commander_predicate=is_tokens_commander,
    auto_includes=[
        "Anointed Procession", "Parallel Lives", "Doubling Season",
        "Intangible Virtue", "Cathars' Crusade",
        "Craterhoof Behemoth", "Triumph of the Hordes",
    ],
    slots=[
        Slot("Ramp", 8, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera."),
        Slot("Card Draw", 8, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Removal & Sweepers", 7,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c),
             score_rank, "Removal", "Responde."),
        Slot("Token Generators", 12, cls.is_token_maker,
             score_rank, "Token Gen", "Crea cuerpos de tokens."),
        Slot("Anthems & Token Payoffs", 8, cls.is_token_payoff,
             score_rank, "Anthem", "Potencia el ejército de tokens."),
        Slot("Finisher / Alpha Strike", 5, cls.is_threat,
             score_rank, "Wincon", "Efectos overrun o cierre de partida."),
    ],
)


# === GROUP HUG ============================================================

def is_group_hug_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "each player draws",
        "each player may draw",
        "each opponent draws",
        "players draw cards",
        "each player gains",
        "each player may put",
        "each player may play an additional",
        "each player may search their library",
        "whenever a player draws",
        "each player gets an emblem",
    )
    return any(s in text for s in signals)


GROUP_HUG = Archetype(
    key="group_hug",
    name="Group Hug / Política",
    description=(
        "Beneficiamos a todos los jugadores: cartas extra, maná adicional, "
        "recursos compartidos. Creamos alianzas políticas y aprovechamos "
        "la ventaja acumulada mejor que nadie. Wincons: combo oculto, "
        "fatiga controlada, o aliar a todos contra el jugador más peligroso."
    ),
    commander_predicate=is_group_hug_commander,
    auto_includes=[
        "Howling Mine", "Dictate of Kruphix", "Temple Bell",
        "Rites of Flourishing", "Collective Voyage",
        "Minds Aglow", "Prosperity",
    ],
    slots=[
        Slot("Ramp", 8, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera."),
        Slot("Card Draw", 7, cls.is_draw, score_rank, "Draw", "Card flow propio."),
        Slot("Removal & Counterspells", 6,
             lambda c: cls.is_removal(c) or cls.is_counterspell(c),
             score_rank, "Interaction", "Responde selectivamente."),
        Slot("Group Hug Effects", 14, cls.is_group_hug_piece,
             score_rank, "Group Hug", "Beneficia a todos los jugadores."),
        Slot("Pillowfort / Proteccion", 7, cls.is_pillowfort_piece,
             score_rank, "Fort", "Nos protege mientras somos generosos."),
        Slot("Wincons Politicos", 6,
             lambda c: cls.is_threat(c) or cls.is_drain(c),
             score_rank, "Wincon", "Cierra cuando el momento politico es correcto."),
    ],
)


# === ENCHANTRESS ==========================================================

def is_enchantress_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "whenever you cast an enchantment",
        "whenever an enchantment enters the battlefield under your control",
        "whenever an enchantment enters",
        "enchantress",
        "for each enchantment you control",
        "enchantment spells you cast cost",
        "whenever you attach an aura",
        "whenever an aura becomes attached",
    )
    return any(s in text for s in signals)


ENCHANTRESS = Archetype(
    key="enchantress",
    name="Enchantress / Encantamientos",
    description=(
        "Construimos una red de encantamientos que generan ventaja al "
        "entrar o existir. El comandante es un motor de robo por encantamientos. "
        "Wincons: tablero bloqueado con encantamientos de control + criatura "
        "enorme buffeada con Auras, o combo de encantamientos."
    ),
    commander_predicate=is_enchantress_commander,
    auto_includes=[
        "Argothian Enchantress", "Enchantress's Presence", "Sythis, Harvest's Hand",
        "Sphere of Safety", "Sigil of the Empty Throne", "Starfield of Nyx",
        "Greater Auramancy", "Sterling Grove",
    ],
    slots=[
        Slot("Ramp", 7, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera."),
        Slot("Card Draw", 8, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Removal", 7,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c),
             score_rank, "Removal", "Responde."),
        Slot("Enchantress Draw Engines", 10, cls.is_enchantment_payoff,
             score_rank, "Enchantress", "Roba cartas por encantamientos."),
        Slot("Auras & Utility Enchantments", 12,
             lambda c: cls.is_aura(c) and not has_type(c, "Land"),
             score_low_cmc_then_rank, "Aura", "Aura ofensiva o defensiva."),
        Slot("Wincon Enchantments", 4,
             lambda c: cls.is_threat(c) or has_text(c, "starfield", "omniscience", "sigil of"),
             score_rank, "Wincon", "Cierra partidas."),
    ],
)


# === ARTIFACTS ============================================================

def is_artifacts_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "whenever you cast an artifact",
        "whenever an artifact enters the battlefield",
        "whenever an artifact enters",
        "for each artifact you control",
        "artifact creatures you control",
        "affinity for artifacts",
        "metalcraft",
        "artifacts you control have",
        "artifacts you control get",
    )
    return any(s in text for s in signals)


ARTIFACTS = Archetype(
    key="artifacts",
    name="Artifact Synergy / Urza-Style",
    description=(
        "Construimos un tablero denso de artefactos que se potencian entre si. "
        "Cada artefacto que entra dispara ventaja. Wincons: combo de artefactos, "
        "criatura indestructible con Darksteel + overrun, o Hellkite Tyrant."
    ),
    commander_predicate=is_artifacts_commander,
    auto_includes=[
        "Thopter Foundry", "Sword of the Meek",
        "Krark-Clan Ironworks", "Darksteel Forge",
    ],
    slots=[
        Slot("Artifact Ramp", 12,
             lambda c: cls.is_ramp(c) and has_type(c, "Artifact"),
             score_low_cmc_then_rank, "Art Ramp", "Roca de mana artefacto."),
        Slot("Card Draw", 8, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Removal & Interaction", 7,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c),
             score_rank, "Removal", "Responde."),
        Slot("Artifact Synergy & Payoffs", 12, cls.is_artifact_payoff,
             score_rank, "Art Payoff", "Payoff de artefactos."),
        Slot("Artifact Threats", 5,
             lambda c: cls.is_threat(c) and has_type(c, "Artifact"),
             score_rank, "Art Threat", "Amenaza artefacto."),
    ],
)


# === VOLTRON (aura-based) ================================================

def is_voltron_commander(card: dict) -> bool:
    if not card.get("is_creature"):
        return False
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "whenever this creature deals combat damage to a player",
        "aura you control",
        "auras attached to",
        "for each aura attached",
        "equipped or enchanted",
        "whenever an aura becomes attached to this creature",
        "for each equipment and aura",
    )
    keywords = [k.lower() for k in (card.get("keywords") or [])]
    evasion = {"flying", "shadow", "menace", "fear", "intimidate", "trample", "unblockable"}
    has_evasion = any(k in keywords for k in evasion)
    has_aura_signal = any(s in text for s in signals)
    return has_aura_signal or (
        has_evasion
        and "deals combat damage to a player" in text
        and cmc(card) <= 3
    )


VOLTRON = Archetype(
    key="voltron",
    name="Voltron / Auras",
    description=(
        "Convertimos al comandante en una fuerza imparable cargada de Auras. "
        "La clave es evasion + proteccion + pump. Wincons: 21 puntos de dano "
        "de comandante (voltron clasico) o Infect con 10 veneno."
    ),
    commander_predicate=is_voltron_commander,
    auto_includes=[
        "Ethereal Armor", "All That Glitters", "Rancor",
        "Aqueous Form", "Shielded by Faith", "Sage's Reverie",
        "Hyena Umbra", "Eldrazi Conscription",
    ],
    slots=[
        Slot("Ramp", 8, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera."),
        Slot("Card Draw", 6, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Auras Ofensivas", 12, cls.is_aura,
             score_low_cmc_then_rank, "Aura", "Buff para el comandante."),
        Slot("Proteccion (hexproof/indestructible)", 8, cls.is_protection,
             score_low_cmc_then_rank, "Protection", "Protege al comandante."),
        Slot("Tutores de Auras", 5, cls.is_tutor, score_rank,
             "Tutor", "Busca las Auras clave."),
        Slot("Removal & Interaction", 5,
             lambda c: cls.is_removal(c) or cls.is_counterspell(c),
             score_rank, "Removal", "Responde amenazas."),
    ],
)


# === STAX =================================================================

def is_stax_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "spells cost {1} more",
        "spells cost {2} more",
        "each spell costs {1} more",
        "each spell costs {2} more",
        "players can't cast more than one spell",
        "opponents can't cast spells",
        "opponents can't draw",
        "players can't search their libraries",
        "nonbasic lands don't untap",
        "permanents don't untap",
        "whenever an opponent casts a spell, that player pays",
        "whenever a player casts a spell, they pay",
    )
    return any(s in text for s in signals)


STAX = Archetype(
    key="stax",
    name="Stax / Prison / Control Asimetrico",
    description=(
        "Imponemos costes adicionales y restricciones a todos los jugadores, "
        "pero construimos en torno a evitarlos nosotros mismos. Ganamos "
        "mientras el tablero esta bloqueado. Wincons: ventaja acumulada "
        "bajo lock, combo con mana libre, o criatura indestructible imparable."
    ),
    commander_predicate=is_stax_commander,
    auto_includes=[
        "Smokestack", "Winter Orb", "Static Orb", "Tangle Wire",
        "Thalia, Guardian of Thraben",
        "Drannith Magistrate", "Rule of Law",
    ],
    slots=[
        Slot("Ramp (asimetrico)", 9, cls.is_ramp,
             score_low_cmc_then_rank, "Ramp", "Aceleramos sin afectarnos."),
        Slot("Card Draw", 7, cls.is_draw, score_rank, "Draw", "Mantenemos ventaja."),
        Slot("Stax / Lock Pieces", 12, cls.is_stax_piece,
             score_rank, "Stax", "Niega recursos a los rivales."),
        Slot("Removal & Interaction", 7,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c),
             score_rank, "Removal", "Responde sin romper el lock."),
        Slot("Hatebears", 7,
             lambda c: c.get("is_creature") and cls.is_stax_piece(c),
             score_rank, "Hatebear", "Criatura con efecto de stax."),
        Slot("Wincons bajo Lock", 4,
             lambda c: cls.is_threat(c) and cmc(c) <= 5,
             score_rank, "Wincon", "Cierra mientras el tablero esta bloqueado."),
    ],
)


# === MILL =================================================================

def is_mill_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "target player mills",
        "each player mills",
        "target opponent mills",
        "each opponent mills",
        "whenever a card is put into an opponent",
        "whenever a card is put into a graveyard from a library",
        "each opponent puts the top",
        "mill x",
        "mill {x}",
        "cards from target player's library",
    )
    return any(s in text for s in signals)


MILL = Archetype(
    key="mill",
    name="Mill / Biblioteca Vacia",
    description=(
        "Vaciamos las bibliotecas de los rivales. Cada carta molida cuenta. "
        "Aceleramos con efectos de mill masivo y bloqueamos la recuperacion. "
        "Wincons: oponente sin cartas en biblioteca, "
        "Altar of Dementia combo, o Bruvac multiplicador."
    ),
    commander_predicate=is_mill_commander,
    auto_includes=[
        "Bruvac the Grandiloquent", "Fraying Sanity", "Traumatize",
        "Maddening Cacophony", "Altar of Dementia",
        "Consuming Aberration",
    ],
    slots=[
        Slot("Ramp", 8, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera."),
        Slot("Card Draw", 7, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Removal & Interaction", 7,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c),
             score_rank, "Removal", "Responde."),
        Slot("Mill Effects", 14, cls.is_mill_piece,
             score_rank, "Mill", "Manda cartas al cementerio rival."),
        Slot("Mill Payoffs & Wincons", 8,
             lambda c: has_text(c, "graveyard", "whenever a creature card",
                                "power equal to") or cls.is_threat(c),
             score_rank, "Wincon", "Payoff de mill o cierra partidas."),
    ],
)


# === BIG MANA =============================================================

def is_big_mana_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "untap all lands you control",
        "untap up to",
        "double the amount of mana",
        "doubles the amount of mana",
        "whenever you tap a land for mana",
        "add mana equal",
        "for each land you control, add",
        "spend mana as though it were mana of any color",
    )
    return any(s in text for s in signals)


BIG_MANA = Archetype(
    key="big_mana",
    name="Big Mana / X Spells",
    description=(
        "Generamos cantidades absurdas de mana y lo gastamos en hechizos-X "
        "devastadores o criaturas descomunales. El comandante desbloquea el "
        "potencial de mana. Wincons: Torment of Hailfire con X=20, "
        "Finale of Devastation, o criatura indestructible masiva."
    ),
    commander_predicate=is_big_mana_commander,
    auto_includes=[
        "Selvala, Heart of the Wilds", "Mana Reflection",
        "Torment of Hailfire", "Finale of Devastation",
        "Nyxbloom Ancient", "Doubling Cube",
    ],
    slots=[
        Slot("Ramp Masivo", 14, cls.is_ramp,
             score_low_cmc_then_rank, "Ramp", "Genera mana adicional masivo."),
        Slot("Card Draw", 8, cls.is_draw, score_rank, "Draw", "Mantiene mano llena."),
        Slot("Removal & Interaction", 7,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c),
             score_rank, "Removal", "Responde."),
        Slot("Mana Doublers", 5, cls.is_big_mana_piece,
             score_rank, "Mana Doubler", "Dobla el mana disponible."),
        Slot("X-Spells & Finishers", 10,
             lambda c: cls.is_big_mana_piece(c) or (cls.is_threat(c) and cmc(c) >= 6),
             score_rank, "X-Spell", "Gasta el mana masivo como wincon."),
    ],
)


# === SUPERFRIENDS =========================================================

def is_superfriends_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    type_line = (card.get("type_line") or "").lower()
    if "planeswalker" in type_line:
        return True
    signals = (
        "planeswalker you control",
        "whenever you cast a planeswalker",
        "each planeswalker you control",
        "planeswalkers you control have",
        "loyalty counters on planeswalkers",
        "planeswalkers can be your commander",
        "whenever you activate a loyalty ability",
    )
    return any(s in text for s in signals)


SUPERFRIENDS = Archetype(
    key="superfriends",
    name="Superfriends / Planeswalkers",
    description=(
        "Desplegamos una flota de Planeswalkers y los protegemos hasta "
        "que ganen el juego por si solos. El comandante acelera las lealtades "
        "o anade planeswalkers en la zona de comando. Wincons: emblemas acumulados, "
        "ultimate devastadora, o combo con Doubling Season."
    ),
    commander_predicate=is_superfriends_commander,
    auto_includes=[
        "Doubling Season", "Deepglow Skate", "Spark Double",
        "The Chain Veil", "Oath of Teferi",
        "Teferi, Temporal Archmage",
    ],
    slots=[
        Slot("Ramp", 9, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera."),
        Slot("Card Draw", 7, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Planeswalkers", 12, cls.is_superfriends_payoff,
             score_rank, "Planeswalker", "Planeswalker potente para el equipo."),
        Slot("Proteccion de Planeswalkers", 8,
             lambda c: cls.is_token_maker(c) or cls.is_pillowfort_piece(c),
             score_rank, "PW Protection", "Genera cuerpos para bloquear o muro."),
        Slot("Proliferate & Loyalty Synergy", 5,
             lambda c: has_text(c, "proliferate", "loyalty counter", "additional loyalty"),
             score_rank, "Loyalty", "Anade contadores de lealtad."),
        Slot("Tutores & Wincons", 5,
             lambda c: cls.is_tutor(c) or cls.is_threat(c),
             score_rank, "Tutor/Win", "Busca al planeswalker correcto."),
    ],
)


# === PILLOWFORT ===========================================================

def is_pillowfort_commander(card: dict) -> bool:
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "creatures can't attack you",
        "creatures can't attack you unless",
        "whenever a creature attacks you",
        "whenever a player attacks you",
        "damage that would be dealt to you",
        "you have hexproof",
        "you and permanents you control have hexproof",
        "opponents can't attack you",
        "prevent all combat damage that would be dealt to you",
    )
    return any(s in text for s in signals)


PILLOWFORT = Archetype(
    key="pillowfort",
    name="Pillowfort / Defensa Absoluta",
    description=(
        "Construimos un castillo inexpugnable de encantamientos y permanentes "
        "que hacen imposible o carisimo atacarnos. Ganamos mientras los rivales "
        "se destruyen entre si. Wincons: fatiga al resto de la mesa, combo "
        "lento, o enchantment bomb (Felidar Sovereign, Approach of the Second Sun)."
    ),
    commander_predicate=is_pillowfort_commander,
    auto_includes=[
        "Ghostly Prison", "Propaganda", "Sphere of Safety",
        "Collective Restraint", "Solitary Confinement",
        "Windborn Muse", "Norn's Annex",
    ],
    slots=[
        Slot("Ramp", 8, cls.is_ramp, score_low_cmc_then_rank, "Ramp", "Acelera."),
        Slot("Card Draw", 8, cls.is_draw, score_rank, "Draw", "Card flow."),
        Slot("Pillowfort Pieces", 14, cls.is_pillowfort_piece,
             score_rank, "Fort", "Impide o encarece los ataques rivales."),
        Slot("Removal & Sweepers", 7,
             lambda c: cls.is_removal(c) or cls.is_sweeper(c),
             score_rank, "Removal", "Responde amenazas que si llegan."),
        Slot("Card Advantage Over Time", 5,
             lambda c: cls.is_draw(c) and cmc(c) >= 3,
             score_rank, "Draw Engine", "Engine sostenido a largo plazo."),
        Slot("Wincons Lentos", 6,
             lambda c: cls.is_threat(c) or cls.is_drain(c) or has_text(
                 c, "sovereign", "approach of the second sun",
                 "test of endurance"
             ),
             score_rank, "Wincon", "Cierra partidas sin combate directo."),
    ],
)


# ===========================================================================
# Registry
# ===========================================================================

ARCHETYPES: dict[str, Archetype] = {
    # Originales (v1)
    "counters":     COUNTERS,
    "equipment":    EQUIPMENT,
    "aristocrats":  ARISTOCRATS,
    "spellslinger": SPELLSLINGER,
    # Sesión 4 (v2)
    "tribal":       TRIBAL,
    "blink":        BLINK,
    "landfall":     LANDFALL,
    "lifegain":     LIFEGAIN,
    "reanimator":   REANIMATOR,
    # v3 — basados en EDHREC/Scryfall
    "tokens":       TOKENS,
    "group_hug":    GROUP_HUG,
    "enchantress":  ENCHANTRESS,
    "artifacts":    ARTIFACTS,
    "voltron":      VOLTRON,
    "stax":         STAX,
    "mill":         MILL,
    "big_mana":     BIG_MANA,
    "superfriends": SUPERFRIENDS,
    "pillowfort":   PILLOWFORT,
}


# ───────────────────────────────────────────────────────────────────────────
# THEME → ARCHETYPE (v4): mapeo de themes de EDHREC a nuestros 19 keys.
# Los themes vienen del caché de edhrec_advisor (fetch_commander_data → "themes")
# y reflejan cómo la comunidad REALMENTE juega cada comandante.
# ───────────────────────────────────────────────────────────────────────────

THEME_TO_ARCHETYPE: dict[str, str] = {
    "tokens": "tokens",
    "+1/+1 counters": "counters", "counters": "counters",
    "proliferate": "counters", "infect": "counters",
    "group hug": "group_hug", "wheels": "group_hug",
    "stax": "stax", "prison": "stax", "hatebears": "stax", "group slug": "stax",
    "mill": "mill",
    "voltron": "voltron", "auras": "voltron",
    "equipment": "equipment",
    "enchantress": "enchantress", "enchantments": "enchantress",
    "artifacts": "artifacts", "treasure": "artifacts", "affinity": "artifacts",
    "lifegain": "lifegain", "lifedrain": "lifegain",
    "reanimator": "reanimator", "graveyard": "reanimator",
    "self-mill": "reanimator", "dredge": "reanimator",
    "aristocrats": "aristocrats", "sacrifice": "aristocrats",
    "spellslinger": "spellslinger", "storm": "spellslinger",
    "cantrips": "spellslinger", "spell copy": "spellslinger",
    "x spells": "big_mana", "big mana": "big_mana",
    "blink": "blink", "etb": "blink", "flicker": "blink",
    "landfall": "landfall", "lands matter": "landfall", "lands": "landfall",
    "superfriends": "superfriends", "planeswalkers": "superfriends",
    "pillow fort": "pillowfort", "pillowfort": "pillowfort",
}


def archetype_from_themes(themes: list[str]) -> str | None:
    """
    Dado el listado de themes EDHREC de un comandante (ordenados por
    popularidad), devuelve el primer arquetipo propio que matchea.
    """
    for t in themes or []:
        key = THEME_TO_ARCHETYPE.get((t or "").strip().lower())
        if key:
            return key
    return None


def detect_archetype(commander: dict) -> str | None:
    """
    Dado un comandante, sugiere el mejor arquetipo.

    Prioridad (de más a menos específico):
    v1/v2: spellslinger, blink, landfall, reanimator, aristocrats,
           lifegain, tribal, equipment, counters
    v3:    mill, group_hug, stax, superfriends, enchantress,
           artifacts, tokens, big_mana, pillowfort, voltron
    """
    text = (commander.get("oracle_text") or "").lower()
    type_line = (commander.get("type_line") or "").lower()
    candidates = []
    for key, arch in ARCHETYPES.items():
        if arch.commander_predicate(commander):
            candidates.append(key)

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Desempate por señales fuertes (orden de prioridad)
    priority_checks = [
        # ── v3 muy específicos ──────────────────────────────────────────────
        ("mill", lambda: any(s in text for s in (
            "target player mills", "target opponent mills",
            "each opponent mills", "each player mills",
        ))),
        ("group_hug", lambda: any(s in text for s in (
            "each player draws", "each player may draw",
            "each player may play an additional",
        ))),
        ("stax", lambda: any(s in text for s in (
            "spells cost {1} more", "spells cost {2} more",
            "players can't cast more than one spell",
            "whenever an opponent casts a spell, that player pays",
        ))),
        ("superfriends", lambda: "planeswalker" in type_line or any(s in text for s in (
            "whenever you cast a planeswalker",
            "each planeswalker you control",
        ))),
        ("enchantress", lambda: any(s in text for s in (
            "whenever you cast an enchantment",
            "whenever an enchantment enters the battlefield",
            "enchantress",
        ))),
        ("artifacts", lambda: any(s in text for s in (
            "whenever you cast an artifact",
            "whenever an artifact enters the battlefield",
            "affinity for artifacts", "metalcraft",
        ))),
        ("big_mana", lambda: any(s in text for s in (
            "untap all lands you control",
            "double the amount of mana", "doubles the amount of mana",
        ))),
        ("pillowfort", lambda: any(s in text for s in (
            "creatures can't attack you unless",
            "whenever a creature attacks you",
        ))),
        ("voltron", lambda: any(s in text for s in (
            "aura you control", "auras attached to",
            "whenever an aura becomes attached",
        ))),
        ("tokens", lambda: any(s in text for s in (
            "create a 1/1", "create two 1/1",
            "whenever you attack, create", "populate",
        ))),
        # ── v1/v2 ───────────────────────────────────────────────────────────
        ("spellslinger", lambda: any(s in text for s in (
            "whenever you cast an instant", "whenever you cast a sorcery",
            "whenever you cast a noncreature", "magecraft",
            "copy that spell", "whenever you copy", "demonstrate",
        ))),
        ("blink", lambda: any(s in text for s in (
            "exile target creature you control, then return",
            "exile target permanent you control, then return",
            "whenever another creature enters the battlefield under your control",
        ))),
        ("landfall", lambda: "landfall" in text or "whenever a land enters the battlefield" in text),
        ("reanimator", lambda: "from your graveyard to the battlefield" in text),
        ("aristocrats", lambda: (
            ("sacrifice a creature" in text or "whenever a creature dies" in text)
            and ("create a 1/1" in text or "creature token" in text or "dies" in text)
        )),
        ("lifegain", lambda: (
            "whenever you gain life" in text
            and any(s in text for s in ("you gain", "life equal", "life total"))
        )),
        ("tribal", lambda: any(s in text for s in (
            "choose a creature type", "creatures you control of the chosen type",
            "other creatures you control get",
        ))),
        ("equipment", lambda: "equipment" in text),
        ("counters", lambda: "+1/+1 counter" in text or "proliferate" in text),
    ]

    for key, check in priority_checks:
        if key in candidates and check():
            return key

    # Fallback: primer candidato por orden de prioridad
    priority_order = [
        "mill", "group_hug", "stax", "superfriends", "enchantress",
        "artifacts", "big_mana", "pillowfort", "voltron", "tokens",
        "spellslinger", "blink", "landfall", "reanimator",
        "aristocrats", "lifegain", "tribal", "equipment", "counters",
    ]
    for p in priority_order:
        if p in candidates:
            return p

    return candidates[0]
