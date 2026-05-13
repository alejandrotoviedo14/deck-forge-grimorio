"""
builder.py — Construye un mazo de 100 cartas.

Algoritmo:
1. Selecciona comandante (provisto o detectado).
2. Filtra el pool por color identity del comandante.
3. Para cada slot del arquetipo:
   - Filtra candidatos con el predicado del slot
   - Excluye los ya seleccionados
   - Ordena por score
   - Selecciona los top N
4. Auto-includes del arquetipo (si están en pool y no seleccionados ya)
5. Slot de TIERRAS: utility lands + básicas para llegar a 100
"""

from dataclasses import dataclass, field

from . import classifier as cls
from .pool import (
    fits_color_identity, has_text, has_type, cmc, edhrec_rank,
    is_basic_land, is_legal_in_commander,
)
from .archetypes import Archetype, ARCHETYPES, detect_archetype


@dataclass
class DeckCard:
    """Una carta en el mazo, con metadata de por qué está."""
    card: dict  # raw card dict del pool
    category: str
    role: str
    justification: str

    @property
    def name(self) -> str:
        return self.card["name"]


@dataclass
class BuiltDeck:
    """Resultado de la construcción: mazo + metadata."""
    commander: dict
    archetype: Archetype
    colors: str  # ej. "GU"
    cards: list[DeckCard] = field(default_factory=list)
    needed_basics: int = 0  # nº de básicas a añadir para llegar a 100

    @property
    def card_count(self) -> int:
        return len(self.cards) + 1  # +1 commander

    def categorized(self) -> dict[str, list[DeckCard]]:
        """Agrupa cartas por categoría."""
        out: dict[str, list[DeckCard]] = {}
        for c in self.cards:
            out.setdefault(c.category, []).append(c)
        return out

    def all_cards_with_basics(self, basics: dict[str, dict] | None = None) -> list[dict]:
        """
        Devuelve la lista plana de TODAS las cartas como dicts crudos para
        cálculos (bracket score, etc.). Para básicas, genera dicts mínimos
        (name + is_land=True) suficientes para los cálculos de bracket.
        """
        out = [self.commander] + [c.card for c in self.cards]
        if self.needed_basics > 0:
            colors = list(self.colors)
            split = self.needed_basics // len(colors)
            rem = self.needed_basics - split * len(colors)
            basic_map = {"W":"Plains","U":"Island","B":"Swamp","R":"Mountain","G":"Forest"}
            for i, c in enumerate(colors):
                n = split + (1 if i < rem else 0)
                bn = basic_map[c]
                # Stub mínimo para bracket calc — no necesita oracle text porque
                # las básicas no son game changers ni nada relevante para score
                stub = {
                    "name": bn,
                    "is_land": True,
                    "cmc": 0,
                    "type_line": f"Basic Land — {bn}",
                    "oracle_text": "",
                    "produced_mana": [c],
                    "color_identity": [],
                }
                for _ in range(n):
                    out.append(stub)
        return out


def select_commander(
    pool: list[dict],
    *,
    name: str | None = None,
    colors: str | None = None,
    archetype: Archetype | None = None,
    min_colors: int = 2,
) -> dict | None:
    """
    Elige comandante.
    Prioridad:
      - name: si se pasa, busca por nombre exacto.
      - colors + archetype: encuentra el mejor matching legendary con score compuesto.
      - colors: el legendary con mejor score en esos colores.

    El score compuesto (sinergia + bracket + rank) está en commander_score.py
    y se usa en lugar de solo EDHREC rank.
    """
    if name:
        for c in pool:
            if c["name"].lower() == name.lower():
                if not c.get("can_be_commander"):
                    raise ValueError(f"'{name}' no es válido como comandante")
                return c
        raise ValueError(f"Comandante '{name}' no encontrado en pool real")

    # Sin nombre explícito: usar score compuesto
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


def build_deck(
    pool: list[dict],
    *,
    commander_name: str | None = None,
    colors: str | None = None,
    archetype_key: str | None = None,
    target_basics_split: bool = True,
) -> BuiltDeck:
    """
    Construye un mazo siguiendo el plan del arquetipo.

    Parámetros:
        pool: pool real verdadero (sin fakes, dedup)
        commander_name: si se especifica, fuerza ese comandante
        colors: ej. "GU" para Simic. Requerido si no hay commander_name.
        archetype_key: 'counters' | 'equipment' | 'aristocrats' | 'spellslinger'.
                       Si None, se detecta del comandante.
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

    # 3. Pool en identidad
    in_identity = [c for c in pool
                   if fits_color_identity(c, deck_ci)
                   and c["name"] != commander["name"]
                   and not c.get("is_land")]  # tierras se gestionan aparte

    deck = BuiltDeck(commander=commander, archetype=archetype, colors=colors_str)
    selected_names: set[str] = {commander["name"]}

    # 4. Auto-includes del arquetipo (si están en pool y no seleccionados)
    auto_added = 0
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
            auto_added += 1

    # 5. Slots del arquetipo
    for slot in archetype.slots:
        candidates = [c for c in in_identity
                      if c["name"] not in selected_names
                      and slot.predicate(c)]
        candidates.sort(key=slot.scorer)
        for c in candidates[:slot.target_count]:
            deck.cards.append(DeckCard(
                c,
                category=slot.name,
                role=slot.role_label,
                justification=slot.justification,
            ))
            selected_names.add(c["name"])

    # 6. Tierras de utilidad (no básicas) en identidad
    utility_lands = [
        c for c in pool
        if c.get("is_land")
        and not is_basic_land(c)
        and fits_color_identity(c, deck_ci)
    ]
    # Score lands: priorizamos las que producen más colores (mejor fixing)
    def land_score(land: dict) -> float:
        produced = land.get("produced_mana", []) or []
        wubrg = [m for m in produced if m in ("W","U","B","R","G")]
        # Negativo del nº colores (más colores = mejor) + edhrec_rank tiebreak
        return -len(wubrg) * 100_000 + (land.get("edhrec_rank") or 999_999)

    utility_lands.sort(key=land_score)
    # Cap en 12 utility lands
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

    # 7. Calcular cuántas básicas faltan para llegar a 100
    # 100 = commander (1) + cards (?) + basics (?)
    deck.needed_basics = max(0, 99 - len(deck.cards))

    return deck
