"""
synergy_detector.py — Detección automática de sinergias entre cartas.

Analiza el oracle text de cada carta del mazo para detectar:
- Qué cartas son "triggers" (se activan cuando ocurre algo)
- Qué cartas son "enablers" (provocan ese algo)
- Construye paquetes de sinergia: {tipo: [cartas que forman la sinergia]}

También enriquece cada carta con cuántas otras cartas del mazo activa.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field


# ── Definición de patrones de sinergia ────────────────────────────────────

@dataclass
class SynergyType:
    key:          str
    name_es:      str
    description:  str
    icon:         str
    # Texto en oracle que TIENE la carta que se activa (el payoff/trigger)
    trigger_texts: list[str]
    # Función que dice si una carta es enabler de este tipo
    is_enabler:   callable = field(default=lambda c: False)


SYNERGY_TYPES: list[SynergyType] = [
    SynergyType(
        key="spellslinger",
        name_es="Spellslinger",
        description="Se activan al lanzar instantes y conjuros",
        icon="✨",
        trigger_texts=[
            "whenever you cast an instant",
            "whenever you cast a sorcery",
            "whenever you cast a noncreature",
            "whenever you cast an instant or sorcery",
            "instant and sorcery spells you cast cost",
            "whenever a player casts a spell",
        ],
        is_enabler=lambda c: (
            "Instant" in (c.get("type_line") or "") or
            "Sorcery" in (c.get("type_line") or "")
        ),
    ),
    SynergyType(
        key="etb",
        name_es="ETB / Entrar al campo",
        description="Se activan cuando criaturas entran al campo",
        icon="🐾",
        trigger_texts=[
            "whenever a creature enters the battlefield under your control",
            "whenever another creature enters the battlefield",
            "whenever one or more creatures enter the battlefield",
            "whenever a creature enters",
        ],
        is_enabler=lambda c: (
            "Creature" in (c.get("type_line") or "") and
            not c.get("is_land", False)
        ),
    ),
    SynergyType(
        key="death",
        name_es="Muerte / Sacrificio",
        description="Se activan cuando criaturas mueren",
        icon="💀",
        trigger_texts=[
            "whenever a creature dies",
            "whenever another creature dies",
            "whenever a creature you control dies",
            "whenever a nontoken creature dies",
        ],
        is_enabler=lambda c: (
            "Creature" in (c.get("type_line") or "") or
            (re.search(r"sacrifice (a|another) creature", (c.get("oracle_text") or "").lower()) is not None)
        ),
    ),
    SynergyType(
        key="token",
        name_es="Tokens",
        description="Se activan con tokens o los generan masivamente",
        icon="🪙",
        trigger_texts=[
            "whenever a token enters the battlefield",
            "whenever one or more tokens",
            "for each token you control",
            "creature tokens you control",
        ],
        is_enabler=lambda c: (
            "create" in (c.get("oracle_text") or "").lower() and
            "token" in (c.get("oracle_text") or "").lower()
        ),
    ),
    SynergyType(
        key="draw",
        name_es="Robar cartas",
        description="Se activan cuando se roban cartas",
        icon="📚",
        trigger_texts=[
            "whenever you draw a card",
            "whenever a player draws a card",
            "whenever you draw your second card",
        ],
        is_enabler=lambda c: (
            re.search(r"draw (a|two|three|x) card", (c.get("oracle_text") or "").lower()) is not None
        ),
    ),
    SynergyType(
        key="counters",
        name_es="+1/+1 Contadores",
        description="Interactúan con contadores +1/+1",
        icon="⬆",
        trigger_texts=[
            "for each +1/+1 counter",
            "whenever you put one or more +1/+1 counters",
            "whenever a +1/+1 counter is placed",
            "proliferate",
        ],
        is_enabler=lambda c: (
            "+1/+1 counter" in (c.get("oracle_text") or "").lower()
        ),
    ),
    SynergyType(
        key="lifegain",
        name_es="Ganancia de vida",
        description="Se activan cuando se gana vida",
        icon="❤",
        trigger_texts=[
            "whenever you gain life",
            "whenever a player gains life",
            "each time you gain life",
        ],
        is_enabler=lambda c: (
            re.search(r"(gain|gains) \d+ life", (c.get("oracle_text") or "").lower()) is not None or
            "lifelink" in (c.get("oracle_text") or "").lower()
        ),
    ),
    SynergyType(
        key="landfall",
        name_es="Landfall",
        description="Se activan cuando entran tierras al campo",
        icon="🌿",
        trigger_texts=[
            "landfall —",
            "whenever a land enters the battlefield under your control",
        ],
        is_enabler=lambda c: (
            "Land" in (c.get("type_line") or "") or
            re.search(r"(put|search).*(land).*(battlefield)", (c.get("oracle_text") or "").lower()) is not None
        ),
    ),
    SynergyType(
        key="graveyard",
        name_es="Cementerio",
        description="Aprovechan cartas en el cementerio",
        icon="⚰",
        trigger_texts=[
            "from your graveyard",
            "graveyard to the battlefield",
            "cards in your graveyard",
            "whenever a card is put into your graveyard",
        ],
        is_enabler=lambda c: (
            re.search(r"(discard|put|mill).*(graveyard|top.*library)", (c.get("oracle_text") or "").lower()) is not None
        ),
    ),
    SynergyType(
        key="artifact",
        name_es="Artefactos",
        description="Sinergias con artefactos",
        icon="⚙",
        trigger_texts=[
            "whenever an artifact enters the battlefield",
            "for each artifact you control",
            "whenever you cast an artifact",
            "artifact you control",
        ],
        is_enabler=lambda c: (
            "Artifact" in (c.get("type_line") or "")
        ),
    ),
]


# ── Detección ─────────────────────────────────────────────────────────────

def _oracle(card: dict) -> str:
    return (card.get("oracle_text") or "").lower()


def _is_trigger(card: dict, syn: SynergyType) -> bool:
    """¿Esta carta tiene un trigger de este tipo de sinergia?"""
    text = _oracle(card)
    return any(t in text for t in syn.trigger_texts)


def _is_enabler(card: dict, syn: SynergyType) -> bool:
    """¿Esta carta activa/habilita triggers de este tipo?"""
    return syn.is_enabler(card)


def detect_synergies(deck_cards: list[dict]) -> list[dict]:
    """
    Detecta paquetes de sinergia en el mazo.

    `deck_cards` — lista de dicts de cartas (con oracle_text, type_line, etc.)

    Devuelve lista de paquetes:
    [
      {
        "type": "spellslinger",
        "name_es": "Spellslinger",
        "icon": "✨",
        "description": "...",
        "triggers": ["Veyran, Voice of Duality", ...],
        "enablers": ["Ponder", "Opt", ...],
        "strength": 8,  # triggers * enablers (cuanto mayor, mejor)
      }
    ]
    """
    packages = []

    for syn in SYNERGY_TYPES:
        triggers  = [c["name"] for c in deck_cards if _is_trigger(c, syn)]
        enablers  = [c["name"] for c in deck_cards if _is_enabler(c, syn)
                     and c["name"] not in triggers]  # no contar la misma carta en ambos

        if not triggers or not enablers:
            continue

        strength = len(triggers) * len(enablers)
        if strength < 2:   # mínimo 1 trigger y 2 enablers, o 2 triggers y 1 enabler
            continue

        packages.append({
            "type":        syn.key,
            "name_es":     syn.name_es,
            "icon":        syn.icon,
            "description": syn.description,
            "triggers":    triggers[:8],
            "enablers":    enablers[:8],
            "strength":    strength,
            "summary":     f"{len(triggers)} payoff{'s' if len(triggers)>1 else ''}, "
                           f"{len(enablers)} activador{'es' if len(enablers)>1 else ''}",
        })

    # Ordenar por fuerza descendente
    packages.sort(key=lambda p: -p["strength"])
    return packages[:8]   # máximo 8 paquetes relevantes


def build_card_synergy_map(
    deck_cards: list[dict],
    packages: list[dict],
) -> dict[str, list[str]]:
    """
    Construye un mapa {nombre_carta → lista de tipos de sinergia que activa}.
    Usado para enriquecer el tooltip: "Esta carta activa: Spellslinger, Tokens".
    """
    card_syns: dict[str, list[str]] = {}
    for p in packages:
        for name in p["triggers"] + p["enablers"]:
            if name not in card_syns:
                card_syns[name] = []
            if p["name_es"] not in card_syns[name]:
                card_syns[name].append(p["name_es"])
    return card_syns


def compute_deck_stats(deck_cards: list[dict]) -> dict:
    """
    Calcula estadísticas del mazo para el dashboard visual:
    - curva de maná (CMC distribution)
    - distribución de tipos
    - distribución de colores
    - conteo de categorías (ramp, draw, removal, etc.)
    """
    from . import classifier as cls
    from .pool import is_basic_land

    cmc_dist:  dict[str, int] = {"0":0,"1":0,"2":0,"3":0,"4":0,"5":0,"6":0,"7+":0}
    type_dist: dict[str, int] = {"Criatura":0,"Instante":0,"Conjuro":0,"Artefacto":0,
                                  "Encantamiento":0,"Planeswalker":0,"Tierra":0,"Otro":0}
    color_dist: dict[str, int] = {"W":0,"U":0,"B":0,"R":0,"G":0,"C":0}
    cat_dist:  dict[str, int] = {"Ramp":0,"Draw":0,"Removal":0,"Payoffs":0,
                                  "Tierras":0,"Sweepers":0,"Tutores":0}

    for card in deck_cards:
        if is_basic_land(card):
            continue

        # CMC
        cmc = int(card.get("cmc") or 0)
        key = str(min(cmc, 7)) if cmc < 7 else "7+"
        cmc_dist[key] = cmc_dist.get(key, 0) + 1

        # Tipo
        tl = card.get("type_line") or ""
        if   "Creature"     in tl: type_dist["Criatura"]     += 1
        elif "Instant"      in tl: type_dist["Instante"]     += 1
        elif "Sorcery"      in tl: type_dist["Conjuro"]      += 1
        elif "Artifact"     in tl: type_dist["Artefacto"]    += 1
        elif "Enchantment"  in tl: type_dist["Encantamiento"] += 1
        elif "Planeswalker" in tl: type_dist["Planeswalker"]  += 1
        elif "Land"         in tl: type_dist["Tierra"]        += 1
        else:                      type_dist["Otro"]          += 1

        # Color identity
        colors = card.get("color_identity") or card.get("colors") or []
        if not colors:
            color_dist["C"] += 1
        for c in colors:
            if c in color_dist:
                color_dist[c] += 1

        # Categorías funcionales
        roles = cls.classify(card)
        if "ramp"     in roles: cat_dist["Ramp"]    += 1
        if "draw"     in roles: cat_dist["Draw"]    += 1
        if "removal"  in roles: cat_dist["Removal"] += 1
        if "sweeper"  in roles: cat_dist["Sweepers"]+= 1
        if "tutor"    in roles: cat_dist["Tutores"] += 1
        if any(r.startswith("payoff") or r == "threat" for r in roles):
            cat_dist["Payoffs"] += 1

        if "Land" in tl:
            cat_dist["Tierras"] += 1

    return {
        "cmc_dist":   cmc_dist,
        "type_dist":  {k: v for k, v in type_dist.items() if v > 0},
        "color_dist": {k: v for k, v in color_dist.items() if v > 0},
        "cat_dist":   cat_dist,
        "total_non_land": sum(v for k,v in type_dist.items() if k != "Tierra"),
    }
