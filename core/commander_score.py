"""
commander_score.py — Scoring inteligente de comandantes v2.

Correcciones sobre v1:
  FIX 1 — Multi-arquetipo: evalúa TODOS los arquetipos para cada comandante
           y se queda con el que mejor encaja con el pool del jugador.
  FIX 2 — Comandantes sin arquetipo detectado: reciben score basado en
           pool relevance y popularidad, no score 0.
  FIX 3 — Bracket ceiling más granular: usa pesos distintos por tipo de carta
           en lugar de umbrales binarios que igualan a todos.

Métricas (weighted sum, ahora 4 componentes):
    - 45% densidad de sinergia  (mejor arquetipo disponible en el pool)
    - 25% relevancia EDHREC     (% cartas del pool recomendadas para este cmd)
    - 20% bracket alcanzable    (potencia real construible)
    - 10% popularidad EDHREC    (desempate suave — contenido online disponible)
"""

from __future__ import annotations
import math
from dataclasses import dataclass

from .pool import fits_color_identity, edhrec_rank
from .archetypes import ARCHETYPES, detect_archetype, Archetype


@dataclass
class CommanderScore:
    commander:       dict
    archetype:       Archetype | None
    synergy_density: float      # 0-100: % del pool en identidad que sirve al arquetipo
    synergy_raw:     int
    synergy_total:   int
    bracket_ceiling: float      # 1.0-5.0
    rank_score:      float      # 0-100
    edhrec_relevance: float     # 0-100: % pool que EDHREC recomienda para este cmd
    total_score:     float

    @property
    def name(self) -> str:
        return self.commander["name"]

    @property
    def colors(self) -> str:
        return "".join(sorted(self.commander.get("color_identity", []))) or "C"


# ── Helpers de normalización ──────────────────────────────────────────────

def _normalize_rank(rank: int | None) -> float:
    """Normaliza EDHREC rank global a 0-100 (rank 1→100, rank 50k+→0)."""
    if not rank:
        return 0.0
    if rank <= 100:
        return 100.0
    if rank >= 50_000:
        return 0.0
    return max(0.0, 100.0 - (math.log10(rank) - 2) * 33.3)


# ── FIX 1: Multi-arquetipo ────────────────────────────────────────────────

def _synergy_for_archetype(
    commander: dict,
    archetype: Archetype,
    pool: list[dict],
) -> tuple[int, int, float]:
    """
    (raw, total, density) del pool para un arquetipo concreto.
    Evalúa TODOS los slots (incluido ramp/draw) para mayor discriminación.
    """
    deck_ci = set(commander.get("color_identity", []))
    in_identity = [
        c for c in pool
        if fits_color_identity(c, deck_ci)
        and c["name"] != commander["name"]
        and not c.get("is_land")
    ]
    if not in_identity:
        return (0, 0, 0.0)

    # Usar todos los slots — el total de cartas útiles es lo que cuenta
    raw = sum(
        1 for card in in_identity
        if any(slot.predicate(card) for slot in archetype.slots)
    )
    total = len(in_identity)
    density = raw / total if total else 0.0
    return (raw, total, density)


def _best_archetype_score(
    commander: dict,
    pool: list[dict],
) -> tuple[Archetype | None, int, int, float]:
    """
    FIX 1: prueba TODOS los arquetipos y devuelve el que mejor encaja.
    Además intenta con el arquetipo detectado por oracle text primero.
    """
    best_arch   = None
    best_raw    = 0
    best_total  = 0
    best_density = 0.0

    # Orden: primero el detectado (por oracle text), luego todos los demás
    detected_key = detect_archetype(commander)
    arch_order = []
    if detected_key and detected_key in ARCHETYPES:
        arch_order.append(detected_key)
    for k in ARCHETYPES:
        if k not in arch_order:
            arch_order.append(k)

    for arch_key in arch_order:
        arch = ARCHETYPES[arch_key]
        raw, total, density = _synergy_for_archetype(commander, arch, pool)
        # Pequeño bonus al arquetipo detectado (oracle text es señal real)
        bonus = 0.02 if arch_key == detected_key else 0.0
        if density + bonus > best_density + 0.0:
            best_arch    = arch
            best_raw     = raw
            best_total   = total
            best_density = density + bonus

    return (best_arch, best_raw, best_total, best_density)


# ── FIX 3: Bracket ceiling granular ─────────────────────────────────────

