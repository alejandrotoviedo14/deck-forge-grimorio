"""
commander_score.py — Scoring inteligente de comandantes v6.

Filosofía: "el mejor comandante PARA TU COLECCIÓN, no el más popular en
EDHREC". Popularidad (rank_score) queda como desempate mínimo (5%); todo
lo demás se calcula sobre TU pool real Y sobre lo que ESTE comandante
concreto pide.

Correcciones sobre v1-v5:
  FIX 1 — Multi-arquetipo: evalúa TODOS los arquetipos para cada comandante
           y se queda con el que mejor encaja con el pool del jugador.
  FIX 2 — Comandantes sin arquetipo detectado: reciben score basado en
           pool relevance y bracket, no score 0.
  FIX 3 — Bracket ceiling más granular: usa pesos distintos por tipo de carta
           en lugar de umbrales binarios que igualan a todos.
  FIX 5 — Comandantes "de nicho" (pocos datos en EDHREC) no se penalizan.
  FIX 6 (v6) — El score ahora ES específico del comandante:
       a) La densidad ya no satura a 100 en el 15% (curva exponencial suave
          en lugar de cap duro) — antes la mayoría empataba a 100 y el
          desempate real acababa siendo la popularidad EDHREC.
       b) `fit`: mezcla la densidad del arquetipo que el TEXTO del comandante
          pide (60%) con la mejor densidad del pool en sus colores (40%).
          Dos comandantes con la misma identidad de color ya NO puntúan igual.
       c) `tribal_fit`: si el comandante referencia una tribu (Dragons,
          Elves…), cuenta cuántas criaturas de esa tribu tienes de verdad.
  FIX 7 (v6) — Diversidad también por arquetipo (máx 6 del mismo) además
       de por identidad de color (máx 4), para que el top no sea un
       monocultivo.

Métricas (weighted sum):
  Con datos EDHREC suficientes (>=5 high-synergy):
    40% fit · 10% tribal · 25% relevancia EDHREC · 20% bracket · 5% rank
  Comandante de nicho o sin EDHREC (p. ej. /api/analyze):
    55% fit · 10% tribal · 30% bracket · 5% rank
  Sin arquetipo detectable en absoluto:
    45% relevancia · 35% bracket · 20% rank  (o 75/25 si tampoco hay datos)
"""

from __future__ import annotations
import math
import re
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
    edhrec_sample:   int        # nº cartas high-synergy conocidas (0 = nicho/sin datos)
    fit_score:       float      # 0-100: encaje comandante↔pool (v6, específico del cmd)
    tribal_fit:      float      # 0-100: soporte tribal real en el pool (v6)
    total_score:     float

    @property
    def name(self) -> str:
        return self.commander["name"]

    @property
    def colors(self) -> str:
        return "".join(sorted(self.commander.get("color_identity", []))) or "C"

    def summary_line(self) -> str:
        """Línea resumen para el CLI (deck_forge.py analyze)."""
        arch = self.archetype.name if self.archetype else "—"
        return (
            f"{self.total_score:5.1f}  {self.name:<40.40} {self.colors:<5} "
            f"{arch:<28.28} fit {self.fit_score:5.1f}  "
            f"bracket {self.bracket_ceiling:.1f}"
        )


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


def _smooth_density(density: float) -> float:
    """
    v6: curva exponencial suave en lugar de cap duro a 100.

    El cap anterior (density/0.15*100, máx 100) hacía que CUALQUIER
    comandante con >=15% de densidad puntuara exactamente 100 → empates
    masivos donde la popularidad EDHREC decidía el orden real.

    Curva: 100·(1 − e^(−d/0.10))
      5% → 39 · 10% → 63 · 15% → 78 · 25% → 92 · 40% → 98
    Siempre creciente, nunca empata: más densidad = más score, sin techo.
    """
    return 100.0 * (1.0 - math.exp(-max(density, 0.0) / 0.10))


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
) -> tuple[Archetype | None, int, int, float, float]:
    """
    FIX 1: prueba TODOS los arquetipos y devuelve el que mejor encaja.

    v6: además devuelve `detected_density` — la densidad del arquetipo que
    el ORACLE TEXT del comandante pide. Es la señal específica del
    comandante: dos generales con la misma identidad de color difieren
    aquí, porque cada uno quiere construir algo distinto.

    Returns: (best_arch, raw, total, best_density, detected_density)
    """
    best_arch   = None
    best_raw    = 0
    best_total  = 0
    best_density = 0.0
    detected_density = 0.0

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
        if arch_key == detected_key:
            detected_density = density
        # Pequeño bonus al arquetipo detectado (oracle text es señal real)
        bonus = 0.02 if arch_key == detected_key else 0.0
        if density + bonus > best_density + 0.0:
            best_arch    = arch
            best_raw     = raw
            best_total   = total
            best_density = density + bonus

    return (best_arch, best_raw, best_total, best_density, detected_density)


