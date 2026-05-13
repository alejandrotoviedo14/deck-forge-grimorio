"""
classifier.py — v2 con Scryfall Tagger como fuente primaria.

Arquitectura de clasificación en dos capas:

  CAPA 1 — Tagger tags (si `tagger_tags` está en la carta):
    Mapeamos tags como "ramp", "card-draw", "removal"... a roles internos.
    Es más preciso porque Tagger tiene curación humana.

  CAPA 2 — Heurísticas de oracle_text (fallback):
    Si la carta no tiene tagger_tags (JSON viejo o Tagger no disponible),
    usamos las mismas heurísticas que en v1.

Roles internos (sin cambios desde v1 para no romper archetypes/builder):
    ramp, draw, removal, sweeper, counter, recursion, tutor, protection,
    threat, equipment, sac_outlet, instant_or_sorcery,
    payoff_counters, payoff_tokens, payoff_death, payoff_drain,
    payoff_spellslinger,
    -- NUEVO v2 --
    payoff_tribal, payoff_blink, payoff_landfall, payoff_lifegain,
    payoff_reanimator, land (siempre para tierras)

MAPEO DE TAGS DE TAGGER → ROLES:
    Ver TAG_TO_ROLES más abajo. Un tag puede mapear a múltiples roles.
    Si un tag no está en el mapa, se ignora (no rompe, solo no aporta).
"""

from .pool import has_text, has_type, cmc


# ---------------------------------------------------------------------------
# Mapeo Tagger tags → roles internos
# ---------------------------------------------------------------------------
# Los tags vienen en formato kebab-case: "card-draw", "land-ramp", etc.
# Fuente: https://tagger.scryfall.com (tags funcionales más comunes)

TAG_TO_ROLES: dict[str, list[str]] = {
    # --- Ramp ---
    "ramp":                    ["ramp"],
    "land-ramp":               ["ramp"],
    "mana-rock":               ["ramp"],
    "mana-dork":               ["ramp"],
    "cost-reduction":          ["ramp"],
    "treasure-maker":          ["ramp"],
    "ritual":                  ["ramp"],

    # --- Draw ---
    "card-draw":               ["draw"],
    "draw":                    ["draw"],
    "cantrip":                 ["draw"],
    "looting":                 ["draw"],
    "impulse-draw":            ["draw"],
    "investigate":             ["draw"],
    "cycling":                 ["draw"],

    # --- Removal ---
    "removal":                 ["removal"],
    "single-target-removal":   ["removal"],
    "exile":                   ["removal"],
    "bounce":                  ["removal"],
    "spot-removal":            ["removal"],
    "tuck":                    ["removal"],
    "burn":                    ["removal"],

    # --- Sweeper ---
    "board-wipe":              ["sweeper"],
    "mass-removal":            ["sweeper"],
    "sweeper":                 ["sweeper"],

    # --- Counter ---
    "counter-spell":           ["counter"],
    "counterspell":            ["counter"],
    "counter":                 ["counter"],

    # --- Recursion ---
    "reanimation":             ["recursion", "payoff_reanimator"],
    "recursion":               ["recursion"],
    "graveyard-recursion":     ["recursion"],
    "unearth":                 ["recursion"],

    # --- Tutor ---
    "tutor":                   ["tutor"],
    "search":                  ["tutor"],

    # --- Protection ---
    "protection":              ["protection"],
    "hexproof":                ["protection"],
    "indestructible":          ["protection"],
    "shroud":                  ["protection"],
    "ward":                    ["protection"],

    # --- Threat ---
    "finisher":                ["threat"],
    "wincon":                  ["threat"],
    "alpha-strike":            ["threat"],

    # --- Counters archetype ---
    "counter-manipulation":    ["payoff_counters"],
    "proliferate":             ["payoff_counters"],
    "plus-one-counters":       ["payoff_counters"],
    "+1/+1-counters":          ["payoff_counters"],
    "counter-doubling":        ["payoff_counters"],

    # --- Equipment archetype ---
    "equipment":               ["equipment"],
    "equipment-matters":       ["equipment", "payoff_equipment"],
    "voltron":                 ["equipment"],

    # --- Aristocrats archetype ---
    "token-generator":         ["payoff_tokens"],
    "token-generation":        ["payoff_tokens"],
    "go-wide":                 ["payoff_tokens"],
    "sacrifice":               ["sac_outlet"],
    "sacrifice-outlet":        ["sac_outlet"],
    "death-trigger":           ["payoff_death"],
    "dies-trigger":            ["payoff_death"],
    "drain":                   ["payoff_drain"],
    "life-drain":              ["payoff_drain"],

    # --- Spellslinger archetype ---
    "spell-matters":           ["payoff_spellslinger"],
    "magecraft":               ["payoff_spellslinger"],
    "prowess":                 ["payoff_spellslinger"],
    "instant-sorcery-matters": ["payoff_spellslinger"],
    "storm":                   ["payoff_spellslinger"],
    "copy-spell":              ["payoff_spellslinger"],

    # --- Tribal (NUEVO) ---
    "tribal":                  ["payoff_tribal"],
    "lord":                    ["payoff_tribal"],
    "creature-type-matters":   ["payoff_tribal"],
    "kindred":                 ["payoff_tribal"],

    # --- Blink (NUEVO) ---
    "blink":                   ["payoff_blink"],
    "flicker":                 ["payoff_blink"],
    "etb-matters":             ["payoff_blink"],
    "etb":                     ["payoff_blink"],
    "enters-battlefield":      ["payoff_blink"],
    "blink-target":            ["payoff_blink"],

    # --- Landfall (NUEVO) ---
    "landfall":                ["payoff_landfall"],
    "land-matters":            ["payoff_landfall"],
    "land-drop":               ["payoff_landfall"],
    "extra-land":              ["payoff_landfall"],

    # --- Lifegain (NUEVO) ---
    "lifegain":                ["payoff_lifegain"],
    "life-gain":               ["payoff_lifegain"],
    "life-matters":            ["payoff_lifegain"],
    "life-payment":            ["payoff_lifegain"],

    # --- Reanimator (NUEVO) ---
    "reanimator":              ["payoff_reanimator", "recursion"],
    "cheat-into-play":         ["payoff_reanimator"],
    "graveyard-matters":       ["payoff_reanimator"],
    "self-mill":               ["payoff_reanimator"],
    "mill":                    ["payoff_reanimator"],
}


