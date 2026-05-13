"""
upgrader.py — v2 con sugerencias de compra desde Scryfall.
"""

import time
from dataclasses import dataclass, field

from .bracket import estimate_bracket, _load_reference, BracketReport
from .pool import fits_color_identity, edhrec_rank, is_basic_land
from . import classifier as cls

SCRYFALL_SEARCH = "https://api.scryfall.com/cards/search"
RATE_LIMIT_S    = 0.1

_SCRYFALL_QUERIES: dict[str, str] = {
    "fast_mana":    'o:"add" (o:"{T}: add {C}{C}" OR o:"{T}: add two" OR t:artifact o:"add {") t:artifact cmc<=2',
    "tutor":        'o:"search your library for" o:"put it into your hand" -t:land -o:"basic land"',
    "game_changer": 'r:rare OR r:mythic',
    "manabase":     't:land -t:basic -o:"enters tapped" -o:"enters the battlefield tapped"',
    "cmc":          'cmc<=2 (o:"draw a card" OR o:"add {" OR o:"destroy target") -t:land',
}

_SCRYFALL_QUERIES_ARCHETYPE: dict[tuple[str,str], str] = {
    ("game_changer", "counters"):     '(o:"proliferate" OR o:"double the number" OR o:"+1/+1 counter") (r:rare OR r:mythic) cmc<=5',
    ("game_changer", "aristocrats"):  '(o:"whenever a creature dies" OR o:"sacrifice" OR o:"create") (r:rare OR r:mythic) cmc<=5',
    ("game_changer", "spellslinger"): '(o:"whenever you cast" OR o:"magecraft" OR o:"copy") (r:rare OR r:mythic) cmc<=5',
    ("game_changer", "equipment"):    '(t:equipment OR o:"equipped creature") (r:rare OR r:mythic) cmc<=4',
    ("game_changer", "tribal"):       '(o:"creatures you control get" OR o:"of that type") (r:rare OR r:mythic) cmc<=4',
    ("game_changer", "blink"):        '(o:"enters the battlefield" o:"exile" o:"return") (r:rare OR r:mythic) cmc<=5',
    ("game_changer", "landfall"):     '(o:"landfall" OR o:"whenever a land enters") (r:rare OR r:mythic) cmc<=5',
    ("game_changer", "lifegain"):     '(o:"whenever you gain life" OR o:"lifelink") (r:rare OR r:mythic) cmc<=4',
    ("game_changer", "reanimator"):   '(o:"from your graveyard" OR o:"graveyard to the battlefield") (r:rare OR r:mythic) cmc<=6',
}


@dataclass
class Gap:
    category: str
    description: str
    current: int | float
    needed: int | float
    delta: int | float


@dataclass
class SwapProposal:
    add: dict
    remove: dict
    reason: str

    @property
    def add_name(self) -> str:
        return self.add["name"]

    @property
    def remove_name(self) -> str:
        return self.remove["name"]


@dataclass
class PurchaseSuggestion:
    name: str
    cmc: float
    type_line: str
    price_eur: float
    edhrec_rank: int | None
    scryfall_url: str
    reason: str