# ── FIX 6c: Soporte tribal real ──────────────────────────────────────────

def _tribal_fit(commander: dict, pool: list[dict]) -> float:
    """
    Si el comandante referencia una tribu, mide cuántas criaturas de esa
    tribu tienes REALMENTE en su identidad de color.

    - Tribus que el oracle text menciona explícitamente ("other Elves",
      "Dragon you control") cuentan a peso completo.
    - Si solo comparten subtipo (sin mención en el texto) cuenta a medias —
      un Human Wizard genérico no es un comandante tribal.

    0-100: 15+ criaturas de la tribu en pool → 100 (a peso completo).
    """
    type_line = commander.get("type_line") or ""
    if "Creature" not in type_line or "—" not in type_line:
        return 0.0

    own_subtypes = {
        w.strip(",")
        for w in type_line.split("—", 1)[1].replace("//", " ").split()
        if w and w[0].isupper() and w not in ("Legendary", "Creature")
    }
    if not own_subtypes:
        return 0.0

    oracle = commander.get("oracle_text") or ""
    mentioned = {
        t for t in own_subtypes
        if re.search(rf"\b{re.escape(t)}s?\b", oracle)
    }
    targets = mentioned or own_subtypes
    weight = 1.0 if mentioned else 0.5

    deck_ci = set(commander.get("color_identity", []))
    matches = 0
    for c in pool:
        if c.get("is_land") or c["name"] == commander["name"]:
            continue
        ctl = c.get("type_line") or ""
        if "Creature" not in ctl or "—" not in ctl:
            continue
        if not fits_color_identity(c, deck_ci):
            continue
        c_subtypes = set(ctl.split("—", 1)[1].replace("//", " ").split())
        if c_subtypes & targets:
            matches += 1

    return min(matches / 15.0 * 100.0, 100.0) * weight


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