def _roles_from_tags(card: dict) -> set[str]:
    """
    CAPA 1: extrae roles a partir de tagger_tags.
    Devuelve set vacío si no hay tags.
    """
    tags = card.get("tagger_tags") or []
    if not tags:
        return set()

    roles: set[str] = set()
    for tag in tags:
        tag_lower = tag.strip().lower()
        for role in TAG_TO_ROLES.get(tag_lower, []):
            roles.add(role)
    return roles


# ---------------------------------------------------------------------------
# Heurísticas (CAPA 2 — fallback si no hay tags)
# ---------------------------------------------------------------------------

def is_ramp(card: dict) -> bool:
    # Capa 1 check rápido
    if "ramp" in _roles_from_tags(card):
        return True
    # Fallback heurístico
    if has_type(card, "Land"):
        return False
    text = (card.get("oracle_text") or "").lower()
    cm = cmc(card)
    type_line = (card.get("type_line") or "").lower()

    if "artifact" in type_line and cm <= 3:
        if "{t}: add" in text or "add {" in text or "add one mana" in text:
            return True
    if "creature" in type_line and cm <= 2:
        if "{t}: add" in text or "add {" in text:
            return True
    if cm <= 4:
        if "search your library for" in text and ("basic land" in text or "land card" in text):
            return True
        if "put a land card" in text and "battlefield" in text:
            return True
    if cm <= 3 and "create a treasure" in text:
        return True
    if "spells you cast cost" in text and "less to cast" in text:
        return True
    return False


def is_draw(card: dict) -> bool:
    if "draw" in _roles_from_tags(card):
        return True
    if has_type(card, "Land"):
        return False
    text = (card.get("oracle_text") or "").lower()
    cm = cmc(card)
    if cm > 7:
        return False
    draw_signals = (
        "draw a card", "draw two cards", "draw three cards", "draw four cards",
        "draw cards equal", "draw x cards",
    )
    if any(s in text for s in draw_signals):
        return True
    if cm <= 2 and ("scry 2" in text or "scry 3" in text):
        return True
    if "investigate" in text:
        return True
    return False


def is_removal(card: dict) -> bool:
    if "removal" in _roles_from_tags(card):
        return True
    if has_type(card, "Land"):
        return False
    text = (card.get("oracle_text") or "").lower()
    cm = cmc(card)
    if cm > 7:
        return False
    if "destroy target" in text:
        return True
    if "exile target" in text and ("creature" in text or "permanent" in text or "nonland" in text):
        return True
    if "return target" in text and "to its owner's hand" in text:
        return True
    if "deals 4 damage" in text or "deals 5 damage" in text:
        return True
    return False


def is_sweeper(card: dict) -> bool:
    if "sweeper" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    sweepers = (
        "destroy all creatures", "destroy each creature", "exile all creatures",
        "destroy all nonland", "exile all nonland",
        "deals x damage to each creature", "deals 5 damage to each creature",
    )
    return any(s in text for s in sweepers)


