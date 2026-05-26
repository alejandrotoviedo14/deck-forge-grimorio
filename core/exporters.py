"""
exporters.py — v2 con HTML rico multi-mazo.

Formatos:
- HTML multi-mazo standalone con sidebar, imágenes Scryfall, roles,
  wincons, arquetipos, bracket detail, y sección de upgrade integrada.
  Se regenera completo en cada build desde decks_index.json.
- ManaBox CSV (15 columnas, formato exacto)
- Moxfield txt (lista plana con // categorías)
"""

import csv
import io
import json
from pathlib import Path

from .builder import BuiltDeck
from .bracket import BracketReport


# === MOXFIELD TXT ==========================================================

def to_moxfield_txt(deck: BuiltDeck, basics_data: dict[str, dict] | None = None) -> str:
    lines = ["// Commander", f"1 {deck.commander['name']}", ""]
    for cat, cards in deck.categorized().items():
        lines.append(f"// {cat}")
        for dc in cards:
            lines.append(f"1 {dc.name}")
        lines.append("")
    if deck.needed_basics > 0:
        lines.append("// Basic Lands")
        colors = list(deck.colors)
        split = deck.needed_basics // len(colors)
        rem = deck.needed_basics - split * len(colors)
        basic_map = {"W":"Plains","U":"Island","B":"Swamp","R":"Mountain","G":"Forest"}
        for i, c in enumerate(colors):
            n = split + (1 if i < rem else 0)
            if n > 0:
                lines.append(f"{n} {basic_map[c]}")
    return "\n".join(lines)


# === MANABOX CSV ===========================================================

MANABOX_HEADER = [
    "Name", "Set code", "Set name", "Collector number", "Foil", "Rarity",
    "Quantity", "ManaBox ID", "Scryfall ID", "Purchase price", "Misprint",
    "Altered", "Condition", "Language", "Purchase price currency",
]

