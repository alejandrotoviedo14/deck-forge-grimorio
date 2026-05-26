"""
edhrec_advisor.py — Integración con EDHREC para mejorar la selección de cartas.

Consulta EDHREC para obtener las cartas recomendadas para un comandante específico,
las cruza con tu pool real, y genera un ranking de candidatos basado en:
  - Sinergia EDHREC (qué tan específica es la carta para este comandante)
  - Inclusión en decks reales (validación comunitaria)
  - Disponibilidad en tu colección

REQUISITOS:
    pip install pyedhrec
"""

import time
import json
from pathlib import Path
from typing import Optional


CACHE_DIR = Path.home() / ".deck_forge_cache" / "edhrec"
CACHE_TTL_HOURS = 48


def _cache_path(commander_name: str) -> Path:
    safe = commander_name.lower().replace(" ", "_").replace(",", "").replace("'", "")
    return CACHE_DIR / f"{safe}.json"


def _load_cache(commander_name: str) -> Optional[dict]:
    path = _cache_path(commander_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        age_hours = (time.time() - data.get("cached_at", 0)) / 3600
        if age_hours > CACHE_TTL_HOURS:
            return None
        return data
    except Exception:
        return None


def _save_cache(commander_name: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data["cached_at"] = time.time()
    _cache_path(commander_name).write_text(json.dumps(data, indent=2))


def _parse_cards_from_response(raw: any) -> dict[str, dict]:
    """
    Parsea la respuesta de pyedhrec (cualquier formato) a {card_name: {synergy, inclusion}}.
    Maneja: dict con listas, lista directa, strings, etc.
    """
    result = {}
    if not raw:
        return result

    # Si es dict, iterar por valores
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        name = item.get("name")
                        if name:
                            result[name] = {
                                "synergy":         item.get("synergy", 0),
                                "inclusion":       item.get("inclusion", 0),
                                "potential_decks": item.get("potential_decks", 1),
                            }
                    elif isinstance(item, str) and item:
                        # Algunos endpoints devuelven strings directamente
                        result[item] = {"synergy": 0.1, "inclusion": 0, "potential_decks": 1}
            elif isinstance(value, dict):
                name = value.get("name")
                if name:
                    result[name] = {
                        "synergy":   value.get("synergy", 0),
                        "inclusion": value.get("inclusion", 0),
                        "potential_decks": value.get("potential_decks", 1),
                    }
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                name = item.get("name")
                if name:
                    result[name] = {
                        "synergy":   item.get("synergy", 0),
                        "inclusion": item.get("inclusion", 0),
                        "potential_decks": item.get("potential_decks", 1),
                    }
            elif isinstance(item, str) and item:
                result[item] = {"synergy": 0.1, "inclusion": 0, "potential_decks": 1}

    return result


class EDHRecAdvisor:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self._edhrec = None

    def _get_client(self):
        if self._edhrec is None:
            try:
                from pyedhrec import EDHRec
                self._edhrec = EDHRec()
            except ImportError:
                raise ImportError("pip install pyedhrec")
        return self._edhrec

    def fetch_commander_data(self, commander_name: str) -> dict:
        """
        Obtiene todos los datos EDHREC para un comandante con cache de 48h.
        Combina: high_synergy + top_cards + commander_cards (todas las categorías).
        """
        cached = _load_cache(commander_name)
        if cached:
            n = len(cached.get("all_cards", {}))
            if self.verbose:
                print(f"  [EDHREC] Cache hit para '{commander_name}' ({n} cartas)")
            return cached

        if self.verbose:
            print(f"  [EDHREC] Consultando EDHREC para '{commander_name}'...")

        client = self._get_client()
        result = {
            "commander":   commander_name,
            "high_synergy": {},
            "all_cards":   {},  # unión de todas las fuentes
        }

        # 1. High synergy (cartas más específicas para este comandante)
        try:
            raw = client.get_high_synergy_cards(commander_name)
            parsed = _parse_cards_from_response(raw)
            result["high_synergy"] = parsed
            result["all_cards"].update(parsed)
            if self.verbose:
                print(f"  [EDHREC] {len(parsed)} high-synergy cards")
        except Exception as e:
            if self.verbose:
                print(f"  [EDHREC] WARN high_synergy: {e}")
        time.sleep(0.3)

        # 2. Top cards (las más populares)
        try:
            raw = client.get_top_cards(commander_name)
            parsed = _parse_cards_from_response(raw)
            # Merge: si ya existe, combinar synergy scores
            for name, data in parsed.items():
                if name in result["all_cards"]:
                    existing = result["all_cards"][name]
                    # Promedio ponderado: high_synergy tiene más peso
                    existing["synergy"] = max(existing["synergy"], data["synergy"])
                    existing["inclusion"] = max(existing["inclusion"], data["inclusion"])
                else:
                    result["all_cards"][name] = data
            if self.verbose:
                print(f"  [EDHREC] {len(parsed)} top cards")
        except Exception as e:
            if self.verbose:
                print(f"  [EDHREC] WARN top_cards: {e}")
        time.sleep(0.3)

        # 3. Commander cards (todas las categorías: creatures, instants, etc.)
        try:
            raw = client.get_commander_cards(commander_name)
            parsed = _parse_cards_from_response(raw)
            for name, data in parsed.items():
                if name not in result["all_cards"]:
                    result["all_cards"][name] = data
                else:
                    result["all_cards"][name]["inclusion"] = max(
                        result["all_cards"][name]["inclusion"],
                        data["inclusion"]
                    )
            if self.verbose:
                print(f"  [EDHREC] {len(parsed)} commander cards total")
        except Exception as e:
            if self.verbose:
                print(f"  [EDHREC] WARN commander_cards: {e}")
        time.sleep(0.3)

        if self.verbose:
            print(f"  [EDHREC] Total único: {len(result['all_cards'])} cartas conocidas")

        _save_cache(commander_name, result)
        return result

    def score_card(self, card_name: str, edhrec_data: dict) -> float:
        """
        Score [0,1] para una carta dado el contexto del comandante.
        
        0.9+ = en high_synergy con synergy alto → pieza clave del arquetipo
        0.6-0.8 = en all_cards con buena inclusión → carta sólida para el plan
        0.3 = no aparece en EDHREC → neutral (puede ser buena, simplemente menos jugada)
        """
        hs = edhrec_data.get("high_synergy", {}).get(card_name)
        ac = edhrec_data.get("all_cards", {}).get(card_name)

        if not hs and not ac:
            return 0.3  # neutral — no penaliza cartas nuevas/raras

        score = 0.0

        if hs:
            # High synergy: peso máximo
            synergy_val = max(0, hs.get("synergy", 0))
            potential = max(hs.get("potential_decks", 1), 1)
            inclusion_rate = hs.get("inclusion", 0) / potential
            hs_score = 0.6 * synergy_val + 0.4 * min(inclusion_rate, 1.0)
            score = 0.4 + hs_score * 0.6  # base 0.4, max 1.0
        elif ac:
            # En all_cards pero no high_synergy: buena pero no única
            synergy_val = max(0, ac.get("synergy", 0))
            inclusion = ac.get("inclusion", 0)
            inclusion_norm = min(inclusion / 1000, 1.0)
            score = 0.35 + inclusion_norm * 0.30 + synergy_val * 0.15

        return min(score, 1.0)

    def rank_pool_for_commander(
        self,
        commander_name: str,
        pool: list[dict],
    ) -> list[dict]:
        """
        Enriquece el pool con edhrec_score y lo ordena por relevancia.
        Cartas no en EDHREC reciben 0.3 (neutral, no penalizadas).
        """
        try:
            edhrec_data = self.fetch_commander_data(commander_name)
        except Exception as e:
            if self.verbose:
                print(f"  [EDHREC] ERROR: {e}. Usando scoring local.")
            return pool

        hits = 0
        for card in pool:
            name = card.get("name", "")
            s = self.score_card(name, edhrec_data)
            card["edhrec_score"] = s
            if s > 0.3:
                hits += 1

        ranked = sorted(pool, key=lambda c: -c.get("edhrec_score", 0.3))

        if self.verbose:
            print(f"  [EDHREC] {hits}/{len(pool)} cartas del pool reconocidas por EDHREC")
            print(f"  [EDHREC] Top 10 del pool para '{commander_name}':")
            for c in ranked[:10]:
                print(f"    {c['edhrec_score']:.2f} — {c['name']}")

        return ranked

    def get_missing_recommendations(
        self,
        commander_name: str,
        pool: list[dict],
        top_n: int = 15,
    ) -> list[dict]:
        """
        Cartas que EDHREC recomienda pero que NO están en tu pool.
        Útil para sugerencias de compra.
        """
        try:
            edhrec_data = self.fetch_commander_data(commander_name)
        except Exception as e:
            if self.verbose:
                print(f"  [EDHREC] ERROR: {e}")
            return []

        pool_names = {c.get("name", "").lower() for c in pool}
        missing = []

        for name, data in edhrec_data.get("high_synergy", {}).items():
            if name.lower() not in pool_names:
                missing.append({
                    "name":      name,
                    "synergy":   data.get("synergy", 0),
                    "inclusion": data.get("inclusion", 0),
                    "url":       "https://edhrec.com/cards/" + name.lower().replace(" ", "-").replace(",", "").replace("'", ""),
                })

        missing.sort(key=lambda x: -x["synergy"])
        return missing[:top_n]