@dataclass
class UpgradeReport:
    commander: str
    archetype: str
    current_bracket: int
    current_score: float
    target_bracket: int
    gaps: list[Gap]
    swaps: list[SwapProposal]
    purchases: list[PurchaseSuggestion] = field(default_factory=list)
    already_optimal: bool = False

    def print(self):
        print(f"\n{'='*65}")
        print(f"  UPGRADE REPORT: {self.commander}")
        print(f"  Arquetipo: {self.archetype}")
        print(f"{'='*65}")
        print(f"  Bracket actual : {self.current_bracket}  (score {self.current_score:.2f}/5.0)")
        print(f"  Bracket objetivo: {self.target_bracket}")

        if self.already_optimal:
            print(f"\n  El mazo ya esta en bracket {self.current_bracket}.")
            return

        if not self.gaps:
            print(f"\n  Sin gaps detectados.")
            return

        print(f"\n--- GAPS DETECTADOS ({len(self.gaps)}) ---")
        for gap in self.gaps:
            print(f"  - {gap.description}")

        if self.swaps:
            print(f"\n--- SWAPS DESDE TU POOL ({len(self.swaps)}) ---")
            print(f"  Cartas que ya tienes y subirian el bracket:\n")
            for i, swap in enumerate(self.swaps, 1):
                rank_add = swap.add.get("edhrec_rank") or "?"
                rank_rem = swap.remove.get("edhrec_rank") or "?"
                cmc_add  = int(swap.add.get("cmc") or 0)
                cmc_rem  = int(swap.remove.get("cmc") or 0)
                print(f"  [{i}] QUITA: {swap.remove_name:35s} (CMC {cmc_rem}, rank #{rank_rem})")
                print(f"       METE:  {swap.add_name:35s} (CMC {cmc_add}, rank #{rank_add})")
                print(f"       -> {swap.reason}")
                print()

        if self.purchases:
            print(f"\n--- SUGERENCIAS DE COMPRA ({len(self.purchases)}) ---")
            print(f"  Cartas de Scryfall que cubririan los gaps (<=EUR{self.purchases[0].price_eur if self.purchases else 10}, ordenadas por popularidad):\n")
            by_gap: dict[str, list[PurchaseSuggestion]] = {}
            for p in self.purchases:
                by_gap.setdefault(p.reason, []).append(p)
            for gap_label, suggestions in by_gap.items():
                print(f"  [{gap_label}]")
                for s in suggestions:
                    rank_str = f"rank #{s.edhrec_rank}" if s.edhrec_rank else "sin rank"
                    print(f"    {s.name:40s} CMC {int(s.cmc)}  EUR{s.price_eur:.2f}  {rank_str}")
                print()

        if not self.swaps and not self.purchases:
            print(f"\n  No se encontraron candidatos (ni en pool ni en Scryfall).")

        print(f"  La decision final es tuya - considera sinergia con el comandante.")


def _search_scryfall_purchases(
    gap: Gap,
    archetype_key: str,
    deck_ci: set[str],
    deck_names: set[str],
    max_price: float,
    max_suggestions: int,
    session,
) -> list[PurchaseSuggestion]:
    base_query = _SCRYFALL_QUERIES_ARCHETYPE.get(
        (gap.category, archetype_key),
        _SCRYFALL_QUERIES.get(gap.category, ""),
    )
    if not base_query:
        return []

    ci_str = "".join(sorted(deck_ci)).lower() if deck_ci else "c"
    full_query = f"{base_query} identity<={ci_str} eur<={max_price} legal:commander"

    try:
        resp = session.get(
            SCRYFALL_SEARCH,
            params={"q": full_query, "order": "edhrec", "dir": "asc"},
            timeout=10,
        )
        time.sleep(RATE_LIMIT_S)
        if resp.status_code != 200:
            print(f"  [Scryfall] {resp.status_code}: {resp.json().get('details','')[:80]}")
            print(f"  [Scryfall] query usada: {full_query}")
            return []
        data = resp.json()
        cards = data.get("data", [])
    except Exception as e:
        print(f"  [Scryfall] excepcion: {type(e).__name__}: {e}")
        return []

    suggestions: list[PurchaseSuggestion] = []
    for card in cards:
        name = card.get("name", "")
        if name in deck_names:
            continue
        price_raw = card.get("prices", {}).get("eur")
        if price_raw is None:
            continue
        try:
            price_eur = float(price_raw)
        except (ValueError, TypeError):
            continue
        if price_eur <= 0 or price_eur > max_price:
            continue

        suggestions.append(PurchaseSuggestion(
            name=name,
            cmc=card.get("cmc") or 0,
            type_line=card.get("type_line") or "",
            price_eur=price_eur,
            edhrec_rank=card.get("edhrec_rank"),
            scryfall_url=card.get("scryfall_uri") or "",
            reason=_gap_label(gap),
        ))
        if len(suggestions) >= max_suggestions:
            break

    return suggestions


def _gap_label(gap: Gap) -> str:
    return {
        "fast_mana":    "Fast Mana",
        "tutor":        "Tutor",
        "game_changer": "Game Changer",
        "manabase":     "Manabase",
        "cmc":          "CMC bajo",
    }.get(gap.category, gap.category)