def to_manabox_csv(deck: BuiltDeck, raw_csv_path, basics_csv_data=None) -> str:
    raw_data: dict[str, dict] = {}
    with open(raw_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["Name"]
            if name not in raw_data:
                raw_data[name] = row

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(MANABOX_HEADER)

    def add_row(name: str, qty: int):
        row = raw_data.get(name) or (basics_csv_data or {}).get(name)
        if not row:
            return
        writer.writerow([
            row.get("Name", name), row.get("Set code", ""), row.get("Set name", ""),
            row.get("Collector number", ""), row.get("Foil", "normal"), row.get("Rarity", ""),
            qty, row.get("ManaBox ID", ""), row.get("Scryfall ID", ""),
            "", "false", "false", row.get("Condition", "near_mint"), row.get("Language", "en"), "EUR",
        ])

    add_row(deck.commander["name"], 1)
    for dc in deck.cards:
        add_row(dc.name, 1)
    if deck.needed_basics > 0:
        colors = list(deck.colors)
        split = deck.needed_basics // len(colors)
        rem = deck.needed_basics - split * len(colors)
        basic_map = {"W":"Plains","U":"Island","B":"Swamp","R":"Mountain","G":"Forest"}
        for i, c in enumerate(colors):
            n = split + (1 if i < rem else 0)
            if n > 0:
                add_row(basic_map[c], n)
    return out.getvalue()


# === HTML MULTI-MAZO =======================================================

# Color identity → CSS class
COLOR_CLASS = {"W": "w", "U": "u", "B": "b", "R": "r", "G": "g", "C": "c"}

# Archetype descriptions for wincon section
ARCHETYPE_WINCONS = {
    "counters":    ["Simic Ascendancy a 20 contadores", "Alpha strike con criatura monstruosa", "Proliferate loop con engine de draw"],
    "equipment":   ["21 puntos de daño de comandante (voltron)", "One-shot con evasión + Swords", "Stax con equipos de protección"],
    "aristocrats": ["Drain incremental con Blood Artist / Zulaport", "Loop de sacrifice infinito", "Token flood + sac outlet"],
    "spellslinger":["Storm-lite con Grapeshot o Brain Freeze", "Burn incremental con Guttersnipe", "Niv-Mizzet loop draw-damage"],
    "tribal":      ["Board wide con Coat of Arms", "Shared Animosity alpha strike", "Lord stack + evasión tribal"],
    "blink":       ["ETB loop infinito con Panharmonicon", "Value acumulado con Conjurer's Closet", "ETB combo 2 cartas"],
    "landfall":    ["Scute Swarm tokens exponencial", "Avenger of Zendikar + ramp", "Valakut / Scapeshift combo"],
    "lifegain":    ["Aetherflux Reservoir oneshot", "Sanguine Bond + Exquisite Blood loop", "Felidar Sovereign victory"],
    "reanimator":  ["Criatura 8+ en turno 3-4", "Sheoldred / Grave Titan loop", "Entomb + Reanimate turn 1"],
}

ARCHETYPE_DESCRIPTIONS = {
    "counters":    "Acumulamos +1/+1 counters. El comandante los duplica o prolifera.",
    "equipment":   "Equipamos al comandante y lo volvemos imparable. 21 daño de comandante.",
    "aristocrats": "Tokens sacrificables, drain incremental, engine de cementerio.",
    "spellslinger":"Instants y sorceries. Cada hechizo dispara payoffs. Storm-lite.",
    "tribal":      "Un tipo de criatura amplificado. Lords + anthems + sinergia de tipo.",
    "blink":       "Exiliamos y retornamos criaturas para repetir sus ETBs infinitamente.",
    "landfall":    "Cada tierra dispara efectos. Ramp agresivo para dominar el tablero.",
    "lifegain":    "La vida como recurso. Payoffs exponenciales por cada punto ganado.",
    "reanimator":  "Criaturas enormes desde el cementerio a coste cero de maná.",
}

ROLE_ICONS = {
    "ramp": "⬆", "draw": "📖", "removal": "🗑", "sweeper": "💥",
    "counter": "🛡", "recursion": "♻", "tutor": "🔍", "protection": "🔒",
    "threat": "⚔", "equipment": "🗡", "sac_outlet": "💀",
    "payoff_counters": "⬛", "payoff_tokens": "👥", "payoff_death": "☠",
    "payoff_drain": "🩸", "payoff_spellslinger": "✨", "payoff_tribal": "🦁",
    "payoff_blink": "👁", "payoff_landfall": "🌿", "payoff_lifegain": "❤",
    "payoff_reanimator": "💀",
}

BRACKET_LABELS = {1: "Exhibition", 2: "Core", 3: "Upgraded", 4: "Optimized", 5: "cEDH"}


def _scryfall_img(scryfall_id: str) -> str:
    if not scryfall_id or len(scryfall_id) < 2:
        return ""
    return f"https://cards.scryfall.io/normal/front/{scryfall_id[0]}/{scryfall_id[1]}/{scryfall_id}.jpg"


def _color_pips(colors: str) -> str:
    pip_map = {"W":"☀","U":"💧","B":"💀","R":"🔥","G":"🌿"}
    return "".join(pip_map.get(c, c) for c in colors)


def _build_deck_data_json(deck: BuiltDeck, bracket: BracketReport) -> dict:
    """Convierte un BuiltDeck en dict JSON serializable para el HTML."""
    from . import classifier as cls

    def card_record(card: dict, role: str = "", justification: str = "") -> dict:
        scryfall_id = card.get("scryfall_id") or card.get("id") or ""
        roles = list(cls.classify(card))
        return {
            "name": card.get("name", ""),
            "scryfall_id": scryfall_id,
            "img": _scryfall_img(scryfall_id),
            "cmc": int(card.get("cmc") or 0),
            "type": card.get("type_line", ""),
            "oracle": (card.get("oracle_text") or "")[:200],
            "colors": card.get("color_identity", []),
            "rank": card.get("edhrec_rank"),
            "role": role,
            "justification": justification,
            "roles": roles,
            "role_icons": [ROLE_ICONS.get(r, "") for r in roles if ROLE_ICONS.get(r)],
            "is_land": card.get("is_land", False),
            "is_creature": card.get("is_creature", False),
            "rarity": card.get("rarity", ""),
        }

    categories = {}
    cmd_record = card_record(deck.commander, "Commander", "El motor del mazo.")
    categories["Comandante"] = [cmd_record]

    for cat, cards in deck.categorized().items():
        categories[cat] = [card_record(dc.card, dc.role, dc.justification) for dc in cards]

    archetype_key = deck.archetype.key
    return {
        "commander": deck.commander["name"],
        "commander_img": _scryfall_img(deck.commander.get("scryfall_id") or ""),
        "archetype_key": archetype_key,
        "archetype_name": deck.archetype.name,
        "archetype_desc": ARCHETYPE_DESCRIPTIONS.get(archetype_key, deck.archetype.description),
        "wincons": ARCHETYPE_WINCONS.get(archetype_key, []),
        "colors": deck.colors,
        "color_pips": _color_pips(deck.colors),
        "bracket": bracket.bracket,
        "bracket_label": BRACKET_LABELS.get(bracket.bracket, ""),
        "bracket_score": round(bracket.score, 2),
        "bracket_notes": bracket.notes,
        "game_changers": bracket.game_changers,
        "fast_mana": bracket.fast_mana,
        "tutors": bracket.restrictive_tutors,
        "combos": [list(c) for c in bracket.detected_combos],
        "avg_cmc": round(bracket.avg_cmc, 2),
        "manabase_score": round(bracket.manabase_score, 2),
        "card_count": deck.card_count + deck.needed_basics,
        "needed_basics": deck.needed_basics,
        "categories": categories,
        "gameplay_guide": getattr(deck, "gameplay_guide", ""),
    }


def _render_html(all_decks_data: dict) -> str:
    json_str = json.dumps(all_decks_data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Deck Forge — Grimorio</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;900&family=Crimson+Pro:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:       #0d0d0f;
  --bg2:      #13131a;
  --bg3:      #1a1a24;
  --border:   #2a2a3a;
  --accent:   #c9a84c;
  --accent2:  #8b6914;
  --text:     #e8e4d8;
  --text2:    #9990a0;
  --text3:    #5a5468;
  --w: #f9f6f0; --u: #4a90d9; --b: #9b59b6; --r: #e74c3c; --g: #27ae60; --c: #95a5a6;
  --bracket1: #5a5468; --bracket2: #27ae60; --bracket3: #f39c12; --bracket4: #e74c3c; --bracket5: #8b0000;
  --sidebar: 280px;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: 'Crimson Pro', Georgia, serif;
  font-size: 16px;
  min-height: 100vh;
  display: flex;
}}

/* SIDEBAR */
#sidebar {{
  width: var(--sidebar);
  min-height: 100vh;
  background: var(--bg2);
  border-right: 1px solid var(--border);
  position: fixed;
  top: 0; left: 0;
  overflow-y: auto;
  z-index: 100;
  display: flex;
  flex-direction: column;
}}
#sidebar-header {{
  padding: 24px 20px 16px;
  border-bottom: 1px solid var(--border);
}}
#sidebar-header h1 {{
  font-family: 'Cinzel', serif;
  font-size: 18px;
  font-weight: 900;
  color: var(--accent);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}}
