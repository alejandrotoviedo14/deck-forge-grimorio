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
    "voltron":                 ["equipment", "payoff_voltron"],

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
    "mill":                    ["payoff_reanimator", "payoff_mill"],

    # --- Tokens (go-wide, sin sacrifice engine) ---
    "go-wide":                 ["payoff_tokens"],
    "populate":                ["payoff_tokens"],
    "token-matters":           ["payoff_tokens"],
    "anthem":                  ["payoff_tokens"],

    # --- Enchantress ---
    "enchantress":             ["payoff_enchantress"],
    "enchantment-matters":     ["payoff_enchantress"],
    "aura-matters":            ["payoff_enchantress", "payoff_voltron"],

    # --- Artifacts ---
    "artifact-matters":        ["payoff_artifacts"],
    "affinity":                ["payoff_artifacts"],
    "metalcraft":              ["payoff_artifacts"],
    "improvise":               ["payoff_artifacts"],
    "historic-matters":        ["payoff_artifacts"],

    # --- Voltron (aura / combat) ---
    "aura":                    ["payoff_voltron"],
    "aura-synergy":            ["payoff_voltron"],

    # --- Wheels ---
    "wheel":                   ["payoff_wheels"],
    "wheel-effect":            ["payoff_wheels"],
    "discard-matters":         ["payoff_wheels"],

    # --- Group Hug ---
    "group-hug":               ["payoff_group_hug"],
    "shared-resources":        ["payoff_group_hug"],

    # --- Stax ---
    "stax":                    ["payoff_stax"],
    "tax":                     ["payoff_stax"],
    "hatebear":                ["payoff_stax"],
    "prison":                  ["payoff_stax"],
    "asymmetric-effect":       ["payoff_stax"],

    # --- Mill (oponente) ---
    "opponent-mill":           ["payoff_mill"],
    "mill-matters":            ["payoff_mill"],

    # --- Superfriends ---
    "superfriends":            ["payoff_superfriends"],
    "planeswalker-matters":    ["payoff_superfriends"],
    "loyalty-matters":         ["payoff_superfriends"],

    # --- Big Mana ---
    "big-mana":                ["payoff_big_mana"],
    "x-spell":                 ["payoff_big_mana"],
    "mana-doubling":           ["payoff_big_mana", "ramp"],

    # --- Pillowfort ---
    "pillow-fort":             ["payoff_pillowfort"],
    "pillowfort":              ["payoff_pillowfort"],
    "fort":                    ["payoff_pillowfort"],
    "moat-effect":             ["payoff_pillowfort"],
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
    Fallback: "when ~ enters", "whenever ~ enters", "exile ~ then return"
    """
    if "payoff_blink" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    name = (card.get("name") or "").lower()
    signals = (
        "when ~ enters",
        "when this creature enters",
        "whenever a creature enters under your control",
        "creature you control enters",
        "exile target creature, then return",
        "exile ~ return it",
        "blinks",
    )
    # Heurística "when NOMBRE enters" — no tenemos el nombre interpolado, pero
    # podemos detectar "when this creature enters" o "when it enters"
    etb_patterns = (
        "when this creature enters",
        "when it enters",
        "whenever a creature enters", "creature you control enters",
        "exile target creature you control, then return",
        "exile ~ and return",
        "exile target permanent, then return",
    )
    return any(s in text for s in etb_patterns)


def is_landfall_payoff(card: dict) -> bool:
    """
    Payoffs de landfall: triggers cuando una tierra entra, o permite drops extra.
    Tags primarios: landfall, land-matters, extra-land.
    Fallback: "whenever a land enters", "land you control enters", "play an additional land"
    """
    if "payoff_landfall" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "whenever a land enters", "land you control enters",
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
# Payoffs NUEVOS v3 (10 arquetipos extra basados en EDHREC/Scryfall)
# ---------------------------------------------------------------------------

def is_enchantment_payoff(card: dict) -> bool:
    """Enchantress: beneficia de lanzar/tener encantamientos. También los propios encantamientos baratos son core."""
    if "payoff_enchantress" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    type_line = (card.get("type_line") or "").lower()
    signals = (
        "whenever you cast an enchantment",
        "whenever an enchantment enters under your control",
        "enchantment you control enters",
        "whenever an enchantment enters", "enchantment you control enters",
        "enchantress",
        "for each enchantment you control",
        "enchantments you control get",
        "enchantments you control have",
        "enchantment spells you cast",
        "whenever you attach an aura",
    )
    if any(s in text for s in signals):
        return True
    # Encantamientos propios (no Auras, no tierras) de CMC bajo son el núcleo del arquetipo
    if "enchantment" in type_line and "aura" not in type_line and not has_type(card, "Land") and cmc(card) <= 5:
        return True
    return False


def is_aura(card: dict) -> bool:
    """Es un Aura — pieza ofensiva del voltron mágico."""
    if "payoff_voltron" in _roles_from_tags(card):
        return True
    return "aura" in (card.get("type_line") or "").lower()


def is_artifact_payoff(card: dict) -> bool:
    """Artefacto relevante o payoff de artefactos."""
    if "payoff_artifacts" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    type_line = (card.get("type_line") or "").lower()
    signals = (
        "whenever you cast an artifact",
        "whenever an artifact enters", "artifact you control enters",
        "whenever an artifact enters", "artifact you control enters",
        "for each artifact you control",
        "artifact creatures you control",
        "affinity for artifacts",
        "metalcraft",
        "improvise",
    )
    if any(s in text for s in signals):
        return True
    # Artefactos no-tierra de CMC bajo son el core del arquetipo
    if "artifact" in type_line and not has_type(card, "Land") and cmc(card) <= 5:
        return True
    return False


def is_wheel_piece(card: dict) -> bool:
    """Wheel effects: descarta la mano y roba; payoffs por descartar."""
    if "payoff_wheels" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "each player discards their hand",
        "each player discards all the cards",
        "discard your hand, then draw",
        "each player draws",
        "each player discards",
        "whenever you discard",
        "whenever a player discards",
        "each opponent discards",
        "draw cards equal to the number of cards discarded",
    )
    return any(s in text for s in signals)


def is_group_hug_piece(card: dict) -> bool:
    """Group hug: beneficia a todos los jugadores simultáneamente."""
    if "payoff_group_hug" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "each player draws",
        "each player may draw",
        "each opponent draws",
        "each player gains",
        "each player may put",
        "each player may play an additional",
        "each player may search their library",
        "each player gets",
        "each player may cast",
    )
    return any(s in text for s in signals)


def is_stax_piece(card: dict) -> bool:
    """Stax / Prison: niega recursos o bloquea acciones del oponente."""
    if "payoff_stax" in _roles_from_tags(card):
        return True
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
        "can't untap more than",
        "permanents don't untap",
        "unless they pay",
        "must pay {",
        "can't be cast",
        "whenever an opponent casts a spell, that player pays",
    )
    return any(s in text for s in signals)


def is_mill_piece(card: dict) -> bool:
    """Mill de oponentes: manda cartas de biblioteca al cementerio del rival."""
    if "payoff_mill" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "target player mills",
        "each player mills",
        "target opponent mills",
        "each opponent mills",
        "put the top",
        "puts the top",
        "whenever a card is put into an opponent",
        "whenever a card is put into a player",
        "opponent puts the top",
        "each player puts the top",
        "mill x",
        "mills for each",
    )
    return any(s in text for s in signals)


def is_planeswalker(card: dict) -> bool:
    """Es un permanente Planeswalker."""
    return has_type(card, "Planeswalker")


def is_superfriends_payoff(card: dict) -> bool:
    """Superfriends: genera valor con planeswalkers o los protege."""
    if "payoff_superfriends" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "whenever you cast a planeswalker",
        "planeswalker you control",
        "each planeswalker you control",
        "planeswalkers you control have",
        "loyalty counter",
        "loyalty counters",
        "additional loyalty counter",
        "planeswalk",
        "proliferate",  # sinergia con counters de lealtad
    )
    if any(s in text for s in signals):
        return True
    return is_planeswalker(card)


def is_big_mana_piece(card: dict) -> bool:
    """Big mana: dobla maná, X-spells o payoffs de maná masivo."""
    if "payoff_big_mana" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    mana_signals = (
        "doubles the amount of mana",
        "double the amount of mana",
        "untap all lands you control",
        "for each mana spent to cast this spell",
        "equal to the amount of mana",
    )
    if any(s in text for s in mana_signals):
        return True
    # X-spells con payoff grande
    if "{x}" in text and cmc(card) >= 3 and any(
        kw in text for kw in ("damage", "draw", "create", "put", "destroy")
    ):
        return True
    return False


def is_pillowfort_piece(card: dict) -> bool:
    """Pillowfort: defiende al controlador de ataques directos."""
    if "payoff_pillowfort" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "creatures can't attack you",
        "creatures can't attack you unless",
        "whenever a creature attacks you",
        "whenever a creature attacks you or a planeswalker",
        "you have hexproof",
        "you and permanents you control have hexproof",
        "damage that would be dealt to you",
        "prevent all combat damage that would be dealt to you",
        "if you would be dealt damage",
    )
    return any(s in text for s in signals)


def is_token_payoff(card: dict) -> bool:
    """Payoffs del arquetipo tokens: anthems, multiplicadores, synergy con muchas criaturas."""
    if "payoff_tokens" in _roles_from_tags(card):
        return True
    text = (card.get("oracle_text") or "").lower()
    signals = (
        "creatures you control get +",
        "creature tokens you control",
        "tokens you control",
        "whenever a token enters under your control",
        "token you control enters",
        "for each creature you control",
        "populate",
        "number of creatures you control",
    )
    return any(s in text for s in signals)


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

    # Payoffs nuevos v3 (10 arquetipos EDHREC)
    if is_token_payoff(card):           roles.add("payoff_tokens")
    if is_enchantment_payoff(card):     roles.add("payoff_enchantress")
    if is_aura(card):                   roles.add("payoff_voltron")
    if is_artifact_payoff(card):        roles.add("payoff_artifacts")
    if is_wheel_piece(card):            roles.add("payoff_wheels")
    if is_group_hug_piece(card):        roles.add("payoff_group_hug")
    if is_stax_piece(card):             roles.add("payoff_stax")
    if is_mill_piece(card):             roles.add("payoff_mill")
    if is_superfriends_payoff(card):    roles.add("payoff_superfriends")
    if is_big_mana_piece(card):         roles.add("payoff_big_mana")
    if is_pillowfort_piece(card):       roles.add("payoff_pillowfort")

    return roles
