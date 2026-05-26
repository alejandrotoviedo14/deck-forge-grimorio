"""
builder.py — Construye un mazo de 100 cartas.

VERSIÓN 3 — Mejoras sobre v2:
  A) Score compuesto en lugar de solo EDHREC rank:
     - 40% sinergia con arquetipo (densidad de oracle text relevante)
     - 25% manabase friendliness (pips de color)
     - 20% curva (penaliza añadir más a CMC saturado)
     - 15% EDHREC rank (desempate)
  B) Multi-rol cards: una carta puede contribuir a varios slots si encaja
     en más de uno. Se evita el sobrellenado de cubetas y se valoran cartas
     versátiles (ej: Surtr = wincon + aristocrats payoff simultáneamente).

Algoritmo:
1. Comandante (provisto o detectado).
2. Filtra pool por color identity.
3. Auto-includes del arquetipo.
4. Pre-clasifica TODAS las cartas en pool (todos sus roles).
5. Slots del arquetipo:
   - Para cada slot, encuentra candidatos con multi-rol score
   - Selecciona top N con score compuesto
6. Tierras de utilidad + básicas para llegar a 100.
"""

from dataclasses import dataclass, field

from . import classifier as cls
from .pool import (
    fits_color_identity, has_text, has_type, cmc, edhrec_rank,
    is_basic_land, is_legal_in_commander,
)
from .archetypes import Archetype, ARCHETYPES, detect_archetype


# ---------------------------------------------------------------------------
# Constantes de scoring
# ---------------------------------------------------------------------------

# Pesos del score compuesto
W_SYNERGY = 0.40
W_MANA    = 0.25
W_CURVE   = 0.20
W_RANK    = 0.15

# Penalización por CMC saturado en la curva
CURVE_SATURATION_THRESHOLD = 5  # si ya hay >5 cartas a este CMC, penaliza
CURVE_HARD_CAP_BONUS = 1.5      # premia rellenar huecos

# Bonus multi-rol: si una carta cumple varios roles útiles para el plan
MULTIROLE_BONUS_PER_ROLE = 0.15  # +15% por cada rol extra relevante


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DeckCard:
    """Una carta en el mazo, con metadata de por qué está."""
    card: dict
    category: str
    role: str
    justification: str

    @property
    def name(self) -> str:
        return self.card["name"]


@dataclass
class BuiltDeck:
    commander: dict
    archetype: Archetype
    colors: str
    cards: list[DeckCard] = field(default_factory=list)
    needed_basics: int = 0

    @property
    def card_count(self) -> int:
        return len(self.cards) + 1

    def categorized(self) -> dict[str, list[DeckCard]]:
        out: dict[str, list[DeckCard]] = {}
        for c in self.cards:
            out.setdefault(c.category, []).append(c)
        return out

    def all_cards_with_basics(self, basics: dict[str, dict] | None = None) -> list[dict]:
        out = [self.commander] + [c.card for c in self.cards]
        if self.needed_basics > 0:
            colors = list(self.colors)
            split = self.needed_basics // len(colors)
            rem = self.needed_basics - split * len(colors)
            basic_map = {"W": "Plains", "U": "Island", "B": "Swamp",
                         "R": "Mountain", "G": "Forest"}
            for i, c in enumerate(colors):
                n = split + (1 if i < rem else 0)
                bn = basic_map[c]
                stub = {
                    "name": bn, "is_land": True, "cmc": 0,
                    "type_line": f"Basic Land — {bn}", "oracle_text": "",
                    "produced_mana": [c], "color_identity": [],
                }
                for _ in range(n):
                    out.append(stub)
        return out


# ---------------------------------------------------------------------------
# Score components
# ---------------------------------------------------------------------------

def _normalize_rank(rank: int | None) -> float:
    """
    Convierte EDHREC rank en score [0,1]. Rank más bajo = mejor = score más alto.
    Cartas sin rank (raras/nuevas) tienen score medio (no penalizadas).
    """
    if rank is None:
        return 0.5  # neutral, no penaliza cartas raras/nuevas
    if rank <= 100:
        return 1.0
    if rank <= 1000:
        return 0.9
    if rank <= 5000:
        return 0.7
    if rank <= 20000:
        return 0.5
    if rank <= 50000:
        return 0.3
    return 0.1


