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
        # Criaturas con sinergia real: utilidad + bajo coste
        Slot("Soporte & Cuerpos", 7,
             lambda c: c.get("is_creature") and cmc(c) <= 3 and (
                 cls.is_draw(c) or cls.is_ramp(c) or cls.is_removal(c) or
                 has_text(c, "equipment", "equipped", "artifact", "warrior", "soldier",
                          "attack", "combat", "whenever", "enters")
             ),
             score_rank, "Beater", "Cuerpo con sinergia para equipar."),
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
        "Mazo cargado de instants y sorceries. Payoffs por cada hechizo. "
        "Wincons: storm-lite, burn incremental, comandante voltron con counters."
    ),
    commander_predicate=is_spellslinger_commander,
    auto_includes=[
        "Counterspell", "Snapcaster Mage", "Mind's Desire",
        "Past in Flames", "Niv-Mizzet, Parun", "Talrand, Sky Summoner",
        "Young Pyromancer", "Guttersnipe",
    ],
    slots=[
        Slot("Spellslinger Payoffs", 12, cls.is_spellslinger_payoff, score_rank,
             "Payoff", "Premia cada hechizo casteado."),
        Slot("Counterspells", 8, cls.is_counterspell, score_low_cmc_then_rank,
             "Counter", "Reactivo."),
        Slot("Burn / Removal Spells", 8,
             lambda c: cls.is_removal(c) and cls.is_instant_or_sorcery(c),
             score_low_cmc_then_rank, "Burn/Removal", "Daño puntual."),
        Slot("Card Draw / Cantrips", 12, cls.is_draw, score_low_cmc_then_rank,
             "Cantrip", "Mantiene el motor."),
        Slot("Ramp (artifact only)", 6,
             lambda c: cls.is_ramp(c) and has_type(c, "Artifact"),
             score_low_cmc_then_rank, "Ramp", "Mana fix sin verde."),
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
# Registry
# ===========================================================================

ARCHETYPES: dict[str, Archetype] = {
    # Originales
    "counters":     COUNTERS,
    "equipment":    EQUIPMENT,
    "aristocrats":  ARISTOCRATS,
    "spellslinger": SPELLSLINGER,
    # Nuevos sesión 4
    "tribal":       TRIBAL,
    "blink":        BLINK,
    "landfall":     LANDFALL,
    "lifegain":     LIFEGAIN,
    "reanimator":   REANIMATOR,
}


def detect_archetype(commander: dict) -> str | None:
    """
    Dado un comandante, sugiere el mejor arquetipo.

    Prioridad de desempate (de más a menos específico):
    1. Spellslinger — señales muy específicas (magecraft, "whenever you cast")
    2. Blink — "exile target ... then return" es inconfundible
    3. Landfall — "landfall" en oracle_text es tag único
    4. Reanimator — "from your graveyard to the battlefield" muy específico
    5. Aristocrats — sacrifice + death triggers
    6. Lifegain — "whenever you gain life" + payoff
    7. Tribal — "creatures you control get +" puede solapar con otros
    8. Equipment — "equipment" en texto
    9. Counters — +1/+1 counters, puede ser lo más genérico
    """
    text = (commander.get("oracle_text") or "").lower()
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
        "spellslinger", "blink", "landfall", "reanimator",
        "aristocrats", "lifegain", "tribal", "equipment", "counters",
    ]
    for p in priority_order:
        if p in candidates:
            return p

    return candidates[0]
