"""
commander_score.py — Scoring inteligente de comandantes.

NO usa edhrec_rank como métrica principal (es popularidad, no calidad).
En su lugar combina:

    1. PROFUNDIDAD DE SINERGIA (40%): cuántas cartas de tu pool encajan
       con el arquetipo natural del comandante.
    2. TECHO DE BRACKET (40%): el bracket score más alto alcanzable
       construyendo un mazo con este comandante desde tu pool.
    3. EDHREC RANK (20%): solo como desempate suave — comandantes
       populares tienen más guías/contenido online.

Output: lista ordenada de comandantes con desglose del score.
"""

from dataclasses import dataclass

from .pool import fits_color_identity, edhrec_rank
from .archetypes import ARCHETYPES, detect_archetype, Archetype


@dataclass
class CommanderScore:
    """Score detallado de un comandante candidato."""
    commander: dict
    archetype: Archetype | None
    synergy_density: float     # 0-100: % del pool en identidad que sirve al arquetipo
    synergy_raw: int           # nº absoluto de cartas relevantes
    synergy_total: int         # total cartas no-tierra en identidad
    bracket_ceiling: float     # 1.0-5.0: bracket alcanzable
    rank_score: float          # 0-100: rank EDHREC normalizado
    total_score: float         # weighted sum

    @property
    def name(self) -> str:
        return self.commander["name"]

    @property
    def colors(self) -> str:
        return "".join(sorted(self.commander.get("color_identity", []))) or "C"

    def summary_line(self) -> str:
        arch = self.archetype.name if self.archetype else "—"
        ci = self.colors
        return (
            f"score {self.total_score:5.1f} | "
            f"[{ci:5s}] {self.name:35s} | "
            f"{arch:30s} | "
            f"densidad {self.synergy_density:4.1f}% ({self.synergy_raw}/{self.synergy_total}), "
            f"bracket~{self.bracket_ceiling:.1f}, "
            f"rank #{self.commander.get('edhrec_rank') or '?'}"
        )


def _synergy_metrics(commander: dict, archetype: Archetype, pool: list[dict]) -> tuple[int, int, float]:
    """
    Devuelve (raw_count, total_in_identity, density).

    - raw_count: cartas que cumplen al menos un slot específico del arquetipo
    - total_in_identity: cartas no-tierra del pool en la identidad del comandante
    - density: raw_count / total_in_identity (cuán "puro" es el pool para este arquetipo)

    La densidad es el verdadero diferenciador: un pool 5-color tiene muchas
    cartas pero pocas pueden ser relevantes para un arquetipo concreto.
    """
    deck_ci = set(commander.get("color_identity", []))
    if not deck_ci:
        return (0, 0, 0.0)

    in_identity = [
        c for c in pool
        if fits_color_identity(c, deck_ci)
        and c["name"] != commander["name"]
        and not c.get("is_land")
    ]

    archetype_specific_slots = [
        s for s in archetype.slots
        if s.name not in ("Ramp", "Card Draw", "Removal", "Card Draw / Cantrips",
                          "Removal & Interaction", "Removal / Bounce")
    ]
    if not archetype_specific_slots:
        archetype_specific_slots = archetype.slots

    raw = sum(
        1 for card in in_identity
        if any(slot.predicate(card) for slot in archetype_specific_slots)
    )
    total = len(in_identity)
    density = raw / total if total else 0.0
    return (raw, total, density)