def _mana_friendliness(card: dict, deck_colors: set[str]) -> float:
    """
    Cuántos pips de cada color requiere la carta y si encajan en los colores del mazo.
    Premia cartas con pocos pips (más jugables) y penaliza si requieren un color saturado.
    Devuelve score [0, 1].
    """
    mana_cost = (card.get("mana_cost") or "").upper()
    if not mana_cost:
        return 0.7  # incoloro o sin info = neutro positivo

    pip_count = 0
    color_pips: dict[str, int] = {}
    for c in "WUBRG":
        n = mana_cost.count(f"{{{c}}}")
        if n:
            color_pips[c] = n
            pip_count += n

    if pip_count == 0:
        return 0.9  # solo genérico = muy jugable

    # Penaliza más de 2 pips del mismo color (difícil de castear)
    max_same_color = max(color_pips.values()) if color_pips else 0
    if max_same_color >= 3:
        return 0.2
    if max_same_color == 2:
        return 0.6
    return 0.85


def _curve_fit(card: dict, current_cmc_distribution: dict[int, int]) -> float:
    """
    Cómo encaja la carta en la curva actual del mazo.
    Premia rellenar huecos (CMC poco representado), penaliza saturar.
    """
    cm = int(cmc(card) or 0)
    if cm == 0:
        return 0.8  # cartas a 0 mana son geniales

    count_at_this_cmc = current_cmc_distribution.get(cm, 0)

    if count_at_this_cmc == 0:
        return 1.0  # hueco completo
    if count_at_this_cmc <= 3:
        return 0.85
    if count_at_this_cmc < CURVE_SATURATION_THRESHOLD:
        return 0.6
    return 0.3  # saturado


def _synergy_score(
    card: dict,
    card_roles: set[str],
    archetype: Archetype,
) -> float:
    """
    Densidad de sinergia con el arquetipo.
    Cuenta cuántos roles relevantes del arquetipo cumple la carta.
    """
    # Roles que SIEMPRE son relevantes (universal cogs)
    universal_roles = {"ramp", "draw", "removal", "tutor", "protection"}

    # Roles específicos del arquetipo (derivados de los slots)
    archetype_roles: set[str] = set()
    for slot in archetype.slots:
        # Inferimos los roles del slot por su nombre/etiqueta
        name_lower = slot.role_label.lower()
        if "ramp" in name_lower: archetype_roles.add("ramp")
        if "draw" in name_lower: archetype_roles.add("draw")
        if "removal" in name_lower or "interaction" in name_lower:
            archetype_roles.update({"removal", "counter", "sweeper"})
        # Payoffs específicos: hacer guess por keyword del slot
        for tag in card_roles:
            if "payoff" in tag and tag.replace("payoff_", "") in name_lower:
                archetype_roles.add(tag)

    # Score: ¿cuántos roles relevantes cumple esta carta?
    relevant_universal = card_roles & universal_roles
    relevant_archetype = card_roles & archetype_roles

    # Cada rol relevante suma; multi-rol cards puntúan alto
    base = len(relevant_universal) * 0.25 + len(relevant_archetype) * 0.35

    # Bonus si cumple un payoff específico (no genérico)
    payoff_hits = sum(1 for r in card_roles if r.startswith("payoff_"))
    base += payoff_hits * 0.20

    # Bonus si es threat
    if "threat" in card_roles:
        base += 0.15

    # Cap en [0, 1]
    return min(1.0, base)


def composite_score(
    card: dict,
    card_roles: set[str],
    archetype: Archetype,
    deck_colors: set[str],
    current_cmc_distribution: dict[int, int],
) -> float:
    """
    Score compuesto [0, 1] usado para ordenar candidatos dentro de un slot.
    Mayor = mejor.
    """
    synergy = _synergy_score(card, card_roles, archetype)
    mana    = _mana_friendliness(card, deck_colors)
    curve   = _curve_fit(card, current_cmc_distribution)
    rank    = _normalize_rank(card.get("edhrec_rank"))

    score = (W_SYNERGY * synergy +
             W_MANA    * mana    +
             W_CURVE   * curve   +
             W_RANK    * rank)

    # Multi-rol bonus: si la carta cumple varios roles útiles
    useful_roles = card_roles & {
        "ramp", "draw", "removal", "tutor", "protection", "counter",
        "sweeper", "recursion", "threat",
    }
    useful_roles |= {r for r in card_roles if r.startswith("payoff_")}
    if "equipment" in card_roles or "sac_outlet" in card_roles:
        useful_roles.add("utility")

    extra_roles = max(0, len(useful_roles) - 1)
    score *= (1.0 + MULTIROLE_BONUS_PER_ROLE * extra_roles)

    return score


# ---------------------------------------------------------------------------
# Commander selection (sin cambios respecto a v2)
# ---------------------------------------------------------------------------

