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
    impact: str = ""  # impacto esperado específico (generado por el LLM)

    @property
    def name(self) -> str:
        return self.card["name"]


@dataclass
class ConflictEntry:
    """Una carta en conflicto con otro mazo de la sesión."""
    card_name: str          # carta solicitada pero reservada
    reserved_by: str        # nombre del mazo que la tiene
    alternative: str | None # carta alternativa elegida (None si no hay)
    slot: str               # slot donde se produjo el conflicto


@dataclass
class BuiltDeck:
    commander: dict
    archetype: Archetype
    colors: str
    cards: list[DeckCard] = field(default_factory=list)
    needed_basics: int = 0
    gameplay_guide: str = ""  # HTML generado por LLM Critic
    conflicts: list[ConflictEntry] = field(default_factory=list)

    @property
    def card_count(self) -> int:
        return len(self.cards) + 1

    def categorized(self) -> dict[str, list[DeckCard]]:
        out: dict[str, list[DeckCard]] = {}
        for c in self.cards:
            out.setdefault(c.category, []).append(c)
        return out

    def color_pip_distribution(self) -> dict[str, int]:
        """
        Cuenta los pips de color en los costes de maná de todo el mazo
        (comandante incluido). Base para repartir básicas proporcionalmente.
        """
        pips: dict[str, int] = {}
        for card in [self.commander] + [c.card for c in self.cards]:
            mana_cost = (card.get("mana_cost") or "").upper()
            for c in "WUBRG":
                n = mana_cost.count(f"{{{c}}}") + mana_cost.count(f"/{c}}}")
                if n:
                    pips[c] = pips.get(c, 0) + n
        return pips

    def all_cards_with_basics(self, basics: dict[str, dict] | None = None) -> list[dict]:
        """
        Reparte las básicas PROPORCIONALMENTE a los pips de color del mazo
        (no a partes iguales). Un mazo WUB con 60% de pips negros recibe ~60%
        Swamps. Mínimo 2 básicas por color para estabilidad.
        """
        out = [self.commander] + [c.card for c in self.cards]
        if self.needed_basics <= 0:
            return out

        colors = [c for c in self.colors if c in "WUBRG"]
        if not colors:
            colors = ["C"]
        basic_map = {"W": "Plains", "U": "Island", "B": "Swamp",
                     "R": "Mountain", "G": "Forest", "C": "Wastes"}

        pips = self.color_pip_distribution()
        pips = {c: pips.get(c, 0) for c in colors}
        total_pips = sum(pips.values())

        counts: dict[str, int] = {}
        if total_pips == 0 or len(colors) == 1:
            # Sin información de pips o monocolor: reparto uniforme
            split = self.needed_basics // len(colors)
            rem = self.needed_basics - split * len(colors)
            for i, c in enumerate(colors):
                counts[c] = split + (1 if i < rem else 0)
        else:
            # Mínimo garantizado por color, resto proporcional a pips
            min_per_color = min(2, self.needed_basics // len(colors))
            remaining = self.needed_basics - min_per_color * len(colors)
            for c in colors:
                counts[c] = min_per_color
            if remaining > 0:
                quotas = {c: remaining * pips[c] / total_pips for c in colors}
                floors = {c: int(quotas[c]) for c in colors}
                assigned = sum(floors.values())
                for c in colors:
                    counts[c] += floors[c]
                # Restos: a los colores con mayor parte fraccional
                leftovers = sorted(colors, key=lambda c: -(quotas[c] - floors[c]))
                for i in range(remaining - assigned):
                    counts[leftovers[i % len(leftovers)]] += 1

        for c, n in counts.items():
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
    Convierte EDHREC rank en score [0,1] de forma continua.
    Rank 1 = 1.0, rank 50000+ = ~0.1
    Cartas sin rank (nuevas/raras) = 0.45 (neutral-negativo)
    """
    if rank is None:
        return 0.45
    if rank <= 0:
        return 1.0
    import math
    # Función logarítmica inversa: score = 1 - log(rank) / log(max_rank)
    # Con max_rank=50000: rank 1→0.99, rank 100→0.81, rank 1000→0.67,
    # rank 5000→0.53, rank 20000→0.42, rank 50000→0.33
    max_rank = 50000
    score = 1.0 - math.log(max(rank, 1)) / math.log(max_rank)
    return max(0.1, min(1.0, score))


def _mana_friendliness(card: dict, deck_colors: set[str]) -> float:
    """
    Cuánto de fácil es castear esta carta.
    Combina: pips de color + CMC total.
    Penaliza fuertemente cartas de CMC alto aunque sean incoloras.
    """
    mana_cost = (card.get("mana_cost") or "").upper()
    card_cmc = int(cmc(card) or 0)

    # Penalización base por CMC alto
    if card_cmc == 0:
        cmc_factor = 1.0
    elif card_cmc <= 2:
        cmc_factor = 0.95
    elif card_cmc <= 3:
        cmc_factor = 0.85
    elif card_cmc <= 4:
        cmc_factor = 0.70
    elif card_cmc <= 5:
        cmc_factor = 0.50
    elif card_cmc <= 6:
        cmc_factor = 0.30
    else:
        cmc_factor = 0.15  # 7+ mana = muy caro

    if not mana_cost:
        return cmc_factor

    # Penalización por pips de color
    color_pips: dict[str, int] = {}
    for c in "WUBRG":
        n = mana_cost.count(f"{{{c}}}")
        if n:
            color_pips[c] = n

    if not color_pips:
        return cmc_factor  # solo genérico

    max_same_color = max(color_pips.values())
    if max_same_color >= 3:
        pip_factor = 0.5
    elif max_same_color == 2:
        pip_factor = 0.75
    else:
        pip_factor = 1.0

    return cmc_factor * pip_factor


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
    Score compuesto para ordenar candidatos dentro de un slot.
    Mayor = mejor.

    Filosofía: EDHREC rank es el mejor proxy de calidad disponible.
    CMC desempata entre cartas de rank similar.
    EDHREC por comandante (cuando disponible) se añade como bonus.
    """
    rank    = _normalize_rank(card.get("edhrec_rank"))
    card_cmc = int(cmc(card) or 0)

    # CMC factor: penaliza cartas caras linealmente
    if card_cmc == 0:
        cmc_factor = 1.0
    elif card_cmc <= 2:
        cmc_factor = 0.95
    elif card_cmc == 3:
        cmc_factor = 0.85
    elif card_cmc == 4:
        cmc_factor = 0.70
    elif card_cmc == 5:
        cmc_factor = 0.55
    elif card_cmc == 6:
        cmc_factor = 0.35
    else:
        cmc_factor = 0.20  # 7+ muy caro

    # Sinergia ESPECÍFICA con el comandante (EDHREC por comandante).
    # Es la señal más fuerte: una carta que aparece mucho con ESTE comandante
    # vale más que una carta genéricamente buena.
    edhrec_score = card.get("edhrec_score")
    synergy_commander = edhrec_score if edhrec_score is not None else 0.30

    # Sinergia con el ARQUETIPO (densidad de roles relevantes).
    synergy_archetype = _synergy_score(card, card_roles, archetype)

    # Nuevo peso: la sinergia domina, el rank general desempata, CMC ajusta curva.
    #   40% sinergia con comandante
    #   25% sinergia con arquetipo
    #   25% rank general (calidad bruta)
    #   10% curva (CMC)
    score = (
        0.40 * synergy_commander +
        0.25 * synergy_archetype +
        0.25 * rank +
        0.10 * cmc_factor
    )

    # Ajuste de curva: premia rellenar huecos, penaliza saturar
    count_at_cmc = current_cmc_distribution.get(card_cmc, 0)
    if count_at_cmc == 0:
        score *= 1.06
    elif count_at_cmc >= 6:
        score *= 0.92

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
    use_edhrec: bool = True,
    reserved_cards: dict[str, str] | None = None,  # {card_name: deck_name_that_owns_it}
) -> BuiltDeck:
    """
    Construye un mazo de 100 cartas siguiendo el plan del arquetipo.
    V3: scoring compuesto + multi-rol + EDHREC integration.

    use_edhrec: si True (default), consulta EDHREC para enriquecer el scoring.
                Si False o si EDHREC falla, usa solo el scoring local.
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

    # 2. Arquetipo — v4: EDHREC themes primero (datos reales de la comunidad),
    #    heurística de oracle text como fallback.
    if not archetype:
        detected = None
        if use_edhrec:
            try:
                from .archetypes import archetype_from_themes
                from .edhrec_advisor import EDHRecAdvisor
                themes = EDHRecAdvisor(verbose=False).fetch_commander_data(
                    commander["name"]
                ).get("themes") or []
                detected = archetype_from_themes(themes)
                if detected:
                    print(f"  [BUILD] Arquetipo por EDHREC themes {themes[:3]}: {detected}")
            except Exception as e:
                print(f"  [BUILD] EDHREC themes no disponibles ({e})")
        if not detected:
            detected = detect_archetype(commander)
        if not detected:
            raise ValueError(
                f"No pude detectar arquetipo para '{commander['name']}'. "
                f"Pásame uno con --archetype."
            )
        archetype = ARCHETYPES[detected]

    # Identidad de color — fallback a colors si color_identity está vacío
    deck_ci = set(commander.get("color_identity") or commander.get("colors") or [])
    if not deck_ci and colors:
        deck_ci = set(colors.upper())
    colors_str = "".join(sorted(deck_ci)) or "C"

    print(f"  [BUILD] Comandante: {commander['name']} | Identidad: {colors_str}")

    # 3. Pool en identidad (sin tierras, sin comandante)
    in_identity = [c for c in pool
                   if fits_color_identity(c, deck_ci)
                   and c["name"] != commander["name"]
                   and not c.get("is_land")]

    # 4. EDHREC enrichment — añade edhrec_score a cada carta del pool
    if use_edhrec:
        try:
            from .edhrec_advisor import EDHRecAdvisor
            advisor = EDHRecAdvisor(verbose=True)
            in_identity = advisor.rank_pool_for_commander(
                commander["name"], in_identity
            )
        except Exception as e:
            print(f"  [EDHREC] No disponible ({e}). Usando scoring local.")

    # 5. Pre-clasificar TODAS las cartas: card_name → set(roles)
    roles_by_card: dict[str, set[str]] = {}
    for c in in_identity:
        roles_by_card[c["name"]] = cls.classify(c)

    reserved = reserved_cards or {}  # {card_name_lower: deck_name}
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

    # 6. Slots del arquetipo — con score compuesto y detección de conflictos
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

        added = 0
        skip_idx = 0
        while added < slot.target_count and skip_idx < len(candidates):
            c = candidates[skip_idx]
            skip_idx += 1
            name_lower = c["name"].lower()

            if name_lower in reserved:
                # Conflicto — buscar la siguiente mejor alternativa
                owner = reserved[name_lower]
                # La alternativa es el siguiente candidato no reservado no seleccionado
                alt = next(
                    (x for x in candidates[skip_idx:]
                     if x["name"].lower() not in reserved
                     and x["name"] not in selected_names),
                    None,
                )
                deck.conflicts.append(ConflictEntry(
                    card_name=c["name"],
                    reserved_by=owner,
                    alternative=alt["name"] if alt else None,
                    slot=slot.name,
                ))
                print(f"  [CONFLICT] '{c['name']}' reservada por '{owner}' "
                      f"→ alternativa: '{alt['name'] if alt else 'ninguna'}'")
                # Usar la alternativa si existe
                if alt:
                    c = alt
                    skip_idx = candidates.index(alt) + 1  # avanzar el puntero
                else:
                    continue  # sin alternativa, saltar slot

            deck.cards.append(DeckCard(
                c,
                category=slot.name,
                role=slot.role_label,
                justification=slot.justification,
            ))
            selected_names.add(c["name"])
            _track_cmc(c)
            added += 1

    # 7. Tierras — número DINÁMICO según curva y ramp (v4)
    # Heurística tipo Karsten adaptada a Commander:
    #   total_lands = 31 + avg_cmc*2 - ramp_count*0.4, clamp [33, 40]
    # Un mazo agresivo de curva 2.5 con 10 ramp → ~33; big mana curva 4 → ~38.
    _non_land_so_far = [dc.card for dc in deck.cards if not dc.card.get("is_land")]
    _cmcs = [int(cmc(c) or 0) for c in _non_land_so_far]
    _avg_cmc = (sum(_cmcs) / len(_cmcs)) if _cmcs else 3.0
    _ramp_count = sum(1 for c in _non_land_so_far
                      if "ramp" in roles_by_card.get(c["name"], set()))
    _total_lands = max(33, min(40, round(31 + _avg_cmc * 2 - _ramp_count * 0.4)))

    TARGET_UTILITY_LANDS = min(12, _total_lands - 20)
    TARGET_BASICS         = _total_lands - TARGET_UTILITY_LANDS
    TARGET_NON_LANDS      = 99 - _total_lands

    print(f"  [BUILD] Tierras dinámicas: {_total_lands} "
          f"(avg CMC {_avg_cmc:.2f}, ramp {_ramp_count}) "
          f"= {TARGET_UTILITY_LANDS} utility + {TARGET_BASICS} básicas")

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
    util_added = 0
    for land in utility_lands:
        if util_added >= TARGET_UTILITY_LANDS:
            break
        if land["name"] in selected_names:
            continue
        if land["name"].lower() in reserved:
            owner = reserved[land["name"].lower()]
            deck.conflicts.append(ConflictEntry(
                card_name=land["name"], reserved_by=owner,
                alternative=None, slot="Tierras No-Básicas",
            ))
            print(f"  [CONFLICT] Tierra '{land['name']}' reservada por '{owner}' — omitida")
            continue
        deck.cards.append(DeckCard(
            land,
            category="Tierras No-Básicas",
            role="Land",
            justification="Tierra de utilidad / dual.",
        ))
        selected_names.add(land["name"])
        util_added += 1

    # 7b. Relleno inteligente — si los slots no llenaron TARGET_NON_LANDS,
    #     completamos con las mejores cartas disponibles del pool (sin tierras).
    #     Esto evita mazos con 40-50 básicas por predicados demasiado exigentes.
    non_land_count = sum(1 for dc in deck.cards if not dc.card.get("is_land"))
    remaining_slots = TARGET_NON_LANDS - non_land_count

    if remaining_slots > 0:
        # Candidatos: todo el pool no-tierra, no seleccionado, en identidad
        fill_candidates = [
            c for c in in_identity
            if c["name"] not in selected_names
            and not c.get("is_land")
            and c["name"].lower() not in reserved  # respetar reservas también en relleno
        ]
        # Ordenar por score compuesto descendente (las mejores primero)
        fill_candidates.sort(
            key=lambda c: -composite_score(
                c,
                roles_by_card.get(c["name"], set()),
                archetype,
                deck_ci,
                cmc_distribution,
            )
        )
        filled = 0
        for c in fill_candidates:
            if filled >= remaining_slots:
                break
            deck.cards.append(DeckCard(
                c,
                category="Soporte General",
                role="Support",
                justification="Mejor carta disponible para completar el cupo del mazo.",
            ))
            selected_names.add(c["name"])
            _track_cmc(c)
            filled += 1

        if filled:
            print(f"  [BUILD] Relleno inteligente: {filled} cartas añadidas "
                  f"(slots insuficientes en arquetipos específicos)")

    # 8. LLM Critic — revisa y mejora el mazo si hay API key
    if use_edhrec:  # mismo flag que EDHREC — solo cuando hay conectividad
        try:
            from .llm_critic import LLMCritic
            api_key = __import__("os").environ.get("ANTHROPIC_API_KEY")
            if api_key:
                # Recoger recomendaciones EDHREC si están disponibles
                edhrec_recs: list[str] = []
                try:
                    from .edhrec_advisor import EDHRecAdvisor
                    adv = EDHRecAdvisor(verbose=False)
                    cached_data = adv.fetch_commander_data(commander["name"])
                    hs = cached_data.get("high_synergy", {})
                    edhrec_recs = sorted(hs, key=lambda n: -hs[n].get("synergy", 0))[:15]
                except Exception:
                    pass

                critic = LLMCritic(api_key=api_key, verbose=True)
                deck = critic.review_and_improve(deck, in_identity, edhrec_recs,
                                                 reserved_cards=reserved)

                # Generar guía de juego
                guide_html = critic.generate_gameplay_guide(deck)
                if guide_html:
                    deck.gameplay_guide = guide_html
        except Exception as e:
            print(f"  [CRITIC] Saltando revisión: {e}")

    # 9. Filtro de seguridad FINAL — eliminar cualquier carta fuera de identidad de color
    #    (puede ocurrir si el LLM Critic o EDHREC introdujeron cartas incorrectas)
    illegal = []
    legal_cards = []
    for dc in deck.cards:
        card_ci = set(dc.card.get("color_identity") or [])
        # Las tierras básicas y cartas sin color identity siempre son legales
        if not card_ci or card_ci.issubset(deck_ci) or is_basic_land(dc.card):
            legal_cards.append(dc)
        else:
            illegal.append(dc.card.get("name", "?"))

    if illegal:
        print(f"  [BUILD] ⚠ Eliminadas {len(illegal)} cartas con identidad ilegal: "
              f"{', '.join(illegal)}")
        deck.cards = legal_cards

    # 10. Básicas: siempre exactamente 99 - len(deck.cards)
    #     Garantía matemática de 100 cartas totales (cmd + 99).
    #     Si por alguna razón tenemos > 99 cartas, recortamos las de menor score.
    if len(deck.cards) > 99:
        # Separar tierras y no-tierras
        lands = [dc for dc in deck.cards if dc.card.get("is_land")]
        non_lands = [dc for dc in deck.cards if not dc.card.get("is_land")]
        # Ordenar no-tierras por score desc y recortar las peores
        non_lands.sort(
            key=lambda dc: -composite_score(
                dc.card,
                roles_by_card.get(dc.card.get("name",""), set()),
                archetype, deck_ci, {},
            )
        )
        excess = len(deck.cards) - 99
        non_lands = non_lands[:-excess] if excess <= len(non_lands) else non_lands
        deck.cards = non_lands + lands
        print(f"  [BUILD] Recortadas {excess} cartas excedentes (mantenemos las {len(deck.cards)} mejores)")

    deck.needed_basics = 99 - len(deck.cards)  # siempre ≥ 0 tras el recorte
    print(f"  [BUILD] Total: {len(deck.cards)} cartas reales + {deck.needed_basics} básicas "
          f"+ 1 comandante = 100")

    return deck