def _bracket_ceiling(commander: dict, archetype: Archetype, pool: list[dict]) -> float:
    """
    Estima el bracket score MÁXIMO alcanzable con este comandante.

    Heurística rápida sin construir el mazo entero:
    - Cuenta game changers, fast mana, tutors disponibles en la identidad
    - Suma señales que el bracket score premia
    - No construye mazo (sería caro hacer 100+ veces)
    """
    from .bracket import _load_reference

    deck_ci = set(commander.get("color_identity", []))
    in_identity_names = {
        c["name"] for c in pool
        if fits_color_identity(c, deck_ci)
    }

    ref = _load_reference()
    gc = len(in_identity_names & set(ref["game_changers"]))
    fm = len(in_identity_names & set(ref["fast_mana"]))
    tut = len(in_identity_names & set(ref["restrictive_tutors"]))

    # Replicamos roughly la lógica de estimate_bracket
    score = 1.0
    if gc >= 1: score += 1.5
    if gc >= 4: score += 1.0
    if fm >= 2: score += 0.8
    elif fm == 1: score += 0.4
    if tut >= 1: score += 0.5
    if tut >= 3: score += 0.5

    # Bonus por staples universales accesibles
    universal = {"Sol Ring", "Arcane Signet", "Command Tower", "Mind Stone", "Fellwar Stone"}
    if not (in_identity_names & universal):
        score -= 0.4

    return max(1.0, min(score, 5.0))


def _normalize_rank(rank: int | None) -> float:
    """Normaliza EDHREC rank a 0-100 (rank 1 = 100, rank 50000+ = 0)."""
    if not rank:
        return 0.0
    if rank <= 100: return 100.0
    if rank >= 50000: return 0.0
    # Escala logarítmica suave
    import math
    return max(0.0, 100.0 - (math.log10(rank) - 2) * 33.3)


def score_commanders(
    pool: list[dict],
    *,
    min_colors: int = 2,
    require_legal: bool = False,  # ignoramos banlist por defecto
) -> list[CommanderScore]:
    """
    Puntúa todos los comandantes candidatos en el pool.

    Métricas (weighted sum):
        - 50% densidad de sinergia (% del pool en identidad que sirve al arquetipo)
        - 30% bracket alcanzable (techo de potencia construyendo desde tu pool)
        - 20% popularidad EDHREC (desempate suave)

    Args:
        pool: pool real verdadero
        min_colors: mínimo de colores en color identity (2 = bicolor mínimo)
        require_legal: si True, filtra por banlist oficial de Commander

    Returns:
        Lista ordenada por total_score descendente
    """
    candidates = [
        c for c in pool
        if c.get("can_be_commander")
        and len(c.get("color_identity", [])) >= min_colors
    ]
    if require_legal:
        candidates = [c for c in candidates
                      if c.get("legalities", {}).get("commander") == "legal"]

    scores: list[CommanderScore] = []

    for cmd in candidates:
        archetype_key = detect_archetype(cmd)
        archetype = ARCHETYPES[archetype_key] if archetype_key else None

        if not archetype:
            scores.append(CommanderScore(
                commander=cmd, archetype=None,
                synergy_density=0.0, synergy_raw=0, synergy_total=0,
                bracket_ceiling=1.0,
                rank_score=_normalize_rank(cmd.get("edhrec_rank")),
                total_score=0.0,
            ))
            continue

        raw, total, density = _synergy_metrics(cmd, archetype, pool)
        # Density ya es 0-1; multiplicamos x 100 para escala consistente
        # Cap saludable: density > 0.15 (15% del pool sirve) ya es excelente
        # Escalamos: density 0.15+ → 100, density 0 → 0
        density_score = min(density / 0.15 * 100.0, 100.0)

        bracket = _bracket_ceiling(cmd, archetype, pool)
        # Bracket score: 1.0 → 0, 5.0 → 100
        bracket_score = (bracket - 1.0) / 4.0 * 100.0

        rank_score = _normalize_rank(cmd.get("edhrec_rank"))

        # Weighted: densidad 50% + bracket 30% + rank 20%
        total_score = (
            density_score * 0.5
            + bracket_score * 0.3
            + rank_score * 0.2
        )

        scores.append(CommanderScore(
            commander=cmd, archetype=archetype,
            synergy_density=density * 100.0,
            synergy_raw=raw, synergy_total=total,
            bracket_ceiling=bracket,
            rank_score=rank_score,
            total_score=total_score,
        ))

    scores.sort(key=lambda s: -s.total_score)
    return scores
