"""
llm_critic.py — Revisión inteligente del mazo con Claude Haiku.

Después de que el builder heurístico construye un mazo, este módulo:
1. Envía el mazo construido + las cartas del pool NO incluidas a Claude Haiku
2. Claude analiza el plan del mazo y propone swaps específicos
3. El builder aplica los swaps y regenera el mazo final

Coste estimado: ~$0.003-0.01 por mazo (Claude Haiku es muy barato)
Caché: los análisis se guardan en ~/.deck_forge_cache/critic/ durante 24h

USO:
    from core.llm_critic import LLMCritic
    critic = LLMCritic()
    improved_deck = critic.review_and_improve(deck, pool, archetype)

REQUISITOS:
    ANTHROPIC_API_KEY en variables de entorno, o pasar api_key al constructor
"""

import os
import json
import time
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .builder import BuiltDeck
    from .archetypes import Archetype


CACHE_DIR = Path.home() / ".deck_forge_cache" / "critic"
CACHE_TTL_HOURS = 24


def _cache_key(commander_name: str, pool_names: list[str]) -> str:
    content = commander_name + "|" + ",".join(sorted(pool_names[:50]))
    return hashlib.md5(content.encode()).hexdigest()[:16]


def _load_cache(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        age = (time.time() - data.get("cached_at", 0)) / 3600
        if age > CACHE_TTL_HOURS:
            return None
        return data
    except Exception:
        return None


def _save_cache(key: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data["cached_at"] = time.time()
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(data, indent=2))


    def generate_gameplay_guide(self, deck: "BuiltDeck") -> str:
        """
        Genera una guía de juego para el mazo usando Claude Haiku.
        Devuelve HTML listo para insertar en el grimorio.
        """
        commander_name = deck.commander["name"]
        cache_key = "guide_" + _cache_key(commander_name, [deck.archetype.key])
        cached = _load_cache(cache_key)
        if cached:
            if self.verbose:
                print(f"  [GUIDE] Cache hit para '{commander_name}'")
            return cached.get("html", "")

        if self.verbose:
            print(f"  [GUIDE] Generando guía para '{commander_name}'...")

        # Construir lista de cartas relevantes
        cards_by_cat = deck.categorized()
        key_cards = []
        for cat, cards in cards_by_cat.items():
            if cat in ("Tierras No-Básicas",):
                continue
            for dc in cards[:3]:
                key_cards.append(f"{dc.card['name']} ({cat})")

        prompt = f"""You are an expert Magic: The Gathering Commander player writing a deck guide.

COMMANDER: {commander_name}
ARCHETYPE: {deck.archetype.name}
COLORS: {deck.colors}
PLAN: {deck.archetype.description}
WIN CONDITIONS: {', '.join(deck.archetype.auto_includes[:5]) if deck.archetype.auto_includes else 'See key cards'}

KEY CARDS IN THIS DECK:
{chr(10).join(key_cards[:20])}

Write a concise gameplay guide in SPANISH with these sections:
1. **Plan del mazo** (2-3 sentences: what does this deck want to do?)
2. **Cómo ganar** (2-3 sentences: main win conditions)
3. **Mulligan** (1-2 sentences: what to keep in opening hand)
4. **Curva de juego** (turns 1-4 ideal sequence, 2-3 sentences)
5. **Sinergias clave** (2-3 specific card interactions from this deck)

Keep it practical and specific to THIS deck. Use simple Spanish. No markdown headers, use HTML <h4> and <p> tags.
Respond ONLY with HTML, no other text."""

        response = self._call_claude(prompt)
        if not response:
            return ""

        # Clean potential markdown
        html = response.strip()
        if html.startswith("```"):
            parts = html.split("```")
            html = parts[1] if len(parts) > 1 else html
            if html.startswith("html"):
                html = html[4:]
        html = html.strip()

        _save_cache(cache_key, {"html": html})
        return html
    """
    Usa Claude Haiku para revisar un mazo y proponer mejoras concretas.
    
    Flujo:
    1. Construye prompt con: comandante, arquetipo, mazo actual, candidatos no incluidos
    2. Claude identifica: cartas malas en el mazo + cartas del pool que deberían entrar
    3. Aplica swaps respetando identidad de color y restricciones del formato
    """

    def __init__(self, api_key: str | None = None, verbose: bool = True):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.verbose = verbose

    def _call_claude(self, prompt: str) -> str | None:
        """Llama a Claude Haiku y devuelve la respuesta como string."""
        if not self.api_key:
            if self.verbose:
                print("  [CRITIC] No ANTHROPIC_API_KEY. Saltando revisión LLM.")
                print("  [CRITIC] Añade tu API key: $env:ANTHROPIC_API_KEY='sk-ant-...'")
            return None

        try:
            import urllib.request
            import urllib.error

            payload = {
                "model": "claude-haiku-4-5",
                "max_tokens": 1500,
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

            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data["content"][0]["text"]

        except Exception as e:
            if self.verbose:
                print(f"  [CRITIC] Error llamando a Claude: {e}")
            return None

    def _build_prompt(
        self,
        deck: "BuiltDeck",
        pool_not_included: list[dict],
        edhrec_recommendations: list[str],
    ) -> str:
        """Construye el prompt para Claude con el contexto del mazo."""

        # Mazo actual por categoría (sin tierras ni básicas)
        current_deck_lines = []
        for category, cards in deck.categorized().items():
            if category == "Tierras No-Básicas":
                continue
            current_deck_lines.append(f"\n{category}:")
            for dc in cards:
                rank = dc.card.get("edhrec_rank", "?")
                cmc_val = dc.card.get("cmc", "?")
                current_deck_lines.append(
                    f"  - {dc.card['name']} (CMC {cmc_val}, rank {rank})"
                )

        # Pool no incluido — top candidatos por rank
        pool_not_included_sorted = sorted(
            [c for c in pool_not_included if c.get("edhrec_rank")],
            key=lambda c: c.get("edhrec_rank") or 999999
        )[:40]

        pool_lines = []
        for c in pool_not_included_sorted:
            oracle_short = (c.get("oracle_text") or "")[:80].replace("\n", " ")
            pool_lines.append(
                f"  - {c['name']} (CMC {c.get('cmc','?')}, "
                f"rank {c.get('edhrec_rank','?')}): {oracle_short}"
            )

        # EDHREC recommendations
        edhrec_lines = "\n".join(f"  - {name}" for name in edhrec_recommendations[:15])

        prompt = f"""You are an expert Magic: The Gathering Commander deck builder.

COMMANDER: {deck.commander['name']}
COLOR IDENTITY: {deck.colors}
ARCHETYPE: {deck.archetype.name}
ARCHETYPE PLAN: {deck.archetype.description}

CURRENT DECK (non-land cards):
{''.join(current_deck_lines)}

CARDS IN COLLECTION NOT IN DECK (sorted by EDHREC rank, top 40):
{''.join(pool_lines)}

EDHREC HIGH-SYNERGY CARDS FOR THIS COMMANDER (from community data):
{edhrec_lines if edhrec_lines else "  (no data available)"}

TASK:
Analyze this Commander deck critically. Identify:
1. Cards in the deck that don't fit the archetype plan or are clearly weak
2. Cards from the collection that should replace them

Rules:
- All suggested cards must be from the "CARDS IN COLLECTION NOT IN DECK" list
- Respect the {deck.colors} color identity
- Maximum 8 swaps total
- Focus on improving synergy with the commander's strategy
- Prefer lower CMC when stats are similar

Respond ONLY with a JSON object, no other text:
{{
  "analysis": "2-3 sentence analysis of the deck's main weaknesses",
  "swaps": [
    {{
      "remove": "exact card name to remove",
      "add": "exact card name to add from collection",
      "reason": "one sentence explaining why"
    }}
  ]
}}"""

        return prompt

    def review_and_improve(
        self,
        deck: "BuiltDeck",
        full_pool: list[dict],
        edhrec_recommendations: list[str] | None = None,
    ) -> "BuiltDeck":
        """
        Revisa el mazo y aplica mejoras sugeridas por Claude.
        Devuelve el mazo mejorado (o el original si el Critic falla).
        """
        commander_name = deck.commander["name"]

        # Cartas del pool que NO están en el mazo
        deck_names = {dc.card["name"] for dc in deck.cards}
        deck_names.add(commander_name)
        pool_not_included = [
            c for c in full_pool
            if c["name"] not in deck_names and not c.get("is_land")
        ]

        # Cache check
        pool_names = [c["name"] for c in pool_not_included]
        cache_key = _cache_key(commander_name, pool_names)
        cached = _load_cache(cache_key)

        if cached:
            if self.verbose:
                print(f"  [CRITIC] Cache hit para '{commander_name}'")
            result = cached
        else:
            if self.verbose:
                print(f"  [CRITIC] Analizando '{commander_name}' con Claude Haiku...")

            prompt = self._build_prompt(
                deck,
                pool_not_included,
                edhrec_recommendations or [],
            )

            response = self._call_claude(prompt)
            if not response:
                return deck

            # Parse JSON response
            try:
                # Clean potential markdown fences
                clean = response.strip()
                if clean.startswith("```"):
                    clean = clean.split("```")[1]
                    if clean.startswith("json"):
                        clean = clean[4:]
                result = json.loads(clean.strip())
                _save_cache(cache_key, result)
            except Exception as e:
                if self.verbose:
                    print(f"  [CRITIC] Error parseando respuesta: {e}")
                    print(f"  [CRITIC] Respuesta raw: {response[:200]}")
                return deck

        # Mostrar análisis
        if self.verbose and result.get("analysis"):
            print(f"  [CRITIC] Análisis: {result['analysis']}")

        # Aplicar swaps
        swaps = result.get("swaps", [])
        if not swaps:
            if self.verbose:
                print("  [CRITIC] No se propusieron swaps.")
            return deck

        # Construir lookup del pool no incluido
        pool_lookup = {c["name"].lower(): c for c in pool_not_included}

        applied = 0
        for swap in swaps:
            remove_name = swap.get("remove", "").strip()
            add_name = swap.get("add", "").strip()
            reason = swap.get("reason", "")

            if not remove_name or not add_name:
                continue

            # Verificar que la carta a añadir está en el pool
            add_card = pool_lookup.get(add_name.lower())
            if not add_card:
                if self.verbose:
                    print(f"  [CRITIC] SKIP: '{add_name}' no encontrada en pool")
                continue

            # Verificar que la carta a eliminar está en el mazo
            remove_idx = next(
                (i for i, dc in enumerate(deck.cards)
                 if dc.card["name"].lower() == remove_name.lower()),
                None
            )
            if remove_idx is None:
                if self.verbose:
                    print(f"  [CRITIC] SKIP: '{remove_name}' no está en el mazo")
                continue

            # Aplicar swap
            removed_dc = deck.cards[remove_idx]
            from .builder import DeckCard
            deck.cards[remove_idx] = DeckCard(
                card=add_card,
                category=removed_dc.category,
                role=removed_dc.role,
                justification=f"[CRITIC] {reason}",
            )

            if self.verbose:
                print(f"  [CRITIC] ✓ -{remove_name} → +{add_name}: {reason}")
            applied += 1

        if self.verbose:
            print(f"  [CRITIC] {applied}/{len(swaps)} swaps aplicados")

        return deck