def _bracket_ceiling(commander: dict, pool: list[dict]) -> float:
    """
    FIX 3: usa pesos continuos por tipo de carta en lugar de umbrales binarios.
    Esto diferencia mejor entre colecciones similares.
    """
    from .bracket import _load_reference

    deck_ci = set(commander.get("color_identity", []))
    in_identity_names = {
        c["name"] for c in pool
        if fits_color_identity(c, deck_ci)
    }

    ref = _load_reference()
    gc  = len(in_identity_names & set(ref["game_changers"]))
    fm  = len(in_identity_names & set(ref["fast_mana"]))
    tut = len(in_identity_names & set(ref["restrictive_tutors"]))

    # Escala continua: cada pieza suma, sin saltos binarios
    score = 1.0
    score += min(gc  * 0.60, 2.50)   # game changers: cap en 2.5 extra
    score += min(fm  * 0.45, 1.50)   # fast mana:     cap en 1.5 extra
    score += min(tut * 0.35, 1.20)   # tutors:        cap en 1.2 extra

    # Penalty si faltan staples básicos (Sol Ring, signets…)
    universal = {"Sol Ring", "Arcane Signet", "Command Tower", "Fellwar Stone", "Mind Stone"}
    staple_count = len(in_identity_names & universal)
    if staple_count == 0:
        score -= 0.6
    elif staple_count == 1:
        score -= 0.3

    return max(1.0, min(score, 5.0))


# ── FIX 2: Relevancia EDHREC ─────────────────────────────────────────────

_edhrec_cache: dict[str, dict] = {}   # cache en memoria para esta sesión


def _edhrec_relevance(commander_name: str, pool_names: set[str]) -> float:
    """
    FIX 2: usa los datos de EDHREC ya integrados para medir qué % de tu pool
    recomienda EDHREC para este comandante específico.
    0 si no hay datos disponibles (neutral, no penaliza).
    """
    global _edhrec_cache
    try:
        if commander_name not in _edhrec_cache:
            from .edhrec_advisor import EDHRecAdvisor
            adv = EDHRecAdvisor(verbose=False)
            _edhrec_cache[commander_name] = adv.fetch_commander_data(commander_name)
        data = _edhrec_cache[commander_name]
        edhrec_names = {n.lower() for n in data.get("all_cards", {})}
        if not edhrec_names:
            return 0.0
        pool_lower = {n.lower() for n in pool_names}
        overlap = len(pool_lower & edhrec_names)
        # Normalizar: 15+ cartas en común → 100
        return min(overlap / 15 * 100.0, 100.0)
    except Exception:
        return 0.0


# ── Función principal ─────────────────────────────────────────────────────

def score_commanders(
    pool: list[dict],
    *,
    min_colors: int = 2,
    require_legal: bool = False,
    use_edhrec: bool = True,
) -> list[CommanderScore]:
    """
    Puntúa todos los comandantes candidatos del pool.

    Fórmula v2:
        45% mejor densidad de sinergia (multi-arquetipo)
        25% relevancia EDHREC (cartas del pool recomendadas para este cmd)
        20% bracket alcanzable (potencia real)
        10% popularidad EDHREC (desempate)

    Nota: use_edhrec=False desactiva las llamadas a EDHREC (más rápido,
    menos preciso). El 25% de relevancia queda en 0 para todos.
    """
    candidates = [
        c for c in pool
        if c.get("can_be_commander")
        and len(c.get("color_identity", [])) >= min_colors
    ]
    if require_legal:
        candidates = [
            c for c in candidates
            if c.get("legalities", {}).get("commander") == "legal"
        ]

    pool_names = {c["name"] for c in pool}
    scores: list[CommanderScore] = []

    for cmd in candidates:
        # FIX 1: mejor arquetipo entre todos
        arch, raw, total, density = _best_archetype_score(cmd, pool)

        # density: escala 0→1 donde 0.15 (15% del pool) ya es excelente
        # Cap saludable en 100
        density_score = min(density / 0.15 * 100.0, 100.0)

        # FIX 3: bracket granular
        bracket = _bracket_ceiling(cmd, pool)
        bracket_score = (bracket - 1.0) / 4.0 * 100.0

        # Popularidad (desempate suave)
        rank_sc = _normalize_rank(cmd.get("edhrec_rank"))

        # FIX 2: relevancia EDHREC
        rel_sc = 0.0
        if use_edhrec:
            rel_sc = _edhrec_relevance(cmd["name"], pool_names)

        # FIX 2: comandantes sin arquetipo ya no reciben 0 automático
        # Si arch es None, su score depende de EDHREC + bracket + popularidad
        if arch is None:
            total_score = (
                rel_sc    * 0.45
                + bracket_score * 0.30
                + rank_sc       * 0.25
            )
        else:
            total_score = (
                density_score  * 0.45
                + rel_sc       * 0.25
                + bracket_score * 0.20
                + rank_sc       * 0.10
            )

        scores.append(CommanderScore(
            commander        = cmd,
            archetype        = arch,
            synergy_density  = density * 100.0,
            synergy_raw      = raw,
            synergy_total    = total,
            bracket_ceiling  = bracket,
            rank_score       = rank_sc,
            edhrec_relevance = rel_sc,
            total_score      = round(total_score, 1),
        ))

    scores.sort(key=lambda s: -s.total_score)
    return scores
