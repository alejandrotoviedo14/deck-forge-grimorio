"""
bracket.py — Estimación de bracket según reglas oficiales WotC.

NO es una réplica exacta del algoritmo de ManaBox/Moxfield (que es propietario
y opaco). Es una aproximación basada en las señales públicas que WotC describe
en sus brackets oficiales:

    Bracket 1 (Exhibition): mazos jank/temáticos, sin game changers, sin combos
    Bracket 2 (Core):       precon-level, sin game changers, sin combos infinitos
    Bracket 3 (Upgraded):   ≤3 game changers, sin combos en turnos tempranos
    Bracket 4 (Optimized):  game changers ilimitados, combos OK
    Bracket 5 (cEDH):       todo permitido

Este módulo computa un score numérico 1.0-5.0 basado en señales detectables
y lo redondea al bracket más cercano. Ajustar los pesos en BRACKET_WEIGHTS
según calibración con resultados reales de ManaBox.
"""

import json
from pathlib import Path
from dataclasses import dataclass, field

DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass
class BracketReport:
    """Resultado del cálculo de bracket con desglose."""
    score: float
    bracket: int
    game_changers: list[str] = field(default_factory=list)
    fast_mana: list[str] = field(default_factory=list)
    restrictive_tutors: list[str] = field(default_factory=list)
    mass_land_destruction: list[str] = field(default_factory=list)
    detected_combos: list[tuple[str, str]] = field(default_factory=list)
    avg_cmc: float = 0.0
    manabase_score: float = 0.0
    avg_edhrec_rank: float = 0.0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Bracket estimado: {self.bracket}  (score: {self.score:.2f}/5.0)",
            f"  Game changers: {len(self.game_changers)} {self.game_changers if self.game_changers else ''}",
            f"  Fast mana: {len(self.fast_mana)} {self.fast_mana if self.fast_mana else ''}",
            f"  Tutores restrictivos: {len(self.restrictive_tutors)} {self.restrictive_tutors if self.restrictive_tutors else ''}",
            f"  Mass Land Destruction: {len(self.mass_land_destruction)}",
            f"  Combos infinitos detectados: {len(self.detected_combos)}",
            f"  CMC promedio (no-tierra): {self.avg_cmc:.2f}",
            f"  Manabase score: {self.manabase_score:.2f}/10",
            f"  EDHREC rank promedio: {self.avg_edhrec_rank:.0f}",
        ]
        if self.notes:
            lines.append("  Notas:")
            for n in self.notes:
                lines.append(f"    - {n}")
        return "\n".join(lines)


