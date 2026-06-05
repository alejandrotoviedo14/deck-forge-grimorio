"""
price_advisor.py — Cálculo de precios de mazos usando datos de Scryfall.

Los precios ya están en el bulk data de Scryfall (campo `prices`).
Este módulo los extrae y calcula:
  - Precio total del mazo (€ y $)
  - Carta más cara
  - Distribución de precio
  - Filtro de presupuesto para el builder
"""

from __future__ import annotations


# ── Extracción de precio de una carta ──────────────────────────────────────

def card_price_eur(card: dict) -> float:
    """Precio en euros de una carta. 0.0 si no disponible."""
    prices = card.get("prices") or {}
    v = prices.get("eur") or prices.get("eur_foil")
    try:
        return float(v) if v else 0.0
    except (TypeError, ValueError):
        return 0.0


def card_price_usd(card: dict) -> float:
    """Precio en dólares de una carta. 0.0 si no disponible."""
    prices = card.get("prices") or {}
    v = prices.get("usd") or prices.get("usd_foil")
    try:
        return float(v) if v else 0.0
    except (TypeError, ValueError):
        return 0.0


# ── Análisis de precio de un mazo ─────────────────────────────────────────

def calculate_deck_price(cards: list[dict]) -> dict:
    """
    Calcula estadísticas de precio para una lista de cartas.
    `cards` es la lista de dicts enriquecidos de Scryfall.

    Devuelve:
      total_eur, total_usd,
      most_expensive (card dict con precio),
      price_buckets (distribución por rangos),
      cards_with_price (cuántas tienen precio conocido)
    """
    total_eur = 0.0
    total_usd = 0.0
    cards_with_price = 0

    priced: list[tuple[dict, float]] = []

    for card in cards:
        eur = card_price_eur(card)
        usd = card_price_usd(card)
        if eur > 0 or usd > 0:
            cards_with_price += 1
        total_eur += eur
        total_usd += usd
        priced.append((card, eur))

    # Carta más cara
    priced.sort(key=lambda x: -x[1])
    most_expensive = None
    if priced and priced[0][1] > 0:
        c, p = priced[0]
        most_expensive = {
            "name":  c.get("name", ""),
            "price_eur": round(p, 2),
            "price_usd": round(card_price_usd(c), 2),
        }

    # Distribución por rangos de precio
    buckets = {"<0.5": 0, "0.5-2": 0, "2-10": 0, "10-30": 0, ">30": 0}
    for _, p in priced:
        if   p < 0.5:   buckets["<0.5"]   += 1
        elif p < 2:     buckets["0.5-2"]  += 1
        elif p < 10:    buckets["2-10"]   += 1
        elif p < 30:    buckets["10-30"]  += 1
        else:           buckets[">30"]    += 1

    # Top 10 cartas más caras
    top_10 = [
        {"name": c.get("name",""), "price_eur": round(p,2)}
        for c, p in priced[:10] if p > 0
    ]

    return {
        "total_eur":          round(total_eur, 2),
        "total_usd":          round(total_usd, 2),
        "cards_with_price":   cards_with_price,
        "most_expensive":     most_expensive,
        "price_buckets":      buckets,
        "top_10_expensive":   top_10,
    }


# ── Filtro de presupuesto para el builder ──────────────────────────────────

def filter_by_budget(
    cards: list[dict],
    max_price_eur: float | None = None,
) -> list[dict]:
    """
    Elimina las cartas que superan el presupuesto por carta.
    (El filtro de presupuesto total requiere lógica más compleja
    en el builder — esto es el filtro simple por carta individual.)
    """
    if max_price_eur is None:
        return cards
    return [c for c in cards if card_price_eur(c) <= max_price_eur]


def price_label(eur: float) -> str:
    """Etiqueta amigable para el precio."""
    if eur == 0:   return "—"
    if eur < 0.5:  return f"€{eur:.2f}"
    if eur < 2:    return f"€{eur:.2f}"
    if eur < 10:   return f"€{eur:.1f}"
    return f"€{eur:.0f}"