def select_commander(
    pool: list[dict],
    *,
    name: str | None = None,
    colors: str | None = None,
    archetype: Archetype | None = None,
    min_colors: int = 2,
) -> dict | None:
    if name:
        for c in pool:
            if c["name"].lower() == name.lower():
                if not c.get("can_be_commander"):
                    raise ValueError(f"'{name}' no es válido como comandante")
                return c
        raise ValueError(f"Comandante '{name}' no encontrado en pool real")

    from .commander_score import score_commanders
    scored = score_commanders(pool, min_colors=min_colors, require_legal=False)

    if colors:
        target = set(colors.upper())
        scored = [s for s in scored
                  if set(s.commander.get("color_identity", [])) == target]

    if archetype:
        scored = [s for s in scored
                  if s.archetype and s.archetype.key == archetype.key]

    return scored[0].commander if scored else None


# ---------------------------------------------------------------------------
# Build deck — V3
# ---------------------------------------------------------------------------

def build_deck(
    pool: list[dict],
    *,
    commander_name: str | None = None,
    colors: str | None = None,
    archetype_key: str | None = None,
    target_basics_split: bool = True,
) -> BuiltDeck:
    """
    Construye un mazo de 100 cartas siguiendo el plan del arquetipo.
    V3: scoring compuesto + multi-rol.
    """
    # 1. Comandante
    archetype = ARCHETYPES.get(archetype_key) if archetype_key else None
    commander = select_commander(pool, name=commander_name, colors=colors,
                                  archetype=archetype)
    if not commander:
        raise ValueError(
            f"No se encontró comandante para colors={colors}, "
            f"archetype={archetype_key}"
        )

    # 2. Arquetipo
    if not archetype:
        detected = detect_archetype(commander)
        if not detected:
            raise ValueError(
                f"No pude detectar arquetipo para '{commander['name']}'. "
                f"Pásame uno con --archetype."
            )
        archetype = ARCHETYPES[detected]

    deck_ci = set(commander["color_identity"])
    colors_str = "".join(sorted(deck_ci)) or "C"

    # 3. Pool en identidad (sin tierras, sin comandante)
    in_identity = [c for c in pool
                   if fits_color_identity(c, deck_ci)
                   and c["name"] != commander["name"]
                   and not c.get("is_land")]

    # 4. Pre-clasificar TODAS las cartas: card_name → set(roles)
    roles_by_card: dict[str, set[str]] = {}
    for c in in_identity:
        roles_by_card[c["name"]] = cls.classify(c)

    deck = BuiltDeck(commander=commander, archetype=archetype, colors=colors_str)
    selected_names: set[str] = {commander["name"]}
    cmc_distribution: dict[int, int] = {}

    def _track_cmc(card: dict) -> None:
        cm = int(cmc(card) or 0)
        cmc_distribution[cm] = cmc_distribution.get(cm, 0) + 1

    # 5. Auto-includes del arquetipo
    for auto_name in archetype.auto_includes:
        if auto_name in selected_names:
            continue
        match = next((c for c in in_identity if c["name"] == auto_name), None)
        if match:
            deck.cards.append(DeckCard(
                match,
                category="Core / Auto-includes",
                role="Staple",
                justification=f"Auto-incluido: pieza clave del arquetipo {archetype.name}.",
            ))
            selected_names.add(auto_name)
            _track_cmc(match)

    # 6. Slots del arquetipo — con score compuesto
    for slot in archetype.slots:
        # Candidatos que pasan el predicado y no están ya seleccionados
        candidates = [c for c in in_identity
                      if c["name"] not in selected_names
                      and slot.predicate(c)]

        # Ordenar por score compuesto (descendente = mejor primero)
        candidates.sort(
            key=lambda c: -composite_score(
                c,
                roles_by_card.get(c["name"], set()),
                archetype,
                deck_ci,
                cmc_distribution,
            )
        )

        for c in candidates[:slot.target_count]:
            deck.cards.append(DeckCard(
                c,
                category=slot.name,
                role=slot.role_label,
                justification=slot.justification,
            ))
            selected_names.add(c["name"])
            _track_cmc(c)

    # 7. Tierras de utilidad
    utility_lands = [
        c for c in pool
        if c.get("is_land")
        and not is_basic_land(c)
        and fits_color_identity(c, deck_ci)
    ]

    def land_score(land: dict) -> float:
        produced = land.get("produced_mana", []) or []
        wubrg = [m for m in produced if m in ("W", "U", "B", "R", "G")]
        return -len(wubrg) * 100_000 + (land.get("edhrec_rank") or 999_999)

    utility_lands.sort(key=land_score)
    util_count = min(12, len(utility_lands))
    for land in utility_lands[:util_count]:
        if land["name"] in selected_names:
            continue
        deck.cards.append(DeckCard(
            land,
            category="Tierras No-Básicas",
            role="Land",
            justification="Tierra de utilidad / dual.",
        ))
        selected_names.add(land["name"])

    # 8. Básicas para llegar a 100
    deck.needed_basics = max(0, 99 - len(deck.cards))

    return deck