def is_counterspell(card: dict) -> bool:
    if "counter" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    return "counter target spell" in text or "counter target noncreature spell" in text


def is_recursion(card: dict) -> bool:
    if "recursion" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    if has_type(card, "Land"):
        return False
    signals = (
        "return target creature card from your graveyard",
        "return target card from your graveyard",
        "return that card to your hand",
        "from your graveyard to the battlefield",
    )
    return any(s in text for s in signals)


def is_tutor(card: dict) -> bool:
    if "tutor" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    if has_type(card, "Land"):
        return False
    if "search your library for" not in text:
        return False
    if "basic land" in text or "land card" in text:
        return False
    targets = ("creature card", "instant card", "sorcery card", "artifact card",
               "enchantment card", "card with", "a card", "any card")
    return any(t in text for t in targets)


def is_protection(card: dict) -> bool:
    if "protection" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "indestructible", "hexproof", "phasing", "protection from",
        "can't be countered", "can't be the target",
        "regenerate", "shroud",
    )
    return any(s in text for s in signals) and cmc(card) <= 4


def is_threat(card: dict) -> bool:
    if "threat" in _roles_from_tags(card):
        return True
    if not card.get("is_creature"):
        return False
    cm = cmc(card)
    pwr = card.get("power")
    try:
        pwr_n = int(pwr) if pwr else 0
    except (ValueError, TypeError):
        pwr_n = 0
    return cm >= 5 or pwr_n >= 5


# ---------------------------------------------------------------------------
# Payoffs específicos de arquetipo
# ---------------------------------------------------------------------------

def is_counter_payoff(card: dict) -> bool:
    if "payoff_counters" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "+1/+1 counter", "proliferate", "double the number",
        "for each +1/+1 counter", "another +1/+1",
    )
    return any(s in text for s in signals)


def is_equipment(card: dict) -> bool:
    # Tagger tiene "equipment" tag que mapea a rol equipment
    if "equipment" in _roles_from_tags(card):
        return True
    return has_type(card, "Equipment")


def is_token_maker(card: dict) -> bool:
    if "payoff_tokens" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    if not any(s in text for s in (
        "create a", "create two", "create three", "create four", "create x"
    )):
        return False
    return "creature token" in text or "token creature" in text


def is_sac_outlet(card: dict) -> bool:
    if "sac_outlet" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    if has_type(card, "Land"):
        return False
    return "sacrifice a creature" in text or "sacrifice another creature" in text


def is_death_trigger(card: dict) -> bool:
    if "payoff_death" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "whenever a creature you control dies",
        "whenever another creature dies",
        "when this creature dies",
        "whenever a creature dies",
    )
    return any(s in text for s in signals)


def is_drain(card: dict) -> bool:
    if "payoff_drain" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    return "each opponent loses" in text and "life" in text


def is_spellslinger_payoff(card: dict) -> bool:
    if "payoff_spellslinger" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "whenever you cast", "magecraft", "prowess",
        "copy target instant", "copy target sorcery",
        "noncreature spell",
    )
    return any(s in text for s in signals)


def is_instant_or_sorcery(card: dict) -> bool:
    return has_type(card, "Instant") or has_type(card, "Sorcery")


# ---------------------------------------------------------------------------
# Payoffs NUEVOS (sesión 4)
# ---------------------------------------------------------------------------

def is_tribal_payoff(card: dict) -> bool:
    """
    Premia un tipo de criatura específico: lords, anthem tribal, sinergia kindred.
    Tags primarios: tribal, lord, creature-type-matters, kindred.
    Fallback: "as long as you control", "each [Type] you control", "other [Type]s you control"
    """
    if "payoff_tribal" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    keywords = [k.lower() for k in (card.get("keywords") or [])]
    # Palabra clave Kindred (antes "tribal") en keywords Scryfall
    if "kindred" in keywords:
        return True
    signals = (
        "other creatures you control get",
        "creatures you control get +",
        "each creature you control of the chosen type",
        "as long as you control a",
        "of that type", "that share a creature type",
        "lords get",
    )
    return any(s in text for s in signals)