#sidebar-header p {{
  font-size: 12px;
  color: var(--text3);
  margin-top: 4px;
  font-style: italic;
}}
#deck-list {{
  flex: 1;
  padding: 12px 0;
}}
.deck-nav-item {{
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: all 0.2s;
  text-decoration: none;
  color: var(--text2);
}}
.deck-nav-item:hover {{ background: var(--bg3); color: var(--text); }}
.deck-nav-item.active {{
  border-left-color: var(--accent);
  background: var(--bg3);
  color: var(--accent);
}}
.deck-nav-commander-img {{
  width: 36px; height: 36px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--border);
  flex-shrink: 0;
}}
.deck-nav-info {{ min-width: 0; }}
.deck-nav-name {{
  font-family: 'Cinzel', serif;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.deck-nav-meta {{
  font-size: 11px;
  color: var(--text3);
  margin-top: 2px;
}}
.bracket-dot {{
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-left: auto;
}}

/* MAIN */
#main {{
  margin-left: var(--sidebar);
  flex: 1;
  min-width: 0;
}}

/* DECK PANEL */
.deck-panel {{
  display: none;
  padding: 0;
}}
.deck-panel.active {{ display: block; }}

/* HERO */
.deck-hero {{
  position: relative;
  height: 320px;
  overflow: hidden;
  background: var(--bg2);
}}
.deck-hero-bg {{
  position: absolute; inset: 0;
  background-size: cover;
  background-position: center 20%;
  filter: blur(8px) brightness(0.3) saturate(1.5);
  transform: scale(1.05);
}}
.deck-hero-content {{
  position: relative;
  z-index: 2;
  display: flex;
  align-items: flex-end;
  gap: 32px;
  padding: 32px 48px;
  height: 100%;
}}
.commander-portrait {{
  width: 160px;
  height: 220px;
  object-fit: cover;
  object-position: top;
  border-radius: 12px;
  border: 2px solid var(--accent2);
  box-shadow: 0 8px 32px rgba(0,0,0,0.8);
  flex-shrink: 0;
}}
.deck-hero-text {{ padding-bottom: 8px; }}
.deck-hero-text h2 {{
  font-family: 'Cinzel', serif;
  font-size: 32px;
  font-weight: 900;
  color: var(--text);
  line-height: 1.1;
  text-shadow: 0 2px 8px rgba(0,0,0,0.8);
}}
.deck-color-pips {{
  font-size: 20px;
  margin: 6px 0;
  letter-spacing: 2px;
}}
.deck-archetype-badge {{
  display: inline-block;
  background: rgba(201,168,76,0.15);
  border: 1px solid var(--accent2);
  color: var(--accent);
  font-family: 'Cinzel', serif;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 3px 10px;
  border-radius: 3px;
  margin-top: 4px;
}}
.bracket-badge {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(0,0,0,0.4);
  border: 1px solid var(--border);
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  margin-top: 8px;
  margin-left: 8px;
}}
.bracket-badge .b-dot {{
  width: 8px; height: 8px; border-radius: 50%;
}}

/* CONTENT SECTIONS */
.deck-content {{ padding: 0 48px 64px; }}

.section {{
  margin-top: 40px;
}}
.section-title {{
  font-family: 'Cinzel', serif;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--accent);
  border-bottom: 1px solid var(--border);
  padding-bottom: 8px;
  margin-bottom: 20px;
}}

/* STATS ROW */
.stats-row {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}}
.stat-card {{
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  text-align: center;
}}
.stat-value {{
  font-family: 'Cinzel', serif;
  font-size: 22px;
  font-weight: 900;
  color: var(--accent);
}}
.stat-label {{
  font-size: 11px;
  color: var(--text3);
  margin-top: 2px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}}

/* ARCHETYPE + WINCONS */
.archetype-box {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}}
.info-box {{
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
}}
.info-box h4 {{
  font-family: 'Cinzel', serif;
  font-size: 12px;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 10px;
}}
.info-box p {{
  font-size: 14px;
  color: var(--text2);
  line-height: 1.6;
  font-style: italic;
}}
.wincon-list {{ list-style: none; }}
.wincon-list li {{
  font-size: 14px;
  color: var(--text2);
  padding: 5px 0;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
}}
.wincon-list li:last-child {{ border-bottom: none; }}
.wincon-list li::before {{
  content: "⚡";
  font-size: 11px;
  color: var(--accent2);
}}

/* BRACKET DETAIL */
.bracket-detail {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}}
.bracket-item {{
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px 16px;
  font-size: 13px;
}}
.bracket-item-label {{
  font-size: 11px;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 4px;
}}
.bracket-item-value {{ color: var(--text); font-weight: 600; }}
.bracket-notes {{
  margin-top: 12px;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 14px 16px;
}}
.bracket-note {{
  font-size: 12px;
  color: var(--text3);
  padding: 3px 0;
  font-style: italic;
}}

/* CARD GRID */
.category-section {{ margin-bottom: 32px; }}
.category-title {{
  font-family: 'Cinzel', serif;
  font-size: 12px;
  color: var(--text2);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}}
.category-count {{
  background: var(--bg3);
  border: 1px solid var(--border);
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  color: var(--text3);
}}
.card-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}}
.card-item {{
  position: relative;
  cursor: pointer;
}}
.card-item img {{
  width: 100%;
  border-radius: 8px;
  display: block;
  border: 1px solid var(--border);
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
}}
.card-item:hover img {{
  transform: translateY(-4px) scale(1.03);
  border-color: var(--accent2);
  box-shadow: 0 8px 24px rgba(0,0,0,0.6);
  z-index: 10;
}}