def _detect_gaps(bracket_report: BracketReport, target_bracket: int) -> list[Gap]:
    gaps: list[Gap] = []
    if bracket_report.bracket >= target_bracket:
        return gaps
    thresholds = {
        2: {"fast_mana": 1, "tutor": 0, "game_changer": 0, "manabase": 3.0},
        3: {"fast_mana": 2, "tutor": 1, "game_changer": 1, "manabase": 4.0},
        4: {"fast_mana": 3, "tutor": 3, "game_changer": 4, "manabase": 6.0},
    }
    needed = thresholds.get(min(target_bracket, 4), thresholds[4])
    fm  = len(bracket_report.fast_mana)
    tut = len(bracket_report.restrictive_tutors)
    gc  = len(bracket_report.game_changers)
    mb  = bracket_report.manabase_score
    if fm  < needed["fast_mana"]:
        gaps.append(Gap("fast_mana", f"Fast mana: tienes {fm}, necesitas {needed['fast_mana']} para bracket {target_bracket}", fm, needed["fast_mana"], needed["fast_mana"] - fm))
    if tut < needed["tutor"]:
        gaps.append(Gap("tutor", f"Tutores restrictivos: tienes {tut}, necesitas {needed['tutor']} para bracket {target_bracket}", tut, needed["tutor"], needed["tutor"] - tut))
    if gc  < needed["game_changer"]:
        gaps.append(Gap("game_changer", f"Game changers: tienes {gc}, necesitas {needed['game_changer']} para bracket {target_bracket}", gc, needed["game_changer"], needed["game_changer"] - gc))
    if mb  < needed["manabase"]:
        gaps.append(Gap("manabase", f"Manabase debil: {mb:.1f}/10, recomendado {needed['manabase']:.0f}+ para bracket {target_bracket}", mb, needed["manabase"], needed["manabase"] - mb))
    if bracket_report.avg_cmc >= 4.0:
        gaps.append(Gap("cmc", f"CMC promedio alto: {bracket_report.avg_cmc:.2f} - baja el curve para mas consistencia", bracket_report.avg_cmc, 3.5, bracket_report.avg_cmc - 3.5))
    return gaps


def _candidates_for_gap(gap: Gap, pool: list[dict], deck_ci: set[str], deck_names: set[str], ref: dict) -> list[dict]:
    in_identity = [c for c in pool if fits_color_identity(c, deck_ci) and c["name"] not in deck_names and not is_basic_land(c)]
    if gap.category == "fast_mana":
        candidates = [c for c in in_identity if c["name"] in set(ref["fast_mana"])]
    elif gap.category == "tutor":
        candidates = [c for c in in_identity if c["name"] in set(ref["restrictive_tutors"])]
        if len(candidates) < 3:
            candidates += [c for c in in_identity if cls.is_tutor(c) and c not in candidates]
    elif gap.category == "game_changer":
        candidates = [c for c in in_identity if c["name"] in set(ref["game_changers"])]
    elif gap.category == "manabase":
        candidates = []
        for c in pool:
            if not c.get("is_land") or is_basic_land(c) or not fits_color_identity(c, deck_ci) or c["name"] in deck_names:
                continue
            produced = c.get("produced_mana", []) or []
            wubrg = [m for m in produced if m in ("W","U","B","R","G")]
            text = (c.get("oracle_text") or "").lower()
            if len(wubrg) >= 2 and "enters tapped" not in text and "enters the battlefield tapped" not in text:
                candidates.append(c)
    elif gap.category == "cmc":
        candidates = [c for c in in_identity if int(c.get("cmc") or 0) <= 2 and (cls.is_ramp(c) or cls.is_draw(c) or cls.is_removal(c))]
    else:
        candidates = []
    candidates.sort(key=lambda c: edhrec_rank(c))
    return candidates


def _worst_cards_in_deck(deck_cards: list[dict], deck_names: set[str], archetype_key: str, gap_category: str) -> list[dict]:
    candidates = [c for c in deck_cards if not is_basic_land(c) and not c.get("can_be_commander")]
    def prescindibility(card: dict) -> float:
        score = 0.0
        cm = int(card.get("cmc") or 0)
        rank = edhrec_rank(card)
        if cm >= 5 and not cls.is_threat(card): score += cm * 10
        score += rank / 10_000
        if not (cls.classify(card) & {"ramp","draw","removal","sweeper","counter","tutor","protection","threat"}): score += 50
        if gap_category == "manabase" and card.get("is_land"):
            text = (card.get("oracle_text") or "").lower()
            score += 200 if ("enters tapped" in text or "enters the battlefield tapped" in text) else -50
        if gap_category != "manabase" and card.get("is_land"): score -= 500
        return score
    candidates.sort(key=prescindibility, reverse=True)
    return candidates


