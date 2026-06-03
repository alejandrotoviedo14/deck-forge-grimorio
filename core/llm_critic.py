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

    def _call_claude(self, prompt: str, max_tokens: int = 2000) -> str | None:
        if not self.api_key:
            if self.verbose:
                print("  [CRITIC] Sin ANTHROPIC_API_KEY — saltando revisión LLM.")
                print("  [CRITIC] Añade tu key en el archivo .env del proyecto.")
            return None

        try:
            import urllib.request

            payload = {
                "model": "claude-haiku-4-5",
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
    ) -> str:
        """
        Nuevo approach: Claude devuelve la lista de cartas que QUIERE en el mazo.
        No hace swaps posicionales — piensa holísticamente sobre el plan completo.
        El builder valida disponibilidad y reasigna categorías con el classifier.
        """
        commander_oracle = (deck.commander.get("oracle_text") or "")[:500].replace("\n", " ")

        # Todas las cartas disponibles: en el mazo + pool no incluido
        # ordenadas por edhrec_score + rank
        current_deck_cards = []
        for cat, cards in deck.categorized().items():
            if cat == "Tierras No-Básicas":
                continue
            for dc in cards:
                oracle = (dc.card.get("oracle_text") or "")[:180].replace("\n", " ")
                synergy = " ★" if (dc.card.get("edhrec_score") or 0) > 0.4 else ""
                current_deck_cards.append(
                    f"  {dc.card['name']}{synergy} "
                    f"(CMC {dc.card.get('cmc','?')}, "
                    f"rank {dc.card.get('edhrec_rank','?')}): {oracle}"
                )

        pool_sorted = sorted(
            [c for c in pool_not_included if not c.get("is_land")],
            key=lambda c: (
                -(c.get("edhrec_score") or 0.3),
                c.get("edhrec_rank") or 999999,
            )
        )[:80]

        pool_lines = []
        for c in pool_sorted:
            oracle = (c.get("oracle_text") or "")[:180].replace("\n", " ")
            synergy = " ★" if (c.get("edhrec_score") or 0) > 0.4 else ""
            pool_lines.append(
                f"  {c['name']}{synergy} "
                f"(CMC {c.get('cmc','?')}, "
                f"rank {c.get('edhrec_rank','?')}): {oracle}"
            )

        edhrec_block = (
            "\n".join(f"  - {n}" for n in edhrec_recs[:20])
            if edhrec_recs else "  (no data)"
        )

        return f"""You are the world's best Magic: The Gathering Commander deck builder. Build the OPTIMAL 99-card deck for this commander from the available card pool.

## COMMANDER
Name: {deck.commander['name']}
Colors: {deck.colors}
Ability: {commander_oracle}

## ARCHETYPE: {deck.archetype.name}
Strategy: {deck.archetype.description}

## CARDS CURRENTLY IN DRAFT (you may keep or replace any of these):
{"".join(current_deck_cards)}

## ADDITIONAL CARDS AVAILABLE IN COLLECTION (not yet in draft):
{"".join(pool_lines)}

## EDHREC HIGH-SYNERGY CARDS FOR THIS COMMANDER (★ = proven synergy):
{edhrec_block}

## YOUR MISSION
Think about the commander's game plan holistically. Consider:
1. What does this commander need on turns 1-4 to function?
2. What are the 3-4 best win conditions given the available cards?
3. Which cards have 1:N synergies — one card that enables multiple others?
4. What is the ideal ratio of ramp/draw/removal/threats/synergy for this strategy?
5. Which cards are simply too slow, too conditional, or off-theme?

Select exactly 50 non-land cards (the deck needs these + commander + 12 utility lands + ~37 basic lands = 100).

STRICT RULES:
- Every card must exist in either "CARDS CURRENTLY IN DRAFT" or "ADDITIONAL CARDS AVAILABLE"
- Respect {deck.colors} color identity strictly — no exceptions
- No duplicate card names
- Do not include basic lands or the commander itself
- ★ cards are proven synergies — prioritize them when they fit the strategy

Respond ONLY with valid JSON, no markdown, no other text:
{{
  "analysis": "4-5 sentences: the commander's optimal game plan, key synergy packages you identified, and why you made major changes from the draft",
  "cards": [
    "Card Name 1",
    "Card Name 2",
    ... exactly 50 card names
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
    ) -> "BuiltDeck":
        """
        Claude devuelve la lista óptima de 62 cartas.
        El builder reconstruye el mazo con esas cartas, reclasificadas por el classifier.
        """
        commander_name = deck.commander["name"]

        deck_names = {dc.card["name"] for dc in deck.cards} | {commander_name}
        pool_not_included = [
            c for c in full_pool
            if c["name"] not in deck_names and not c.get("is_land")
        ]

        cache_key = _cache_key(commander_name, [c["name"] for c in pool_not_included])
        cached = _load_cache(cache_key)

        if cached:
            if self.verbose:
                print(f"  [CRITIC] Cache hit para '{commander_name}'")
            result = cached
        else:
            if self.verbose:
                print(f"  [CRITIC] Reconstruyendo '{commander_name}' con Claude Haiku...")

            prompt = self._build_critic_prompt(deck, pool_not_included, edhrec_recs or [])
            response = self._call_claude(prompt, max_tokens=4000)
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
                    # Extract partial JSON — get cards array
                    import re
                    analysis_match = re.search(r'"analysis"\s*:\s*"([^"]+)"', clean)
                    # Extract card names from partial array
                    card_matches = re.findall(r'"([^"]{3,60})"', clean)
                    # Filter out JSON keys
                    json_keys = {"analysis", "cards", "swaps", "remove", "add", "reason"}
                    card_names = [c for c in card_matches
                                  if c not in json_keys and len(c) > 3]
                    result = {
                        "analysis": analysis_match.group(1) if analysis_match else "",
                        "cards": card_names,
                    }
                    if self.verbose:
                        print(f"  [CRITIC] JSON parcial — recuperadas {len(card_names)} cartas")

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

        # Validar cada carta de la lista de Claude
        validated: list[dict] = []
        seen_names: set[str] = set()
        skipped = 0

        for card_name in desired_cards:
            name_lower = card_name.lower().strip()
            if name_lower in seen_names:
                if self.verbose:
                    print(f"  [CRITIC] SKIP duplicado: '{card_name}'")
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
                    print(f"  [CRITIC] SKIP color ilegal: '{card_name}' "
                          f"({card_ci} ⊄ {commander_ci})")
                skipped += 1
                continue

            validated.append(card)
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

            new_cards.append(DeckCard(
                card=card,
                category=cat,
                role=role,
                justification="[CRITIC] Seleccionada por análisis holístico.",
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
        response = self._call_claude(prompt, max_tokens=3000)
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