/* CARD ZOOM MODAL */
.card-modal {{
  display: none;
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(0,0,0,0.85);
  align-items: center;
  justify-content: center;
  animation: modalFadeIn 0.2s ease-out;
}}
.card-modal.visible {{ display: flex; }}
.card-modal-img {{
  max-width: 90vw;
  max-height: 90vh;
  border-radius: 16px;
  box-shadow: 0 16px 64px rgba(0,0,0,0.9);
  animation: modalZoomIn 0.25s cubic-bezier(0.2, 0.9, 0.3, 1.2);
}}
.card-modal-close {{
  position: absolute;
  top: 24px;
  right: 24px;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: rgba(0,0,0,0.6);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 22px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s, transform 0.2s;
}}
.card-modal-close:hover {{
  background: rgba(231, 76, 60, 0.8);
  transform: scale(1.1);
}}
@keyframes modalFadeIn {{
  from {{ opacity: 0; }}
  to   {{ opacity: 1; }}
}}
@keyframes modalZoomIn {{
  from {{ transform: scale(0.4); opacity: 0; }}
  to   {{ transform: scale(1);   opacity: 1; }}
}}

/* VIEW CONTROLS (toggle grid/list + sort) */
.view-controls {{
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 16px;
  padding: 10px 14px;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 8px;
}}
.view-controls-label {{
  font-size: 11px;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  white-space: nowrap;
}}
.view-toggle {{
  display: flex;
  background: var(--bg3);
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--border);
  flex-shrink: 0;
}}
.view-toggle button {{
  background: transparent;
  color: var(--text2);
  border: none;
  padding: 8px 14px;
  font-size: 13px;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.2s, color 0.2s;
  min-width: 60px;
  -webkit-tap-highlight-color: transparent;
  touch-action: manipulation;
}}
.view-toggle button.active {{
  background: var(--accent2);
  color: var(--bg);
  font-weight: 600;
}}
.view-toggle button:hover:not(.active),
.view-toggle button:active:not(.active) {{
  background: var(--border);
  color: var(--text);
}}
.sort-select {{
  background: var(--bg3);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  flex: 1;
  min-width: 120px;
  -webkit-appearance: none;
  appearance: none;
}}
.sort-select:focus {{ outline: none; border-color: var(--accent2); }}
@media (max-width: 768px) {{
  .view-controls {{
    gap: 6px;
    padding: 8px 10px;
  }}
  .view-controls-label {{ display: none; }}
  .view-toggle button {{ padding: 10px 16px; font-size: 14px; }}
  .sort-select {{ font-size: 14px; padding: 10px 8px; }}
}}

/* LIST VIEW */
.card-list {{
  display: none;
  flex-direction: column;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}}
.category-section.list-mode .card-grid {{ display: none; }}
.category-section.list-mode .card-list {{ display: flex; }}

.card-list-row {{
  display: grid;
  grid-template-columns: 40px 1fr 80px 60px 80px;
  align-items: center;
  gap: 12px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  cursor: zoom-in;
  transition: background 0.15s;
}}
.card-list-row:last-child {{ border-bottom: none; }}
.card-list-row:hover {{ background: var(--bg3); }}
.card-list-thumb {{
  width: 30px;
  height: 42px;
  border-radius: 3px;
  object-fit: cover;
  object-position: top;
  border: 1px solid var(--border);
}}
.card-list-name {{
  font-size: 13px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}
.card-list-type {{
  font-size: 11px;
  color: var(--text3);
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}
.card-list-cmc {{
  font-size: 12px;
  color: var(--text2);
  text-align: center;
  font-weight: 600;
}}
.card-list-roles {{
  font-size: 12px;
  text-align: right;
  letter-spacing: 2px;
}}
@media (max-width: 768px) {{
  .card-list-row {{ grid-template-columns: 30px 1fr 40px; gap: 8px; padding: 6px 10px; }}
  .card-list-type, .card-list-roles {{ display: none; }}
}}

/* GAMEPLAY GUIDE */
.gameplay-guide {{
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px 24px;
  line-height: 1.7;
}}
.gameplay-guide h4 {{
  font-family: 'Cinzel', serif;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--accent2);
  margin: 16px 0 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border);
}}
.gameplay-guide h4:first-child {{ margin-top: 0; }}
.gameplay-guide p {{
  font-size: 13px;
  color: var(--text2);
  margin: 0 0 8px;
}}
@media (max-width: 768px) {{
  .gameplay-guide {{ padding: 14px 16px; }}
  .gameplay-guide p {{ font-size: 14px; }}
}}

.card-name {{
  font-size: 11px;
  color: var(--text2);
  text-align: center;
  margin-top: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.card-roles {{
  position: absolute;
  top: 4px; right: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}}
.role-icon {{
  background: rgba(0,0,0,0.7);
  border-radius: 3px;
  font-size: 10px;
  padding: 1px 3px;
  line-height: 1;
}}

/* CARD TOOLTIP */
.card-tooltip {{
  display: none;
  position: fixed;
  z-index: 1000;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
  max-width: 300px;
  box-shadow: 0 16px 48px rgba(0,0,0,0.8);
  pointer-events: none;
}}
.card-tooltip.visible {{ display: block; }}
.tooltip-name {{
  font-family: 'Cinzel', serif;
  font-size: 14px;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 4px;
}}
.tooltip-type {{
  font-size: 11px;
  color: var(--text3);
  margin-bottom: 8px;
}}
.tooltip-oracle {{
  font-size: 12px;
  color: var(--text2);
  line-height: 1.5;
  font-style: italic;
  border-top: 1px solid var(--border);
  padding-top: 8px;
  margin-top: 8px;
}}
.tooltip-role {{
  font-size: 11px;
  color: var(--accent2);
  margin-top: 6px;
}}
.tooltip-justification {{
  font-size: 11px;
  color: var(--text3);
  margin-top: 4px;
  font-style: italic;
}}

/* UPGRADE SECTION */
.upgrade-box {{
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
}}
.gap-item {{
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  color: var(--text2);
}}
.gap-item:last-child {{ border-bottom: none; }}
.gap-icon {{ font-size: 16px; }}
.upgrade-cta {{
  margin-top: 16px;
  font-size: 12px;
  color: var(--text3);
  font-style: italic;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}}

/* EMPTY STATE */
.empty-state {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 60vh;
  color: var(--text3);
  text-align: center;
}}
.empty-state h2 {{
  font-family: 'Cinzel', serif;
  font-size: 24px;
  color: var(--accent2);
  margin-bottom: 12px;
}}
.empty-state p {{ font-size: 14px; line-height: 1.8; }}

/* SCROLLBAR */
::-webkit-scrollbar {{ width: 6px; }}
::-webkit-scrollbar-track {{ background: var(--bg); }}
::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}