def _edhrec_relevance(commander_name: str, pool_names: set[str]) -> tuple[float, int]:
    """
    Relevancia EDHREC mejorada: usa SOLO las cartas HIGH-SYNERGY del comandante,
    no todas las recomendadas (que incluyen genéricas como Sol Ring para todos).

    Las cartas high-synergy son las que EDHREC marca como específicas de ESTE
    comandante (synergy score > 0.3) — cartas que se juegan MÁS con este
    comandante que con la media. Son el verdadero diferenciador.

    Score: % de esas cartas específicas que tienes en tu pool.

    Devuelve (score, sample_size). sample_size = nº de cartas high-synergy que
    EDHREC conoce para este comandante. Comandantes poco jugados (nicho) tienen
    sample_size bajo — el caller usa esto para NO penalizarlos por falta de
    datos de popularidad (ver score_commanders).
    """
    global _edhrec_cache
    try:
        if commander_name not in _edhrec_cache:
            from .edhrec_advisor import EDHRecAdvisor
            adv = EDHRecAdvisor(verbose=False)
            _edhrec_cache[commander_name] = adv.fetch_commander_data(commander_name)
        data = _edhrec_cache[commander_name]

        # Usar SOLO high_synergy — cartas específicas de este comandante
        high_synergy = data.get("high_synergy", {})
        if not high_synergy:
            # Fallback: all_cards filtradas por synergy > 0.25
            all_cards = data.get("all_cards", {})
            high_synergy = {
                n: v for n, v in all_cards.items()
                if v.get("synergy", 0) > 0.25
            }

        if not high_synergy:
            return (0.0, 0)

        hs_names = {n.lower() for n in high_synergy}
        pool_lower = {n.lower() for n in pool_names}
        overlap = len(pool_lower & hs_names)

        # Normalizar: 8+ cartas específicas en pool → score 100
        # (tener 8 cartas que EDHREC marca como únicas para este commander
        #  es excelente — demuestra que tu pool encaja con el plan del cmd)
        return (min(overlap / 8 * 100.0, 100.0), len(hs_names))
    except Exception:
        return (0.0, 0)


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
        # FIX 1 + FIX 6b: mejor arquetipo y densidad del arquetipo DETECTADO
        arch, raw, total, density, det_density = _best_archetype_score(cmd, pool)

        # FIX 6b — fit específico del comandante:
        # 60% lo que SU texto pide (det_density), 40% lo mejor que ofrece el
        # pool en sus colores. Si su texto no detecta arquetipo, solo cuenta
        # el pool con un descuento del 15% — un general cuyo plan coincide
        # con tu colección merece ir por delante de uno genérico.
        if det_density > 0:
            fit_score = _smooth_density(0.6 * det_density + 0.4 * density)
        else:
            fit_score = _smooth_density(density) * 0.85

        # FIX 6c — soporte tribal real
        tribal_sc = _tribal_fit(cmd, pool)

        # FIX 3: bracket granular
        bracket = _bracket_ceiling(cmd, pool)
        bracket_score = (bracket - 1.0) / 4.0 * 100.0

        # Popularidad (desempate suave — NO debe decidir el ranking)
        rank_sc = _normalize_rank(cmd.get("edhrec_rank"))

        # FIX 2: relevancia EDHREC (+ tamaño de muestra)
        rel_sc, rel_n = (0.0, 0)
        if use_edhrec:
            rel_sc, rel_n = _edhrec_relevance(cmd["name"], pool_names)

        # v5/v6 — "best for MY collection", no "most popular on EDHREC":
        # Si EDHREC apenas tiene datos de este comandante (poco jugado/nicho),
        # rel_sc no es fiable: redistribuimos su peso hacia fit/bracket,
        # que se calculan 100% sobre TU pool y no dependen de popularidad.
        SPARSE = 5  # < 5 cartas high-synergy conocidas = comandante de nicho

        if arch is None:
            # FIX 2: comandantes sin arquetipo ya no reciben 0 automático
            if rel_n >= SPARSE:
                total_score = (
                    rel_sc    * 0.45
                    + bracket_score * 0.35
                    + rank_sc       * 0.20
                )
            else:
                # Sin arquetipo Y sin datos EDHREC: solo poder bruto del pool
                total_score = (
                    bracket_score * 0.75
                    + rank_sc       * 0.25
                )
        else:
            if rel_n >= SPARSE:
                total_score = (
                    fit_score      * 0.40
                    + tribal_sc    * 0.10
                    + rel_sc       * 0.25
                    + bracket_score * 0.20
                    + rank_sc       * 0.05
                )
            else:
                # Comandante de nicho (o use_edhrec=False): tu pool es la
                # única señal — encaje específico + tribal + poder real.
                total_score = (
                    fit_score      * 0.55
                    + tribal_sc    * 0.10
                    + bracket_score * 0.30
                    + rank_sc       * 0.05
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
            edhrec_sample    = rel_n,
            fit_score        = round(fit_score, 1),
            tribal_fit       = round(tribal_sc, 1),
            total_score      = round(total_score, 1),
        ))

    scores.sort(key=lambda s: -s.total_score)

    # ── FIX 7: Diversidad por identidad de color Y por arquetipo ──
    # Si los 20 primeros son todos GU o todos "tokens", el usuario no ve
    # alternativas reales. Máx 4 por identidad exacta, máx 6 por arquetipo.
    diversity_filtered: list[CommanderScore] = []
    ci_count: dict[str, int] = {}
    arch_count: dict[str, int] = {}
    MAX_PER_CI   = 4
    MAX_PER_ARCH = 6

    for s in scores:
        ci = s.colors
        ak = s.archetype.key if s.archetype else "_none"
        if ci_count.get(ci, 0) < MAX_PER_CI and arch_count.get(ak, 0) < MAX_PER_ARCH:
            diversity_filtered.append(s)
            ci_count[ci] = ci_count.get(ci, 0) + 1
            arch_count[ak] = arch_count.get(ak, 0) + 1
        # Los que no entran por diversidad aún pueden aparecer
        # si hay huecos (el caller pide top=20 de ~50 slots posibles)

    # Si la diversidad redujo demasiado, completar con los siguientes en score
    if len(diversity_filtered) < len(scores):
        seen = {id(s) for s in diversity_filtered}
        remaining = [s for s in scores if id(s) not in seen]
        diversity_filtered.extend(remaining)

    return diversity_filtered
