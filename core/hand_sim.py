"""
hand_sim.py — Simulación de manos iniciales (v7).

Valida que el mazo ROBA jugable antes de entregarlo: simula miles de manos
de 7 con mulligan London simplificado y mide:

  - keepable_pct:   % de manos aceptables (2-5 tierras tras mulligans)
  - early_play_pct: % de manos con jugada de turno 1-2 (carta de CMC <= 2
                    casteable con las tierras de la mano)
  - avg_lands:      media de tierras en la mano final
  - avg_mulligans:  mulligans medios hasta mano aceptable (máx 2)

Determinista (seed fija) para que el mismo mazo dé siempre el mismo
resultado — los números son comparables entre builds.
"""

from __future__ import annotations
import random


def _is_land(card: dict) -> bool:
    return bool(card.get("is_land")) or "Land" in (card.get("type_line") or "")


def _keepable(hand: list[dict]) -> bool:
    lands = sum(1 for c in hand if _is_land(c))
    return 2 <= lands <= 5


def _has_early_play(hand: list[dict]) -> bool:
    """¿Hay una no-tierra de CMC<=2 cuyos colores cubren las tierras de la mano?"""
    land_colors: set[str] = set()
    for c in hand:
        if _is_land(c):
            for m in c.get("produced_mana") or []:
                if m in "WUBRGC":
                    land_colors.add(m)
            text = (c.get("oracle_text") or "").lower()
            if "any color" in text:
                land_colors |= set("WUBRG")
    for c in hand:
        if _is_land(c):
            continue
        if (c.get("cmc") or 0) > 2:
            continue
        cost = (c.get("mana_cost") or "").upper()
        needed = {col for col in "WUBRG" if f"{{{col}}}" in cost}
        if needed.issubset(land_colors) or not needed:
            return True
    return False


def simulate_hands(deck_cards: list[dict], n: int = 2000, seed: int = 7) -> dict:
    """
    deck_cards: las 99 cartas del mazo (sin comandante, básicas incluidas).
    Devuelve métricas agregadas de n manos simuladas.
    """
    rng = random.Random(seed)
    deck = list(deck_cards)

    keepable = 0
    early = 0
    total_lands = 0
    total_mulls = 0

    for _ in range(n):
        hand: list[dict] = []
        mulls = 0
        # London simplificado: hasta 2 mulligans, robas 7 y "devuelves" las
        # peores (aquí: simplemente re-robas; el bottom no afecta la métrica).
        for attempt in range(3):
            rng.shuffle(deck)
            hand = deck[:7]
            if _keepable(hand):
                break
            if attempt < 2:
                mulls += 1

        if _keepable(hand):
            keepable += 1
        if _has_early_play(hand):
            early += 1
        total_lands += sum(1 for c in hand if _is_land(c))
        total_mulls += mulls

    return {
        "n": n,
        "keepable_pct":   round(keepable / n * 100, 1),
        "early_play_pct": round(early / n * 100, 1),
        "avg_lands":      round(total_lands / n, 2),
        "avg_mulligans":  round(total_mulls / n, 2),
    }