/* HAMBURGER BUTTON */
#menu-btn {{
  display: none;
  position: fixed;
  top: 12px; left: 12px;
  z-index: 200;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 44px; height: 44px;
  cursor: pointer;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.5);
}}
#menu-btn span {{
  display: block;
  width: 20px; height: 2px;
  background: var(--accent);
  border-radius: 2px;
  transition: all 0.2s;
}}
#sidebar-overlay {{
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  z-index: 99;
}}

@media (max-width: 768px) {{
  :root {{ --sidebar: 280px; }}

  body {{ display: block; }}

  /* Sidebar oculto por defecto, aparece como drawer */
  #sidebar {{
    transform: translateX(-100%);
    transition: transform 0.25s ease;
    z-index: 100;
  }}
  #sidebar.open {{
    transform: translateX(0);
  }}
  #sidebar-overlay.open {{
    display: block;
  }}
  #menu-btn {{
    display: flex;
  }}

  /* Main ocupa toda la pantalla */
  #main {{
    margin-left: 0;
    width: 100%;
  }}

  /* Hero: columna, más compacto */
  .deck-hero {{
    height: auto;
    min-height: 200px;
  }}
  .deck-hero-content {{
    flex-direction: row;
    align-items: flex-end;
    padding: 16px;
    gap: 16px;
  }}
  .commander-portrait {{
    width: 90px;
    height: 124px;
    flex-shrink: 0;
  }}
  .deck-hero-text h2 {{
    font-size: 18px;
    line-height: 1.2;
  }}
  .deck-color-pips {{ font-size: 14px; margin: 3px 0; }}
  .deck-archetype-badge {{ font-size: 10px; }}
  .bracket-badge {{ font-size: 11px; padding: 3px 8px; margin-left: 0; margin-top: 4px; display: flex; }}

  /* Content padding */
  .deck-content {{ padding: 0 12px 48px; }}

  /* Stats: 2 columnas */
  .stats-row {{ grid-template-columns: 1fr 1fr; gap: 8px; }}
  .stat-value {{ font-size: 18px; }}

  /* Archetype boxes: 1 columna */
  .archetype-box {{ grid-template-columns: 1fr; gap: 12px; }}

  /* Bracket detail: 1 columna */
  .bracket-detail {{ grid-template-columns: 1fr; gap: 8px; }}

  /* Card grid: 3 columnas en móvil */
  .card-grid {{
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }}
  .card-name {{ font-size: 10px; }}

  /* Section titles más pequeños */
  .section-title {{ font-size: 11px; }}
  .section {{ margin-top: 24px; }}
  .category-title {{ font-size: 11px; }}

  /* Tooltip: anchura completa en móvil */
  .card-tooltip {{
    position: fixed;
    bottom: 0; left: 0; right: 0;
    top: auto;
    max-width: 100%;
    border-radius: 16px 16px 0 0;
    padding: 20px;
    pointer-events: auto;
    z-index: 500;
  }}
  .card-tooltip.visible {{ display: block; }}
}}
</style>
</head>
<body>

<button id="menu-btn" onclick="toggleSidebar()" aria-label="Menu">
  <span></span><span></span><span></span>
</button>
<div id="sidebar-overlay" onclick="toggleSidebar()"></div>

<nav id="sidebar">
  <div id="sidebar-header">
    <h1>Deck Forge</h1>
    <p id="deck-count">Cargando...</p>
  </div>
  <div id="deck-list"></div>
</nav>

<main id="main">
  <div id="panels"></div>
</main>

<div class="card-tooltip" id="tooltip">
  <div class="tooltip-name" id="tt-name"></div>
  <div class="tooltip-type" id="tt-type"></div>
  <div class="tooltip-oracle" id="tt-oracle"></div>
  <div class="tooltip-role" id="tt-role"></div>
  <div class="tooltip-justification" id="tt-just"></div>
</div>

<div class="card-modal" id="card-modal">
  <button class="card-modal-close" id="card-modal-close" aria-label="Cerrar">✕</button>
  <img class="card-modal-img" id="card-modal-img" alt="">
</div>

<script>
const DECK_DATA = {json_str};

const BRACKET_COLORS = {{1:'#5a5468',2:'#27ae60',3:'#f39c12',4:'#e74c3c',5:'#8b0000'}};
const GAP_ICONS = {{
  fast_mana:'⚡', tutor:'🔍', game_changer:'💎', manabase:'🗺', cmc:'⚖'
}};

function bracketColor(b) {{ return BRACKET_COLORS[b] || '#fff'; }}