def _load_reference() -> dict:
    with open(DATA_DIR / "game_changers.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _avg_cmc_non_land(decklist: list[dict]) -> float:
    non_land = [c for c in decklist if not c.get("is_land")]
    if not non_land:
        return 0.0
    return sum((c.get("cmc") or 0) for c in non_land) / len(non_land)


def _avg_edhrec_rank(decklist: list[dict]) -> float:
    """Promedio de rank EDHREC (cartas sin rank cuentan como 50000 = jank)."""
    if not decklist:
        return 50_000
    ranks = [c.get("edhrec_rank") or 50_000 for c in decklist]
    return sum(ranks) / len(ranks)


def _manabase_score(decklist: list[dict]) -> float:
    """
    Score 0-10 de calidad de manabase. Premia:
    - Tierras no-básicas que producen >1 color
    - Tierras que entran untapped (no tap-lands)
    - Fetchlands, shocks, originales
    Penaliza:
    - Manabase 100% básica
    - Demasiadas ETB-tapped
    """
    lands = [c for c in decklist if c.get("is_land")]
    if not lands:
        return 0.0

    score = 0.0
    nonbasic = [l for l in lands if l["name"] not in
                ("Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes")]

    # Bonus por nonbasic ratio
    nonbasic_ratio = len(nonbasic) / len(lands)
    score += nonbasic_ratio * 3.0  # max 3.0

    # Bonus por tierras que producen 2+ colores
    multicolor_count = 0
    untapped_count = 0
    for land in nonbasic:
        produced = land.get("produced_mana", []) or []
        wubrg_produced = [m for m in produced if m in ("W","U","B","R","G")]
        if len(wubrg_produced) >= 2:
            multicolor_count += 1
        text = (land.get("oracle_text") or "").lower()
        if "enters tapped" not in text and "enters the battlefield tapped" not in text:
            untapped_count += 1

    score += min(multicolor_count / max(len(nonbasic), 1), 1.0) * 4.0  # max 4.0
    score += (untapped_count / max(len(lands), 1)) * 3.0  # max 3.0

    return min(score, 10.0)


def estimate_bracket(decklist: list[dict]) -> BracketReport:
    """
    Estima el bracket del mazo. Devuelve BracketReport con desglose.
    """
    ref = _load_reference()
    names = {c["name"] for c in decklist}

    gc_set = set(ref["game_changers"])
    fm_set = set(ref["fast_mana"])
    tut_set = set(ref["restrictive_tutors"])
    mld_set = set(ref["mass_land_destruction"])

    found_gc = sorted(names & gc_set)
    found_fm = sorted(names & fm_set)
    found_tut = sorted(names & tut_set)
    found_mld = sorted(names & mld_set)

    # Combos infinitos: 2-card combos de la lista
    combos = []
    for combo in ref["two_card_infinite_combos"]:
        if all(c in names for c in combo):
            combos.append(tuple(combo))

    avg_cmc = _avg_cmc_non_land(decklist)
    avg_rank = _avg_edhrec_rank(decklist)
    mb_score = _manabase_score(decklist)

    notes = []

    # Score base = 1.0 (bracket 1 / exhibition)
    score = 1.0

    # === SUMAS POSITIVAS (suben bracket) ===

    # Game changers: cada uno empuja fuerte hacia 3-4
    if len(found_gc) >= 1:
        score += 1.5
        notes.append(f"+1.5 por game changers (mínimo bracket 3)")
    if len(found_gc) >= 4:
        score += 1.0  # 4+ = bracket 4
        notes.append("+1.0 extra por 4+ game changers (bracket 4)")

    # Fast mana
    if len(found_fm) >= 2:
        score += 0.8
        notes.append(f"+0.8 por fast mana ({len(found_fm)} piezas)")
    elif len(found_fm) == 1:
        score += 0.4
        notes.append("+0.4 por 1 pieza de fast mana (probablemente Sol Ring)")

    # Tutores restrictivos
    if len(found_tut) >= 1:
        score += 0.5
        notes.append(f"+0.5 por tutores restrictivos ({len(found_tut)})")
    if len(found_tut) >= 3:
        score += 0.5
        notes.append("+0.5 extra por 3+ tutores")

    # Combos infinitos
    if combos:
        score += 1.0
        notes.append(f"+1.0 por combos infinitos detectados ({len(combos)})")

    # MLD
    if found_mld:
        score += 0.5
        notes.append(f"+0.5 por mass land destruction")

    # Manabase de calidad
    if mb_score >= 7.0:
        score += 0.5
        notes.append(f"+0.5 por manabase fuerte ({mb_score:.1f}/10)")
    elif mb_score >= 5.0:
        score += 0.2
        notes.append(f"+0.2 por manabase decente ({mb_score:.1f}/10)")

    # CMC bajo (mazo rápido)
    if avg_cmc <= 2.5:
        score += 0.4
        notes.append(f"+0.4 por CMC bajo ({avg_cmc:.2f})")
    elif avg_cmc <= 3.0:
        score += 0.2
        notes.append(f"+0.2 por CMC moderado ({avg_cmc:.2f})")

    # EDHREC rank promedio bueno (cartas populares = staples)
    if avg_rank <= 3000:
        score += 0.3
        notes.append(f"+0.3 por cartas populares (rank promedio {avg_rank:.0f})")
    elif avg_rank <= 8000:
        score += 0.1

    # === RESTAS NEGATIVAS (bajan bracket) ===

    # CMC alto (mazo lento)
    if avg_cmc >= 4.0:
        score -= 0.3
        notes.append(f"-0.3 por CMC alto ({avg_cmc:.2f}, mazo lento)")

    # Manabase mala
    if mb_score < 3.0:
        score -= 0.3
        notes.append(f"-0.3 por manabase débil ({mb_score:.1f}/10)")

    # Si NO hay ningún staple universal (ni Sol Ring, ni Arcane Signet, ni
    # Command Tower), penalizar — esto pasa con pools sin compras
    universal_staples = {"Sol Ring", "Arcane Signet", "Command Tower",
                         "Mind Stone", "Fellwar Stone"}
    found_universal = names & universal_staples
    if not found_universal:
        score -= 0.4
        notes.append("-0.4 sin staples universales (Sol Ring, Signet, Command Tower)")

    # Clamp
    score = max(1.0, min(score, 5.0))

    # Bracket entero por redondeo
    if score < 1.5:
        bracket = 1
    elif score < 2.5:
        bracket = 2
    elif score < 3.5:
        bracket = 3
    elif score < 4.5:
        bracket = 4
    else:
        bracket = 5

    return BracketReport(
        score=score,
        bracket=bracket,
        game_changers=found_gc,
        fast_mana=found_fm,
        restrictive_tutors=found_tut,
        mass_land_destruction=found_mld,
        detected_combos=combos,
        avg_cmc=avg_cmc,
        manabase_score=mb_score,
        avg_edhrec_rank=avg_rank,
        notes=notes,
    )


def estimate_max_bracket_for_pool(pool: list[dict]) -> tuple[int, str]:
    """
    Dado un pool entero, estima cuál es el MÁXIMO bracket alcanzable
    sin compras. Sirve para avisar: 'tu pool soporta bracket X, no esperes Y'.

    Heurística: cuenta game changers, fast mana, tutores en el pool.
    """
    ref = _load_reference()
    names = {c["name"] for c in pool}
    gc = len(names & set(ref["game_changers"]))
    fm = len(names & set(ref["fast_mana"]))
    tut = len(names & set(ref["restrictive_tutors"]))

    if gc >= 8 and fm >= 5:
        return (5, "Pool con suficientes game changers y fast mana para cEDH")
    if gc >= 4 and fm >= 3:
        return (4, "Pool soporta bracket 4 optimized")
    if gc >= 1 or (fm >= 1 and tut >= 1):
        return (3, "Pool soporta bracket 3 upgraded")
    if fm >= 1 or tut >= 1:
        return (2, "Pool sólo soporta bracket 2 core (sin compras)")
    return (1, "Pool sólo soporta bracket 1 exhibition (sin compras de staples)")
