"""
llm_critic.py — Revisión inteligente del mazo con Claude Haiku.

Después de que el builder heurístico construye un mazo, este módulo:
1. Envía el mazo + cartas disponibles del pool a Claude Haiku
2. Claude analiza el plan y propone swaps específicos con razonamiento
3. El builder aplica los swaps y regenera el mazo final
4. Claude genera una guía de juego detallada para el grimorio

Coste estimado: ~$0.005-0.015 por mazo (Critic + Guide)
Caché: 24h en ~/.deck_forge_cache/critic/

REQUISITOS:
    ANTHROPIC_API_KEY en .env o variables de entorno
"""

import os
import json
import time
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .builder import BuiltDeck


CACHE_DIR = Path.home() / ".deck_forge_cache" / "critic"
CACHE_TTL_HOURS = 24


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_key(commander_name: str, pool_names: list[str]) -> str:
    content = commander_name + "|" + ",".join(sorted(pool_names[:50]))
    return hashlib.md5(content.encode()).hexdigest()[:16]


def _load_cache(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = (time.time() - data.get("cached_at", 0)) / 3600
        return data if age <= CACHE_TTL_HOURS else None
    except Exception:
        return None


def _save_cache(key: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data["cached_at"] = time.time()
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# LLMCritic
# ---------------------------------------------------------------------------

class LLMCritic:
    """
    Usa Claude Haiku para:
    1. Revisar un mazo y proponer swaps inteligentes (review_and_improve)
    2. Generar una guía de juego detallada en español (generate_gameplay_guide)
    """

    def __init__(self, api_key: str | None = None, verbose: bool = True):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.verbose = verbose

    # ------------------------------------------------------------------
    # Claude API call
    # ------------------------------------------------------------------

    # Modelos: Sonnet para razonamiento de construcción (calidad superior),
    # Haiku para la guía de juego (texto, más barato).
    MODEL_REVIEW = "claude-sonnet-4-6"
    MODEL_GUIDE  = "claude-haiku-4-5"

    def _call_claude(self, prompt: str, max_tokens: int = 2000,
                     model: str | None = None) -> str | None:
        if not self.api_key:
            if self.verbose:
                print("  [CRITIC] Sin ANTHROPIC_API_KEY — saltando revisión LLM.")
                print("  [CRITIC] Añade tu key en el archivo .env del proyecto.")
            return None

        try:
            import urllib.request

            payload = {
                "model": model or self.MODEL_GUIDE,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps(payload).encode(),
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())["content"][0]["text"]

        except Exception as e:
            if self.verbose:
                print(f"  [CRITIC] Error API: {e}")
            return None

    # ------------------------------------------------------------------
    # Prompt 1 — Critic (swaps)
    # ------------------------------------------------------------------

    def _build_critic_prompt(
        self,
        deck: "BuiltDeck",
        pool_not_included: list[dict],
        edhrec_recs: list[str],
        reserved_cards: dict[str, str] | None = None,
    ) -> str:
        """
        Claude devuelve la lista óptima de cartas CON razón e impacto por carta.
        Piensa holísticamente sobre el plan completo y evita cartas reservadas
        por otros mazos de la colección.
        """
        commander_oracle = (deck.commander.get("oracle_text") or "")[:600].replace("\n", " ")

        # Cartas actuales del draft (no tierras)
        current_deck_cards = []
        for cat, cards in deck.categorized().items():
            if cat == "Tierras No-Básicas":
                continue
            for dc in cards:
                oracle = (dc.card.get("oracle_text") or "")[:160].replace("\n", " ")
                synergy = " ★" if (dc.card.get("edhrec_score") or 0) > 0.4 else ""
                current_deck_cards.append(
                    f"  {dc.card['name']}{synergy} "
                    f"(CMC {dc.card.get('cmc','?')}, rank {dc.card.get('edhrec_rank','?')}): {oracle}"
                )

        pool_sorted = sorted(
            [c for c in pool_not_included if not c.get("is_land")],
            key=lambda c: (-(c.get("edhrec_score") or 0.3), c.get("edhrec_rank") or 999999)
        )[:90]

        pool_lines = []
        for c in pool_sorted:
            oracle = (c.get("oracle_text") or "")[:160].replace("\n", " ")
            synergy = " ★" if (c.get("edhrec_score") or 0) > 0.4 else ""
            pool_lines.append(
                f"  {c['name']}{synergy} "
                f"(CMC {c.get('cmc','?')}, rank {c.get('edhrec_rank','?')}): {oracle}"
            )

        edhrec_block = (
            "\n".join(f"  - {n}" for n in edhrec_recs[:20])
            if edhrec_recs else "  (no data)"
        )

        # Bloque de cartas reservadas por otros mazos de la colección
        reserved = reserved_cards or {}
        if reserved:
            reserved_block = "\n".join(
                f"  - {name} (en uso por: {owner})"
                for name, owner in list(reserved.items())[:60]
            )
            reserved_section = f"""
## CARDS ALREADY USED IN OTHER DECKS — DO NOT USE THESE (physical collection, singleton):
{reserved_block}
"""
        else:
            reserved_section = ""

        return f"""You are a world-class Magic: The Gathering Commander deck builder. You have deeply studied the structure of professional Wizards of the Coast precon decks.

## BRACKET 2 GOLD STANDARD — JESKAI STRIKER (Official WotC Precon 2025)
This is the reference structure every Bracket 2 deck must approximate:
  RAMP: 8 pieces — Sol Ring (mandatory) + signets for each color pair + Fellwar Stone/Talisman
  DRAW: 15 pieces — 5x CMC-1 cantrips (Opt/Ponder/Preordain) + 5x medium draw + 5x engines
  PAYOFFS: 12 permanents that directly implement the main plan
  REMOVAL: 4 single-target + 2 board wipes + 1 permanent removal = 7 total
  LANDS: 37 (14+ basics so check-lands enter untapped + dual/utility mix)
  AVG CMC: 2.8 (curve peaks at CMC 2-3; CMC 7+ only for impactful finishers)

Golden rules from that analysis:
- Sol Ring is mandatory in EVERY Commander deck without exception.
- Include the Signets for each color pair of the commander (e.g., Izzet+Azorius+Boros for WUR).
- 5 CMC-1 cantrips form the consistency backbone — pick any available in the colors.
- Swords to Plowshares is the gold standard White removal; always include if playing White.
- 2-3 tight synergy packages (2-3 cards each) beat 10 random "good" cards.
- No tutors, no fast mana (Mana Crypt, Mox), no 2-card infinite combos in Bracket 2.
- Every payoff card must reference the commander ability specifically, not just be generically good.

## COMMANDER
Name: {deck.commander['name']}
Color identity: {deck.colors}
Full ability text: {commander_oracle}

## ARCHETYPE: {deck.archetype.name}
Strategy: {deck.archetype.description}

## ARCHETYPE SLOT PLAN — approximate these proportions for THIS archetype
(The Jeskai Striker standard above is the generic baseline; THIS plan overrides
it where they differ — e.g. stax/mill/group hug have different structures):
{chr(10).join(f"  {s.name}: {s.target_count} cards — {s.justification}" for s in deck.archetype.slots)}

## CARDS CURRENTLY IN DRAFT (heuristic build — improve on it):
{"".join(current_deck_cards)}

## ADDITIONAL CARDS AVAILABLE IN COLLECTION (★ = proven EDHREC synergy):
{"".join(pool_lines)}

## EDHREC HIGH-SYNERGY CARDS FOR THIS COMMANDER:
{edhrec_block}
{reserved_section}
## YOUR REASONING PROCESS
1. RAMP FIRST: Identify Sol Ring + the 2-3 Signets for this color identity. Are they available? Pick them.
2. CANTRIPS: Find 3-5 CMC-1 cantrips in these colors. These go in automatically.
3. ENGINE: Which 2-3 cards directly power up the commander's specific ability?
4. SYNERGY PACKAGES: Build 2-3 clusters of cards that reference each other AND the commander.
5. WIN CONDITIONS: Define 2-3 concrete paths to victory using cards from the available pool.
6. INTERACTION: 4 single removal + 2 sweepers minimum. Check Swords/Path/Abrade availability.
7. CUTS: Remove anything with CMC 5+ that doesn't win the game or generate massive advantage.
8. CURVE CHECK: Does the final list have a CMC average around 2.8? Adjust if higher.

## STRICT RULES
- Every card must exist in "CARDS CURRENTLY IN DRAFT" or "ADDITIONAL CARDS AVAILABLE"
- Color identity: EVERY card's color_identity must be a subset of {deck.colors}. ZERO EXCEPTIONS.
- NEVER use any card from "CARDS ALREADY USED IN OTHER DECKS"
- No duplicate names. No basic lands. Not the commander itself.
- Select exactly 60 non-land cards (60 + ~12 utility lands + ~27 basics + commander = 100).

## OUTPUT — per-card reasoning
For EACH card, explain WHY it belongs in THIS specific deck (reference commander ability or synergy).
Write reason and impact in SPANISH, max ~15 words each.

Respond ONLY with valid JSON, no markdown:
{{
  "analysis": "4-5 sentences in Spanish: optimal game plan, synergy packages built, main improvements vs draft.",
  "cards": [
    {{"name": "Card Name", "reason": "razón específica con esta comandante", "impact": "qué aporta al plan"}},
    ... exactly 60 cards
  ]
}}"""

    # ------------------------------------------------------------------
    # Prompt 2 — Gameplay Guide
    # ------------------------------------------------------------------

    def _build_guide_prompt(self, deck: "BuiltDeck") -> str:
        """
        Prompt optimizado para la guía de juego.
        Mejoras vs v1:
        - Oracle text completo del comandante
        - Cartas ordenadas por edhrec_score (más sinérgicas primero)
        - Incluye cartas marcadas como CRITIC para que sepa los swaps aplicados
        - 6 secciones completas con instrucciones detalladas por sección
        - Pide mencionar cartas específicas del mazo en cada sección
        """
        commander_oracle = (deck.commander.get("oracle_text") or "")[:500].replace("\n", " ")

        # Cartas del mazo ordenadas por edhrec_score desc + rank
        all_cards = []
        for cat, cards in deck.categorized().items():
            if cat == "Tierras No-Básicas":
                continue
            for dc in cards:
                all_cards.append((dc, cat))

        all_cards.sort(
            key=lambda x: (
                -(x[0].card.get("edhrec_score") or 0.3),
                x[0].card.get("edhrec_rank") or 999999,
            )
        )

        card_lines = []
        for dc, cat in all_cards[:35]:
            oracle_short = (dc.card.get("oracle_text") or "")[:150].replace("\n", " ")
            synergy_tag = " ★" if (dc.card.get("edhrec_score") or 0) > 0.4 else ""
            critic_tag = " [CRITIC PICK]" if "[CRITIC]" in (dc.justification or "") else ""
            card_lines.append(
                f"  {dc.card['name']}{synergy_tag}{critic_tag} "
                f"(CMC {dc.card.get('cmc','?')}, {cat}): {oracle_short}"
            )

        return f"""You are a competitive Magic: The Gathering Commander player writing a detailed deck guide for players.

## DECK: {deck.commander['name']}
Colors: {deck.colors}
Archetype: {deck.archetype.name}
Commander ability: {commander_oracle}
Strategy: {deck.archetype.description}

## KEY CARDS (★ = high synergy with commander, [CRITIC PICK] = AI-recommended addition):
{"".join(card_lines)}

## WRITE A DETAILED GAMEPLAY GUIDE IN SPANISH

Write engaging, practical Spanish text. Be specific — always mention actual card names from this deck, not generic advice.

Structure with <h4> and <p> HTML tags. Include ALL 6 sections:

<h4>Plan del mazo</h4>
[4-5 frases] Explica exactamente qué quiere hacer este mazo y por qué el comandante es central al plan. Menciona las 3-4 cartas más importantes (★) y cómo interactúan con el comandante.

<h4>Cómo ganar</h4>
[4-5 frases] Describe las 2-3 líneas de victoria concretas. Menciona cartas específicas del mazo y la secuencia de juego para ganar. Incluye condiciones y requisitos para cada línea.

<h4>Mano inicial (Mulligan)</h4>
[4-5 frases] Qué cartas son imprescindibles en la mano inicial. Qué combinaciones de 2-3 cartas son perfectas para empezar. Cuándo hacer mulligan sin dudar. Da ejemplos concretos con cartas del mazo.

<h4>Curva de juego ideal</h4>
[5-6 frases] Plan turno a turno detallado: turno 1 (qué jugar), turno 2 (qué desarrollar), turno 3 (cuándo bajar el comandante), turno 4+ (cómo cerrar). Menciona cartas específicas para cada turno.

<h4>Sinergias clave</h4>
[5-6 frases] Explica 3-4 combos o sinergias específicas entre cartas del mazo. Para cada una: nombra las cartas exactas, explica la interacción y por qué es poderosa en este mazo concreto.

<h4>Amenazas y cómo responder</h4>
[4-5 frases] Las 3 amenazas más peligrosas para este mazo (removal del comandante, counters, aggro, etc). Para cada una: qué cartas del mazo tienes para responder y cuándo usarlas.

Respond ONLY with the HTML content, no other text, no markdown fences."""

    # ------------------------------------------------------------------
    # Public: review_and_improve
    # ------------------------------------------------------------------

    def review_and_improve(
        self,
        deck: "BuiltDeck",
        full_pool: list[dict],
        edhrec_recs: list[str] | None = None,
        reserved_cards: dict[str, str] | None = None,
    ) -> "BuiltDeck":
        """
        Claude (Sonnet) devuelve la lista óptima de cartas con razón e impacto por carta.
        El builder reconstruye el mazo con esas cartas, reclasificadas por el classifier.
        reserved_cards: {nombre_lower: mazo_dueño} — cartas a evitar (singleton de colección).
        """
        commander_name = deck.commander["name"]
        reserved = reserved_cards or {}

        deck_names = {dc.card["name"] for dc in deck.cards} | {commander_name}
        pool_not_included = [
            c for c in full_pool
            if c["name"] not in deck_names and not c.get("is_land")
        ]

        # Cache key incluye estado de reservas (distintas reservas → distinto mazo)
        reserve_sig = ",".join(sorted(reserved.keys())[:30])
        cache_key = _cache_key(commander_name,
                               [c["name"] for c in pool_not_included] + [reserve_sig])
        cached = _load_cache(cache_key)

        if cached:
            if self.verbose:
                print(f"  [CRITIC] Cache hit para '{commander_name}'")
            result = cached
        else:
            if self.verbose:
                print(f"  [CRITIC] Reconstruyendo '{commander_name}' con Claude Sonnet...")

            prompt = self._build_critic_prompt(deck, pool_not_included,
                                               edhrec_recs or [], reserved)
            response = self._call_claude(prompt, max_tokens=8000,
                                         model=self.MODEL_REVIEW)
            if not response:
                return deck

            try:
                clean = response.strip()
                if "```" in clean:
                    for part in clean.split("```"):
                        p = part.strip()
                        if p.startswith("json"):
                            p = p[4:].strip()
                        if p.startswith("{"):
                            clean = p
                            break

                # Try full parse
                try:
                    result = json.loads(clean.strip())
                except json.JSONDecodeError:
                    # Recuperación parcial: extraer objetos {name, reason, impact}
                    import re
                    analysis_match = re.search(r'"analysis"\s*:\s*"([^"]+)"', clean)
                    # Buscar objetos de carta con name
                    obj_matches = re.findall(
                        r'\{\s*"name"\s*:\s*"([^"]+)"'
                        r'(?:\s*,\s*"reason"\s*:\s*"([^"]*)")?'
                        r'(?:\s*,\s*"impact"\s*:\s*"([^"]*)")?',
                        clean,
                    )
                    cards_list = [
                        {"name": m[0], "reason": m[1], "impact": m[2]}
                        for m in obj_matches if m[0]
                    ]
                    result = {
                        "analysis": analysis_match.group(1) if analysis_match else "",
                        "cards": cards_list,
                    }
                    if self.verbose:
                        print(f"  [CRITIC] JSON parcial — recuperadas {len(cards_list)} cartas")

                _save_cache(cache_key, result)

            except Exception as e:
                if self.verbose:
                    print(f"  [CRITIC] Error: {e}")
                    print(f"  [CRITIC] Raw: {response[:300]}")
                return deck

        if self.verbose and result.get("analysis"):
            print(f"  [CRITIC] {result['analysis']}")

        desired_cards = result.get("cards", [])
        if not desired_cards:
            if self.verbose:
                print("  [CRITIC] Sin lista de cartas — usando draft original.")
            return deck

        # Normalizar: aceptar tanto strings (formato viejo) como objetos {name,reason,impact}
        def _normalize(entry):
            if isinstance(entry, str):
                return {"name": entry, "reason": "", "impact": ""}
            if isinstance(entry, dict):
                return {
                    "name": entry.get("name", ""),
                    "reason": entry.get("reason", ""),
                    "impact": entry.get("impact", ""),
                }
            return {"name": "", "reason": "", "impact": ""}

        desired = [_normalize(e) for e in desired_cards]

        # Guardar tierras originales antes de reconstruir
        original_categories = deck.categorized()

        # Construir lookup de todas las cartas disponibles (draft + pool)
        all_available: dict[str, dict] = {}
        for dc in deck.cards:
            all_available[dc.card["name"].lower()] = dc.card
        for c in pool_not_included:
            all_available[c["name"].lower()] = c

        # Identidad de color del comandante — filtro de seguridad
        commander_ci = set(deck.commander.get("color_identity") or [])

        # Validar cada carta de la lista de Claude — preservando razón/impacto
        validated: list[dict] = []
        reasons: dict[str, str] = {}   # name_lower → reason
        impacts: dict[str, str] = {}   # name_lower → impact
        seen_names: set[str] = set()
        skipped = 0

        for entry in desired:
            card_name = (entry.get("name") or "").strip()
            if not card_name:
                continue
            name_lower = card_name.lower()
            if name_lower in seen_names:
                skipped += 1
                continue

            card = all_available.get(name_lower)
            if not card:
                if self.verbose:
                    print(f"  [CRITIC] SKIP no en pool: '{card_name}'")
                skipped += 1
                continue

            # ── VALIDACIÓN DE IDENTIDAD DE COLOR ──
            card_ci = set(card.get("color_identity") or [])
            if commander_ci and not card_ci.issubset(commander_ci):
                if self.verbose:
                    print(f"  [CRITIC] SKIP color ilegal: '{card_name}'")
                skipped += 1
                continue

            # ── VALIDACIÓN DE RESERVA (otro mazo de la colección) ──
            if name_lower in reserved:
                if self.verbose:
                    print(f"  [CRITIC] SKIP reservada por '{reserved[name_lower]}': '{card_name}'")
                skipped += 1
                continue

            validated.append(card)
            reasons[name_lower] = entry.get("reason", "")
            impacts[name_lower] = entry.get("impact", "")
            seen_names.add(name_lower)

        if self.verbose:
            print(f"  [CRITIC] {len(validated)}/{len(desired_cards)} cartas validadas "
                  f"({skipped} descartadas)")

        if len(validated) < 30:
            if self.verbose:
                print("  [CRITIC] Muy pocas cartas validadas — usando draft original.")
            return deck

        # Reconstruir el mazo con las cartas validadas, reclasificadas
        from .builder import DeckCard
        from . import classifier as cls

        new_cards = []
        for card in validated:
            roles = cls.classify(card)
            # Determinar categoría basada en roles
            if "ramp" in roles and not card.get("is_land"):
                cat = "Ramp"
                role = "Ramp"
            elif "draw" in roles:
                cat = "Card Draw"
                role = "Draw"
            elif "removal" in roles or "sweeper" in roles or "counter" in roles:
                cat = "Removal & Interaction"
                role = "Removal"
            elif "equipment" in roles:
                cat = "Equipment"
                role = "Equipment"
            elif card.get("is_creature") and any(r.startswith("payoff_") for r in roles):
                cat = "Sinergias"
                role = "Synergy"
            elif "threat" in roles or (card.get("is_creature") and int(card.get("cmc") or 0) >= 4):
                cat = "Wincons & Amenazas"
                role = "Wincon"
            else:
                cat = "Soporte"
                role = "Support"

            nl = card["name"].lower()
            reason = reasons.get(nl, "").strip()
            impact = impacts.get(nl, "").strip()
            new_cards.append(DeckCard(
                card=card,
                category=cat,
                role=role,
                justification=reason or "Seleccionada por el análisis de Claude como óptima para este slot.",
                impact=impact,
            ))

        deck.cards = new_cards
        if self.verbose:
            print(f"  [CRITIC] Mazo reconstruido con {len(new_cards)} cartas.")

        # Preservar tierras no-básicas del draft original
        from .builder import DeckCard as DC2
        lands_preserved = 0
        for cat, cards in original_categories.items():
            if cat == "Tierras No-Básicas":
                for dc in cards:
                    if dc.card["name"] not in seen_names:
                        deck.cards.append(DC2(
                            card=dc.card,
                            category="Tierras No-Básicas",
                            role="Land",
                            justification="Tierra de utilidad.",
                        ))
                        seen_names.add(dc.card["name"])
                        lands_preserved += 1
        if self.verbose and lands_preserved:
            print(f"  [CRITIC] {lands_preserved} tierras no-básicas preservadas.")

        # Relleno de seguridad: si el Critic devolvió pocas cartas,
        # completar con las mejores cartas del pool disponible (no-tierras).
        TARGET_REAL_CARDS = 73  # 62 no-tierras + 11 tierras utilidad ≈ 99-26 básicas
        if len(deck.cards) < TARGET_REAL_CARDS:
            all_pool = {c["name"].lower(): c for c in full_pool if not c.get("is_land")}
            # añadir también las del draft original (no-tierras)
            for dc in deck.cards:
                all_pool[dc.card["name"].lower()] = dc.card

            remaining = [
                c for name, c in all_pool.items()
                if name not in seen_names
                and not c.get("is_land")
                and (not commander_ci or
                     set(c.get("color_identity") or []).issubset(commander_ci))
            ]
            # Ordenar por edhrec_rank (menor = más popular)
            remaining.sort(key=lambda c: (c.get("edhrec_rank") or 999999))
            needed = TARGET_REAL_CARDS - len(deck.cards)
            filled = 0
            for c in remaining:
                if filled >= needed:
                    break
                from . import classifier as cls2
                roles = cls2.classify(c)
                deck.cards.append(DC2(
                    card=c,
                    category="Soporte General",
                    role="Support",
                    justification="[CRITIC FILL] Mejor carta disponible para completar el mazo.",
                ))
                seen_names.add(c["name"].lower())
                filled += 1
            if self.verbose and filled:
                print(f"  [CRITIC] Relleno post-critic: {filled} cartas añadidas "
                      f"para alcanzar {len(deck.cards)} total.")

        return deck

    # ------------------------------------------------------------------
    # Public: generate_gameplay_guide
    # ------------------------------------------------------------------

    def generate_gameplay_guide(self, deck: "BuiltDeck") -> str:
        """Genera guía de juego HTML con Claude Haiku. Con caché 24h."""
        commander_name = deck.commander["name"]
        cache_key = "guide_" + _cache_key(commander_name, [deck.archetype.key])
        cached = _load_cache(cache_key)

        if cached:
            if self.verbose:
                print(f"  [GUIDE] Cache hit para '{commander_name}'")
            return cached.get("html", "")

        if self.verbose:
            print(f"  [GUIDE] Generando guía para '{commander_name}'...")

        prompt = self._build_guide_prompt(deck)
        response = self._call_claude(prompt, max_tokens=3000, model=self.MODEL_GUIDE)
        if not response:
            return ""

        html = response.strip()
        if "```" in html:
            parts = html.split("```")
            html = parts[1] if len(parts) > 1 else html
            if html.startswith("html"):
                html = html[4:]
        html = html.strip()

        _save_cache(cache_key, {"html": html})
        return html