function renderSidebar(decks) {{
  const list = document.getElementById('deck-list');
  const count = document.getElementById('deck-count');
  const keys = Object.keys(decks);
  count.textContent = keys.length + ' mazo' + (keys.length !== 1 ? 's' : '');

  list.innerHTML = keys.map(key => {{
    const d = decks[key];
    return `<div class="deck-nav-item" data-key="${{key}}" id="nav-${{key}}">
      <img class="deck-nav-commander-img" src="${{d.commander_img}}"
           onerror="this.style.display='none'" alt="">
      <div class="deck-nav-info">
        <div class="deck-nav-name">${{d.commander}}</div>
        <div class="deck-nav-meta">${{d.archetype_name}} · B${{d.bracket}}</div>
      </div>
      <div class="bracket-dot" style="background:${{bracketColor(d.bracket)}}"></div>
    </div>`;
  }}).join('');
}}

function renderGaps(deck) {{
  const gaps = [];
  if (!deck.fast_mana || deck.fast_mana.length === 0)
    gaps.push({{cat:'fast_mana', msg:'Sin fast mana — necesitas al menos 1 pieza para bracket 2'}});
  if (deck.manabase_score < 3)
    gaps.push({{cat:'manabase', msg:`Manabase débil (${{deck.manabase_score}}/10)`}});
  if (deck.avg_cmc >= 4)
    gaps.push({{cat:'cmc', msg:`CMC promedio alto (${{deck.avg_cmc}})`}});
  return gaps;
}}

// State for view mode and sorting
let currentSort = 'default';
let currentView = 'grid';

const TYPE_ORDER = {{
  'Creature': 1, 'Artifact': 2, 'Enchantment': 3,
  'Planeswalker': 4, 'Instant': 5, 'Sorcery': 6, 'Land': 7,
}};

function getTypeOrder(type) {{
  if (!type) return 99;
  for (const key in TYPE_ORDER) {{
    if (type.includes(key)) return TYPE_ORDER[key];
  }}
  return 99;
}}

function sortCards(cards, mode) {{
  const arr = [...cards];
  switch (mode) {{
    case 'name':
      return arr.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    case 'cmc':
      return arr.sort((a, b) => (a.cmc ?? 99) - (b.cmc ?? 99) || (a.name || '').localeCompare(b.name || ''));
    case 'cmc_desc':
      return arr.sort((a, b) => (b.cmc ?? -1) - (a.cmc ?? -1) || (a.name || '').localeCompare(b.name || ''));
    case 'type':
      return arr.sort((a, b) => getTypeOrder(a.type) - getTypeOrder(b.type) || (a.cmc ?? 99) - (b.cmc ?? 99));
    case 'rank':
      return arr.sort((a, b) => (a.rank ?? 999999) - (b.rank ?? 999999));
    case 'default':
    default:
      return arr;
  }}
}}

function setView(btn, view) {{
  currentView = view;
  // Update toggle buttons in this panel
  const toggle = btn.closest('.view-toggle') || btn.parentElement;
  toggle.querySelectorAll('button').forEach(b => b.classList.toggle('active', b === btn));
  // Apply list-mode class to all category sections in the active panel
  const panel = btn.closest('.deck-panel');
  if (panel) {{
    panel.querySelectorAll('.category-section').forEach(sec => {{
      sec.classList.toggle('list-mode', view === 'list');
    }});
  }}
}}

function setSort(selectEl) {{
  const mode = selectEl.value;
  currentSort = mode;
  currentView = 'grid'; // reset view on sort change
  // Re-render all panels to apply new sort
  const activePanel = document.querySelector('.deck-panel.active');
  const activeKey = activePanel ? activePanel.id.replace('panel-', '') : null;
  const panels = document.getElementById('panels');
  panels.innerHTML = '';
  Object.keys(DECK_DATA).forEach(key => {{
    panels.innerHTML += renderDeckPanel(key, DECK_DATA[key]);
  }});
  if (activeKey) showDeck(activeKey);
}}