def analyze_upgrade(
    deck_cards: list[dict],
    commander: dict,
    archetype_key: str,
    pool: list[dict],
    target_bracket: int | None = None,
    allow_purchases: bool = True,
    max_price: float = 10.0,
    min_suggestions: int = 5,
    max_suggestions: int = 15,
) -> UpgradeReport:
    ref = _load_reference()
    all_cards = [commander] + deck_cards
    bracket_report = estimate_bracket(all_cards)
    current_bracket = bracket_report.bracket

    if target_bracket is None:
        target_bracket = min(current_bracket + 1, 4)

    archetype_name = archetype_key.replace("_", " ").title()

    if current_bracket >= target_bracket:
        return UpgradeReport(commander=commander["name"], archetype=archetype_name,
            current_bracket=current_bracket, current_score=bracket_report.score,
            target_bracket=target_bracket, gaps=[], swaps=[], purchases=[], already_optimal=True)

    gaps = _detect_gaps(bracket_report, target_bracket)
    deck_ci    = set(commander.get("color_identity", []))
    deck_names = {c["name"] for c in all_cards}

    swaps: list[SwapProposal] = []
    gaps_without_pool: list[Gap] = []
    used_add:    set[str] = set()
    used_remove: set[str] = set()

    for gap in gaps:
        candidates = _candidates_for_gap(gap, pool, deck_ci, deck_names, ref)
        removables = _worst_cards_in_deck(deck_cards, deck_names, archetype_key, gap.category)
        if not candidates:
            gaps_without_pool.append(gap)
            continue
        n = max(1, min(int(gap.delta), 3, len(candidates), len(removables)))
        added = 0
        for _ in range(n):
            add_card    = next((c for c in candidates if c["name"] not in used_add), None)
            remove_card = next((c for c in removables if c["name"] not in used_remove), None)
            if not add_card or not remove_card: break
            swaps.append(SwapProposal(add=add_card, remove=remove_card, reason=_swap_reason(gap, add_card, remove_card)))
            used_add.add(add_card["name"]); used_remove.add(remove_card["name"])
            added += 1
        if added == 0:
            gaps_without_pool.append(gap)

    purchases: list[PurchaseSuggestion] = []
    if allow_purchases and gaps_without_pool:
        try:
            import requests as req
            session = req.Session()
            session.headers.update({"User-Agent": "DeckForgeUpgrader/2.0", "Accept": "application/json"})
            print(f"\n  Consultando Scryfall para sugerencias de compra...", flush=True)
            for gap in gaps_without_pool:
                suggestions = _search_scryfall_purchases(gap, archetype_key, deck_ci, deck_names, max_price, max_suggestions, session)
                if len(suggestions) < min_suggestions:
                    existing_names = deck_names | {s.name for s in suggestions}
                    extra = _search_scryfall_purchases(gap, "", deck_ci, existing_names, max_price, max_suggestions - len(suggestions), session)
                    suggestions += extra
                purchases.extend(suggestions[:max_suggestions])
        except ImportError:
            print("  [Scryfall] requests no disponible en este entorno.")
        except Exception as e:
            print(f"  [Scryfall] error inesperado: {type(e).__name__}: {e}")

    return UpgradeReport(commander=commander["name"], archetype=archetype_name,
        current_bracket=current_bracket, current_score=bracket_report.score,
        target_bracket=target_bracket, gaps=gaps, swaps=swaps, purchases=purchases, already_optimal=False)


def _swap_reason(gap: Gap, add: dict, remove: dict) -> str:
    reasons = {
        "fast_mana":    "Anade fast mana (bracket 2+ requiere al menos 1 pieza).",
        "tutor":        "Anade tutor restrictivo - sube potencia sin game changers.",
        "game_changer": "Game changer: sube el techo de bracket directamente.",
        "manabase":     "Mejora la manabase: entra untapped y produce 2+ colores.",
        "cmc":          "Baja el CMC promedio - mas consistencia.",
    }
    base = reasons.get(gap.category, "Mejora general del mazo.")
    remove_cmc = int(remove.get("cmc") or 0)
    if remove_cmc >= 5 and gap.category != "manabase":
        base += f" ({remove['name']} CMC {remove_cmc} aporta poco para su coste.)"
    return base