def is_blink_payoff(card: dict) -> bool:
    """
    Payoffs de ETB / blink: cartas que se benefician de entrar al campo,
    o que hace blink (exile + return).
    Tags primarios: blink, flicker, etb-matters, etb.
    Fallback: "when ~ enters", "whenever ~ enters the battlefield", "exile ~ then return"
    """
    if "payoff_blink" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    name = (card.get("name") or "").lower()
    signals = (
        "when ~ enters",
        "when this creature enters",
        "whenever a creature enters the battlefield under your control",
        "exile target creature, then return",
        "exile ~ return it",
        "blinks",
    )
    # Heurística "when NOMBRE enters" — no tenemos el nombre interpolado, pero
    # podemos detectar "when this creature enters" o "when it enters"
    etb_patterns = (
        "when this creature enters",
        "when it enters the battlefield",
        "whenever a creature enters",
        "exile target creature you control, then return",
        "exile ~ and return",
        "exile target permanent, then return",
    )
    return any(s in text for s in etb_patterns)


def is_landfall_payoff(card: dict) -> bool:
    """
    Payoffs de landfall: triggers cuando una tierra entra, o permite drops extra.
    Tags primarios: landfall, land-matters, extra-land.
    Fallback: "whenever a land enters", "play an additional land"
    """
    if "payoff_landfall" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "whenever a land enters the battlefield",
        "whenever a land you control enters",
        "landfall",
        "play an additional land",
        "play two additional lands",
        "you may play an additional land",
    )
    return any(s in text for s in signals)


def is_lifegain_payoff(card: dict) -> bool:
    """
    Payoffs de lifegain: se benefician de ganar vida o de tener mucha vida.
    Tags primarios: lifegain, life-gain, life-matters.
    Fallback: "whenever you gain life", "your life total"
    """
    if "payoff_lifegain" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "whenever you gain life",
        "whenever a player gains life",
        "for each life you gained",
        "you have more life",
        "your life total is",
        "equal to your life",
        "if your life total",
    )
    return any(s in text for s in signals)


def is_reanimator_payoff(card: dict) -> bool:
    """
    Piezas de estrategia reanimator: targets grandes para reanimar o
    enablers de graveyard (discard, mill, reanimation spells).
    Tags primarios: reanimator, graveyard-matters, self-mill, cheat-into-play.
    Fallback: "return ~ from your graveyard to battlefield", "discard a card",
              "put cards from library into graveyard"
    """
    if "payoff_reanimator" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    # Targets (criaturas grandes para reanimar)
    if card.get("is_creature"):
        cm = cmc(card)
        if cm >= 6:
            return True  # Cualquier criatura 6+ es candidata a reanimar
    # Enablers
    enabler_signals = (
        "from your graveyard to the battlefield",
        "put the top",
        "put cards from the top of your library",
        "mill",
        "discard a card, then draw",
        "discard any number",
        "exile ~ from your graveyard",
    )
    return any(s in text for s in enabler_signals)


# ---------------------------------------------------------------------------
# Master classifier
# ---------------------------------------------------------------------------

def classify(card: dict) -> set[str]:
    """
    Devuelve el conjunto de roles que cumple una carta.

    Con Tagger tags disponibles, usa capa 1 (más precisa).
    Sin tags, usa capa 2 (heurísticas de oracle_text).
    """
    roles: set[str] = set()

    if card.get("is_land"):
        roles.add("land")
        return roles

    # Capa 1: roles directos de Tagger (si hay tags)
    tag_roles = _roles_from_tags(card)
    roles.update(tag_roles)

    # Capa 2: heurísticas (siempre se ejecutan para completar;
    # las funciones individuales ya evitan duplicar con tag_roles)
    if is_ramp(card):        roles.add("ramp")
    if is_draw(card):        roles.add("draw")
    if is_removal(card):     roles.add("removal")
    if is_sweeper(card):     roles.add("sweeper")
    if is_counterspell(card): roles.add("counter")
    if is_recursion(card):   roles.add("recursion")
    if is_tutor(card):       roles.add("tutor")
    if is_protection(card):  roles.add("protection")
    if is_threat(card):      roles.add("threat")

    # Payoffs de arquetipo
    if is_counter_payoff(card):    roles.add("payoff_counters")
    if is_equipment(card):         roles.add("equipment")
    if is_token_maker(card):       roles.add("payoff_tokens")
    if is_sac_outlet(card):        roles.add("sac_outlet")
    if is_death_trigger(card):     roles.add("payoff_death")
    if is_drain(card):             roles.add("payoff_drain")
    if is_spellslinger_payoff(card): roles.add("payoff_spellslinger")
    if is_instant_or_sorcery(card):  roles.add("instant_or_sorcery")

    # Payoffs nuevos sesión 4
    if is_tribal_payoff(card):      roles.add("payoff_tribal")
    if is_blink_payoff(card):       roles.add("payoff_blink")
    if is_landfall_payoff(card):    roles.add("payoff_landfall")
    if is_lifegain_payoff(card):    roles.add("payoff_lifegain")
    if is_reanimator_payoff(card):  roles.add("payoff_reanimator")

    return roles