function renderDeckPanel(key, deck) {{
  const gaps = renderGaps(deck);

  const categoriesHtml = Object.entries(deck.categories || {{}}).map(([cat, cards]) => {{
    if (!cards || cards.length === 0) return '';
    const sorted = sortCards(cards, currentSort);
    const cardsHtml = sorted.map(c => {{
      const icons = (c.role_icons || []).slice(0, 3).join('');
      const cardData = `data-name="${{c.name.replace(/"/g,'&quot;')}}"
               data-type="${{(c.type||'').replace(/"/g,'&quot;')}}"
               data-oracle="${{(c.oracle||'').replace(/"/g,'&quot;')}}"
               data-role="${{(c.role||'').replace(/"/g,'&quot;')}}"
               data-just="${{(c.justification||'').replace(/"/g,'&quot;')}}"`;
      const img = c.img
        ? `<img src="${{c.img}}" alt="${{c.name}}" loading="lazy"
               style="cursor:zoom-in"
               onmouseenter="showTooltip(event,this)"
               onmouseleave="hideTooltip()"
               onclick="openCardModal(this); return false;"
               ontouchend="event.preventDefault(); openCardModal(this);"
               ${{cardData}}>`
        : `<div style="height:196px;background:#1a1a24;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:11px;color:#5a5468;border:1px solid #2a2a3a">${{c.name}}</div>`;
      return `<div class="card-item">
        ${{img}}
        ${{icons ? `<div class="card-roles">${{icons.split('').map(i=>`<span class="role-icon">${{i}}</span>`).join('')}}</div>` : ''}}
        <div class="card-name">${{c.name}}</div>
      </div>`;
    }}).join('');

    // Vista lista
    const rowsHtml = sorted.map(c => {{
      const icons = (c.role_icons || []).slice(0, 3).join('');
      const thumb = c.img
        ? `<img class="card-list-thumb" src="${{c.img}}" alt="" loading="lazy">`
        : `<div class="card-list-thumb" style="background:#1a1a24"></div>`;
      const onclickAttr = c.img
        ? `onclick="openCardModal(this.querySelector('img'))" ontouchend="event.preventDefault(); openCardModal(this.querySelector('img'));"`
        : '';
      return `<div class="card-list-row" ${{onclickAttr}}>
        ${{thumb}}
        <div class="card-list-name">${{c.name}}</div>
        <div class="card-list-type">${{c.type || ''}}</div>
        <div class="card-list-cmc">${{c.cmc != null ? c.cmc : '—'}}</div>
        <div class="card-list-roles">${{icons}}</div>
      </div>`;
    }}).join('');

    return `<div class="category-section">
      <div class="category-title">
        ${{cat}}
        <span class="category-count">${{cards.length}}</span>
      </div>
      <div class="card-grid">${{cardsHtml}}</div>
      <div class="card-list">${{rowsHtml}}</div>
    </div>`;
  }}).join('');

  const wincons = (deck.wincons || []).map(w =>
    `<li>${{w}}</li>`
  ).join('');

  const bracketNotes = (deck.bracket_notes || []).map(n =>
    `<div class="bracket-note">${{n}}</div>`
  ).join('');

  const gapsHtml = gaps.length > 0
    ? gaps.map(g => `<div class="gap-item">
        <span class="gap-icon">${{GAP_ICONS[g.cat] || '•'}}</span>
        <span>${{g.msg}}</span>
      </div>`).join('')
    : `<div class="gap-item"><span class="gap-icon">✓</span><span style="color:#27ae60">Sin gaps detectados para bracket 2</span></div>`;

  const gameChangers = deck.game_changers && deck.game_changers.length > 0
    ? deck.game_changers.join(', ')
    : '—';
  const fastMana = deck.fast_mana && deck.fast_mana.length > 0
    ? deck.fast_mana.join(', ')
    : '—';
  const tutors = deck.tutors && deck.tutors.length > 0
    ? deck.tutors.join(', ')
    : '—';

  return `<div class="deck-panel" id="panel-${{key}}">
    <div class="deck-hero">
      <div class="deck-hero-bg" style="background-image:url('${{deck.commander_img}}')"></div>
      <div class="deck-hero-content">
        <img class="commander-portrait" src="${{deck.commander_img}}"
             onerror="this.style.opacity=0" alt="${{deck.commander}}">
        <div class="deck-hero-text">
          <h2>${{deck.commander}}</h2>
          <div class="deck-color-pips">${{deck.color_pips}}</div>
          <span class="deck-archetype-badge">${{deck.archetype_name}}</span>
          <span class="bracket-badge">
            <span class="b-dot" style="background:${{bracketColor(deck.bracket)}}"></span>
            Bracket ${{deck.bracket}} · ${{deck.bracket_label}} · ${{deck.bracket_score}}/5.0
          </span>
        </div>
      </div>
    </div>

    <div class="deck-content">

      <div class="section">
        <div class="stats-row">
          <div class="stat-card"><div class="stat-value">${{deck.card_count}}</div><div class="stat-label">Cartas</div></div>
          <div class="stat-card"><div class="stat-value">${{deck.avg_cmc}}</div><div class="stat-label">CMC Medio</div></div>
          <div class="stat-card"><div class="stat-value">${{deck.manabase_score}}</div><div class="stat-label">Manabase /10</div></div>
          <div class="stat-card"><div class="stat-value" style="color:${{bracketColor(deck.bracket)}}">${{deck.bracket}}</div><div class="stat-label">Bracket</div></div>
        </div>
      </div>

      <div class="section">
        <div class="section-title">Estrategia</div>
        <div class="archetype-box">
          <div class="info-box">
            <h4>Plan del mazo</h4>
            <p>${{deck.archetype_desc}}</p>
          </div>
          <div class="info-box">
            <h4>Wincons</h4>
            <ul class="wincon-list">${{wincons || '<li>Sin wincons definidos</li>'}}</ul>
          </div>
        </div>
      </div>

      ${{deck.gameplay_guide ? `
      <div class="section">
        <div class="section-title">Cómo jugar este mazo</div>
        <div class="gameplay-guide">
          ${{deck.gameplay_guide}}
        </div>
      </div>` : ''}}

      <div class="section">
        <div class="section-title">Bracket estimado · ${{deck.bracket}} (${{deck.bracket_label}})</div>
        <div class="bracket-detail">
          <div class="bracket-item">
            <div class="bracket-item-label">Game Changers</div>
            <div class="bracket-item-value">${{gameChangers}}</div>
          </div>
          <div class="bracket-item">
            <div class="bracket-item-label">Fast Mana</div>
            <div class="bracket-item-value">${{fastMana}}</div>
          </div>
          <div class="bracket-item">
            <div class="bracket-item-label">Tutores</div>
            <div class="bracket-item-value">${{tutors}}</div>
          </div>
        </div>
        ${{bracketNotes ? `<div class="bracket-notes">${{bracketNotes}}</div>` : ''}}
      </div>

      <div class="section">
        <div class="section-title">Gaps para subir bracket</div>
        <div class="upgrade-box">
          ${{gapsHtml}}
          <div class="upgrade-cta">
            Ejecuta <code>python deck_forge.py upgrade --deck ${{key}}</code> para swaps y sugerencias de compra detalladas.
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-title">Cartas del mazo</div>
        <div class="view-controls">
          <span class="view-controls-label">Vista:</span>
          <div class="view-toggle">
            <button class="active" data-view="grid" onclick="setView(this, 'grid')">Cartas</button>
            <button data-view="list" onclick="setView(this, 'list')">Lista</button>
          </div>
          <span class="view-controls-label" style="margin-left:auto">Ordenar por:</span>
          <select class="sort-select" onchange="setSort(this)">
            <option value="default">Por defecto</option>
            <option value="name">Nombre A-Z</option>
            <option value="cmc">CMC (menor)</option>
            <option value="cmc_desc">CMC (mayor)</option>
            <option value="type">Tipo</option>
            <option value="rank">Popularidad</option>
          </select>
        </div>
        ${{categoriesHtml}}
      </div>

    </div>
  </div>`;
}}

function showDeck(key) {{
  document.querySelectorAll('.deck-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.deck-nav-item').forEach(n => n.classList.remove('active'));
  const panel = document.getElementById('panel-' + key);
  const nav   = document.getElementById('nav-' + key);
  if (panel) panel.classList.add('active');
  if (nav)   nav.classList.add('active');
}}

function showTooltip(e, el) {{
  const tt = document.getElementById('tooltip');
  document.getElementById('tt-name').textContent  = el.dataset.name  || '';
  document.getElementById('tt-type').textContent  = el.dataset.type  || '';
  document.getElementById('tt-oracle').textContent= el.dataset.oracle|| '';
  document.getElementById('tt-role').textContent  = el.dataset.role  ? '⚙ ' + el.dataset.role : '';
  document.getElementById('tt-just').textContent  = el.dataset.just  || '';
  tt.classList.add('visible');
  positionTooltip(e);
}}

function positionTooltip(e) {{
  const tt = document.getElementById('tooltip');
  const x = e.clientX + 16;
  const y = e.clientY - 60;
  const maxX = window.innerWidth  - tt.offsetWidth  - 16;
  const maxY = window.innerHeight - tt.offsetHeight - 16;
  tt.style.left = Math.min(x, maxX) + 'px';
  tt.style.top  = Math.max(16, Math.min(y, maxY)) + 'px';
}}

function hideTooltip() {{
  document.getElementById('tooltip').classList.remove('visible');
}}

// CARD ZOOM MODAL
function openCardModal(imgEl) {{
  hideTooltip();
  const modal    = document.getElementById('card-modal');
  const modalImg = document.getElementById('card-modal-img');
  modalImg.src = imgEl.src;
  modalImg.alt = imgEl.alt || '';
  modal.classList.add('visible');
}}

function closeCardModal() {{
  document.getElementById('card-modal').classList.remove('visible');
}}

// Cerrar con click fuera de la imagen o en la cruz
document.getElementById('card-modal').addEventListener('click', e => {{
  if (e.target.id === 'card-modal' || e.target.id === 'card-modal-close') {{
    closeCardModal();
  }}
}});

// Cerrar con Escape
document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') closeCardModal();
}});

document.addEventListener('mousemove', e => {{
  if (document.getElementById('tooltip').classList.contains('visible')) {{
    positionTooltip(e);
  }}
}});

function toggleSidebar() {{
  const sidebar  = document.getElementById('sidebar');
  const overlay  = document.getElementById('sidebar-overlay');
  const isOpen   = sidebar.classList.contains('open');
  sidebar.classList.toggle('open', !isOpen);
  overlay.classList.toggle('open', !isOpen);
}}

// (Mobile sidebar close ahora se integra dentro del listener click,
//  no redefiniendo showDeck para evitar recursion infinita)

// INIT
(function init() {{
  const keys = Object.keys(DECK_DATA);
  if (keys.length === 0) {{
    document.getElementById('panels').innerHTML = `
      <div class="empty-state">
        <h2>Grimorio vacío</h2>
        <p>Construye tu primer mazo con:<br>
        <code>python deck_forge.py build --commander "Nombre" ...</code></p>
      </div>`;
    document.getElementById('deck-count').textContent = '0 mazos';
    return;
  }}
  renderSidebar(DECK_DATA);

  // Event delegation — single listener on sidebar, no inline onclick
  document.getElementById('deck-list').addEventListener('click', function(e) {{
    const item = e.target.closest('.deck-nav-item');
    if (item && item.dataset.key) {{
      e.stopPropagation();
      showDeck(item.dataset.key);
      // Cerrar sidebar en mobile tras seleccionar mazo
      if (window.innerWidth <= 768) {{
        const sb = document.getElementById('sidebar');
        const ov = document.getElementById('sidebar-overlay');
        if (sb) sb.classList.remove('open');
        if (ov) ov.classList.remove('open');
      }}
    }}
  }});

  const panels = document.getElementById('panels');
  keys.forEach(key => {{
    panels.innerHTML += renderDeckPanel(key, DECK_DATA[key]);
  }});
  showDeck(keys[0]);
}})();
</script>
</body>
</html>"""


# === PUBLIC API ============================================================

def build_multi_html(output_dir: Path, all_decks: dict[str, tuple]) -> str:
    """
    Construye el HTML multi-mazo completo desde los datos del índice.

    all_decks: dict de key -> (BuiltDeck, BracketReport)
    """
    data = {{}}
    for key, (deck, bracket) in all_decks.items():
        data[key] = _build_deck_data_json(deck, bracket)
    return _render_html(data)


def build_multi_html_from_index(output_dir: Path, index_decks: dict) -> str:
    """
    Construye el HTML directamente desde decks_index.json (sin reconstruir mazos).
    Usado cuando se regenera el HTML sin hacer un nuevo build.
    """
    return _render_html(index_decks)


def to_html_multi(decks, brackets, raw_csv_path, basics_data) -> str:
    """Compatibilidad con llamadas existentes — genera HTML para 1+ mazos."""
    # Este método se llama desde cmd_build con un solo mazo.
    # Genera un HTML standalone para ese mazo (no el multi-mazo del índice).
    # El multi-mazo real se genera en cmd_build después de registrar en el índice.
    data = {}
    for deck, bracket in zip(decks, brackets):
        key = "".join(c if c.isalnum() else "_" for c in deck.commander["name"].lower()).strip("_")
        data[key] = _build_deck_data_json(deck, bracket)
    return _render_html(data)
