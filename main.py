"""
main.py — Deck Forge Web API

Endpoints:
  POST /api/ingest          — sube real.csv (+ fake.csv opcional) → devuelve collection JSON
  POST /api/build           — construye 1 mazo → devuelve HTML + archivos de exportación
  POST /api/multi           — construye N mazos → devuelve HTML combinado
  POST /api/analyze         — analiza el pool → devuelve top comandantes
  POST /api/upgrade         — propone swaps para subir bracket
  GET  /                    — UI web
"""

import io
import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).parent))

from core.pool import load_collection, build_real_pool
from core.builder import build_deck
from core.bracket import estimate_bracket, estimate_max_bracket_for_pool
from core.exporters import (
    to_moxfield_txt,
    to_manabox_csv,
    to_html_multi,
    build_multi_html_from_index,
    _build_deck_data_json,
)
from core.archetypes import ARCHETYPES
from core.deck_index import register_deck, load_index, save_index

app = FastAPI(title="Deck Forge API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directorio temporal para archivos de trabajo por sesión
_WORK_DIR = Path(tempfile.mkdtemp(prefix="deck_forge_"))
_DECKS_DIR = _WORK_DIR / "decks"
_DECKS_DIR.mkdir(parents=True, exist_ok=True)

# Directorio PERSISTENTE para colecciones con PIN
# En Railway: /data (volumen montado). En local: ~/.deck_forge_cache/collections
_PERSISTENT_BASE = Path(os.environ.get("DECK_FORGE_CACHE", str(Path.home() / ".deck_forge_cache")))
_COLLECTIONS_DIR = _PERSISTENT_BASE / "collections"
_COLLECTIONS_DIR.mkdir(parents=True, exist_ok=True)

# Directorio temporal de colecciones en sesión (para las no guardadas con PIN)
_SESSION_COLLECTIONS_DIR = _WORK_DIR / "collections"
_SESSION_COLLECTIONS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def _save_upload(upload: UploadFile, dest: Path) -> Path:
    dest.write_bytes(upload.file.read())
    return dest


def _build_sim_cards(deck) -> list[dict]:
    """Construye la lista de 99 cartas para el simulador (sin el comandante)."""
    BASIC_NAMES = {
        "W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"
    }
    BASIC_IDS = {
        "Plains":   "bc8d829c-22f9-4a35-bb4c-a0dfd7ab18a0",
        "Island":   "b278f8b3-7799-4a67-a81b-96e61aa28f8e",
        "Swamp":    "72b4d0b9-40f3-4a1e-8cf6-baab3bf3e4fc",
        "Mountain": "f0e9fb8a-cc60-4e79-b6de-54e4e73d8873",
        "Forest":   "a3fb7228-e76b-4240-a9b1-58a9c7ab98d2",
    }

    def scryfall_img(sid):
        if not sid or len(sid) < 2: return ""
        return f"https://cards.scryfall.io/normal/front/{sid[0]}/{sid[1]}/{sid}.jpg"

    cards = []
    for dc in deck.cards:
        c = dc.card
        sid = c.get("scryfall_id") or c.get("id") or ""
        cards.append({
            "name": c.get("name", ""),
            "scryfall_id": sid,
            "img": scryfall_img(sid),
            "type_line": c.get("type_line", ""),
            "cmc": int(c.get("cmc") or 0),
            "is_land": bool(c.get("is_land")),
            "category": dc.category,
            "role": dc.role,
        })

    # Añadir básicas
    colors = deck.colors or "W"
    needed = deck.needed_basics
    basics_per_color = {c: 0 for c in colors}
    per = needed // len(colors)
    rem = needed % len(colors)
    for i, c in enumerate(colors):
        basics_per_color[c] = per + (1 if i < rem else 0)

    for color, count in basics_per_color.items():
        name = BASIC_NAMES.get(color, "Plains")
        sid = BASIC_IDS.get(name, "")
        for _ in range(count):
            cards.append({
                "name": name,
                "scryfall_id": sid,
                "img": scryfall_img(sid),
                "type_line": "Basic Land",
                "cmc": 0,
                "is_land": True,
                "category": "Tierras Básicas",
                "role": "Land",
            })

    return cards


def _csv_from_collection(coll: dict) -> str:
    """
    Sintetiza un CSV en formato ManaBox a partir de la colección enriquecida.
    Permite forjar/exportar sin necesidad de re-subir el CSV original
    (la colección ya tiene scryfall_id, set, collector_number, etc.).
    """
    import csv as csv_mod
    out = io.StringIO()
    w = csv_mod.writer(out)
    w.writerow([
        "Name", "Set code", "Set name", "Collector number", "Foil", "Rarity",
        "Quantity", "ManaBox ID", "Scryfall ID", "Purchase price",
        "Misprint", "Altered", "Condition", "Language", "Purchase price currency",
    ])
    for card in coll.get("real", []):
        w.writerow([
            card.get("name", ""),
            card.get("set", ""),
            card.get("set_name", ""),
            card.get("collector_number", ""),
            card.get("foil", "normal"),
            card.get("rarity", ""),
            card.get("quantity", 1),
            card.get("manabox_id", ""),
            card.get("scryfall_id", ""),
            "", "false", "false",
            card.get("condition", "near_mint"),
            card.get("language", "en"),
            "EUR",
        ])
    return out.getvalue()


def _load_basics_from_bytes(content: bytes) -> dict:
    import csv as csv_mod
    basics = {}
    reader = csv_mod.DictReader(io.StringIO(content.decode("utf-8")))
    for row in reader:
        name = row.get("Name", "")
        if name in ("Plains", "Island", "Swamp", "Mountain", "Forest"):
            if name not in basics:
                basics[name] = {
                    "set_code": row.get("Set code", ""),
                    "set_name": row.get("Set name", ""),
                    "collector_number": row.get("Collector number", ""),
                    "foil": row.get("Foil", "normal"),
                    "rarity": row.get("Rarity", ""),
                    "manabox_id": row.get("ManaBox ID", ""),
                    "scryfall_id": row.get("Scryfall ID", ""),
                    "language": row.get("Language", "en"),
                    "condition": row.get("Condition", "near_mint"),
                }
    return basics


# ---------------------------------------------------------------------------
# Rutas estáticas
# ---------------------------------------------------------------------------

# Servir fuentes locales y assets estáticos
_WEB_DIR = Path(__file__).parent / "web"
if (_WEB_DIR / "fonts").exists():
    app.mount("/fonts", StaticFiles(directory=str(_WEB_DIR / "fonts")), name="fonts")

@app.get("/", response_class=HTMLResponse)
async def index():
    ui = Path(__file__).parent / "web" / "index.html"
    if ui.exists():
        return HTMLResponse(ui.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Deck Forge API</h1><p>Docs: <a href='/docs'>/docs</a></p>")

@app.get("/simulator", response_class=HTMLResponse)
async def simulator():
    ui = Path(__file__).parent / "web" / "simulator.html"
    if ui.exists():
        return HTMLResponse(ui.read_text(encoding="utf-8"))
    return HTMLResponse("<p>Simulador no disponible</p>")


# ---------------------------------------------------------------------------
# Supabase helpers para PINs persistentes
# ---------------------------------------------------------------------------

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

def _supa_headers() -> dict:
    return {
        "apikey": _SUPABASE_KEY,
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

def _supa_available() -> bool:
    return bool(_SUPABASE_URL and _SUPABASE_KEY)

def _generate_pin() -> str:
    import random, requests as req
    for _ in range(20):
        pin = str(random.randint(100000, 999999))
        if _supa_available():
            r = req.get(f"{_SUPABASE_URL}/rest/v1/pins?pin=eq.{pin}&select=pin",
                        headers=_supa_headers(), timeout=5)
            if r.status_code == 200 and not r.json():
                return pin
        else:
            if not (_COLLECTIONS_DIR / f"{pin}.json").exists():
                return pin
    return str(random.randint(100000, 999999))

def _supa_save_pin(pin: str, name: str, real_count: int, uploaded_at: str, collection: dict) -> bool:
    """Guarda colección en Supabase. Devuelve True si OK."""
    if not _supa_available():
        return False
    import requests as req
    payload = {
        "pin": pin,
        "name": name,
        "real_count": real_count,
        "uploaded_at": uploaded_at,
        "collection": collection,
    }
    r = req.post(f"{_SUPABASE_URL}/rest/v1/pins",
                 headers={**_supa_headers(), "Prefer": "return=minimal"},
                 json=payload, timeout=30)
    return r.status_code in (200, 201)

def _supa_load_pin(pin: str) -> dict | None:
    """Carga colección desde Supabase por PIN."""
    if not _supa_available():
        return None
    import requests as req
    r = req.get(f"{_SUPABASE_URL}/rest/v1/pins?pin=eq.{pin}&select=*",
                headers=_supa_headers(), timeout=15)
    if r.status_code == 200 and r.json():
        return r.json()[0]
    return None


def _supa_save_deck(pin: str, deck_key: str, commander: str, archetype: str,
                    colors: str, bracket: int, deck_data: dict) -> bool:
    """Guarda/actualiza un mazo en Supabase vinculado a un PIN."""
    if not _supa_available():
        return False
    try:
        import requests as req
        payload = {
            "pin": pin, "deck_key": deck_key, "commander": commander,
            "archetype": archetype, "colors": colors, "bracket": bracket,
            "deck_data": deck_data,
        }
        r = req.post(
            f"{_SUPABASE_URL}/rest/v1/decks",
            headers={**_supa_headers(), "Prefer": "resolution=merge-duplicates"},
            json=payload, timeout=30,
        )
        return r.status_code in (200, 201)
    except Exception:
        return False


def _supa_load_decks(pin: str) -> list[dict]:
    """Carga todos los mazos de un PIN desde Supabase."""
    if not _supa_available():
        return []
    import requests as req
    r = req.get(f"{_SUPABASE_URL}/rest/v1/decks?pin=eq.{pin}&select=*",
                headers=_supa_headers(), timeout=15)
    if r.status_code == 200:
        return r.json()
    return []


def _supa_delete_deck(pin: str, deck_key: str) -> bool:
    """Borra un mazo concreto de un PIN en Supabase."""
    if not _supa_available():
        return False
    try:
        import requests as req
        r = req.delete(
            f"{_SUPABASE_URL}/rest/v1/decks?pin=eq.{pin}&deck_key=eq.{deck_key}",
            headers=_supa_headers(), timeout=15,
        )
        return r.status_code in (200, 204)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# GET /api/collections — lista colecciones de la sesión actual
# ---------------------------------------------------------------------------

@app.get("/api/collections")
async def list_collections():
    """Lista colecciones de la sesión (no persistentes sin PIN)."""
    cols = []
    for f in sorted(_SESSION_COLLECTIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            meta = json.loads((_SESSION_COLLECTIONS_DIR / f"{f.stem}.meta.json").read_text())
        except Exception:
            meta = {}
        cols.append({
            "id": f.stem,
            "name": meta.get("name", f.stem),
            "real_count": meta.get("real_count", 0),
            "uploaded_at": meta.get("uploaded_at", ""),
            "pin": meta.get("pin"),
        })
    return {"collections": cols}


# ---------------------------------------------------------------------------
# POST /api/collections/save — guarda colección con PIN persistente
# ---------------------------------------------------------------------------

@app.post("/api/collections/save")
async def save_collection(
    collection: str = Form(...),
    name: str = Form(...),
):
    """Guarda una colección con PIN persistente y en la sesión actual."""
    import time
    try:
        coll = json.loads(collection)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pin = _generate_pin()
    col_id = _safe_filename(name) or f"col_{int(time.time())}"
    real_count = len(coll.get("real", []))
    uploaded_at = time.strftime("%Y-%m-%d %H:%M")
    meta = {"name": name, "id": col_id, "pin": pin,
            "real_count": real_count, "uploaded_at": uploaded_at}

    # Guardar en Supabase (persistente) + sesión local
    supa_ok = _supa_save_pin(pin, name, real_count, uploaded_at, coll)

    # Fallback: archivo local si Supabase no disponible
    if not supa_ok:
        (_COLLECTIONS_DIR / f"{pin}.json").write_text(
            json.dumps(coll, ensure_ascii=False), encoding="utf-8")
        (_COLLECTIONS_DIR / f"{pin}.meta.json").write_text(
            json.dumps(meta), encoding="utf-8")

    # Sesión local para acceso rápido sin re-consultar Supabase
    (_SESSION_COLLECTIONS_DIR / f"{col_id}.json").write_text(
        json.dumps(coll, ensure_ascii=False), encoding="utf-8")
    (_SESSION_COLLECTIONS_DIR / f"{col_id}.meta.json").write_text(
        json.dumps(meta), encoding="utf-8")

    return {"ok": True, "id": col_id, "name": name, "pin": pin,
            "persistent": supa_ok}


# ---------------------------------------------------------------------------
# POST /api/sessions/restore — restaura colección por PIN
# ---------------------------------------------------------------------------

@app.post("/api/sessions/restore")
async def restore_session(pin: str = Form(...)):
    """Restaura una colección a partir de su PIN."""
    pin = pin.strip()

    # Buscar en Supabase primero
    row = _supa_load_pin(pin)
    if row:
        coll = row["collection"]
        meta = {"name": row["name"], "id": _safe_filename(row["name"]) or f"pin_{pin}",
                "pin": pin, "real_count": row["real_count"]}
    else:
        # Fallback: archivo local
        path = _COLLECTIONS_DIR / f"{pin}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="PIN no encontrado. Comprueba que es correcto.")
        meta_path = _COLLECTIONS_DIR / f"{pin}.meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        coll = json.loads(path.read_text(encoding="utf-8"))

    col_id = meta.get("id", f"pin_{pin}")

    # Registrar colección en sesión actual
    (_SESSION_COLLECTIONS_DIR / f"{col_id}.json").write_text(
        json.dumps(coll, ensure_ascii=False), encoding="utf-8"
    )
    (_SESSION_COLLECTIONS_DIR / f"{col_id}.meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )

    # Restaurar mazos vinculados al PIN
    supa_decks = _supa_load_decks(pin)
    restored_decks = []
    for d in supa_decks:
        dd = d.get("deck_data", {})
        try:
            register_deck(
                output_dir=_DECKS_DIR,
                deck_key=d["deck_key"],
                commander_card=dd.get("commander_card", {}),
                archetype_key=dd.get("archetype_key", ""),
                colors=dd.get("colors", ""),
                bracket=dd.get("bracket", 1),
                bracket_score=dd.get("bracket_score", 0),
                cards=dd.get("cards", []),
                needed_basics=dd.get("needed_basics", 37),
                html_data=dd.get("html_data", {}),
            )
            restored_decks.append({
                "key": d["deck_key"],
                "commander": d.get("commander", ""),
                "archetype": d.get("archetype", ""),
                "bracket": d.get("bracket", 1),
            })
        except Exception:
            pass

    return {
        "ok": True,
        "id": col_id,
        "name": meta.get("name", "Mi Colección"),
        "real_count": len(coll.get("real", [])),
        "pin": pin,
        "collection": coll,
        "decks_restored": restored_decks,
    }


# ---------------------------------------------------------------------------
# GET /api/collections/{id} — carga una colección de la sesión
# ---------------------------------------------------------------------------

@app.get("/api/collections/{col_id}")
async def get_collection(col_id: str):
    # Buscar primero en sesión, luego por PIN
    session_path = _SESSION_COLLECTIONS_DIR / f"{col_id}.json"
    if session_path.exists():
        return json.loads(session_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="Colección no encontrada")


# ---------------------------------------------------------------------------
# POST /api/ingest
# ---------------------------------------------------------------------------

@app.post("/api/ingest")
async def ingest(
    real_csv: UploadFile = File(..., description="CSV de ManaBox (real.csv)"),
    fake_csv: UploadFile | None = File(None, description="CSV de proxies (fake.csv)"),
):
    """
    Procesa los CSV de ManaBox y devuelve la colección enriquecida.
    Usa ingest.py internamente (Scryfall bulk, cacheado en el servidor).
    """
    import subprocess

    work = _WORK_DIR / "upload"
    work.mkdir(exist_ok=True)

    real_path = work / "real.csv"
    _save_upload(real_csv, real_path)

    cmd = [sys.executable, str(Path(__file__).parent / "ingest.py"),
           "--real", str(real_path),
           "--output", str(work / "collection_enriched.json")]

    if fake_csv:
        fake_path = work / "fake.csv"
        _save_upload(fake_csv, fake_path)
        cmd += ["--fake", str(fake_path)]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).parent))
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr[-2000:])

    collection_path = work / "collection_enriched.json"
    if not collection_path.exists():
        raise HTTPException(status_code=500, detail="ingest.py no generó collection_enriched.json")

    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    return {
        "ok": True,
        "real_count": len(collection.get("real", [])),
        "fake_count": len(collection.get("fake", [])),
        "collection": collection,
    }


# ---------------------------------------------------------------------------
# POST /api/analyze
# ---------------------------------------------------------------------------

@app.post("/api/analyze")
async def analyze(
    collection: str = Form(..., description="JSON string de collection_enriched"),
    min_colors: int = Form(2),
    top: int = Form(20),
):
    """Analiza el pool y devuelve top comandantes con scores."""
    from core.commander_score import score_commanders

    try:
        coll = json.loads(collection)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"collection JSON inválido: {e}")

    pool = build_real_pool(coll)
    pool_names = {c["name"].lower() for c in pool}
    pool_by_name = {c["name"].lower(): c for c in pool}
    max_b, reason = estimate_max_bracket_for_pool(pool)
    # use_edhrec=False para el scoring inicial (ya hacemos fetch separado abajo)
    # evitamos llamar EDHREC dos veces por comandante
    scores = score_commanders(pool, min_colors=min_colors, require_legal=False, use_edhrec=False)

    # Enriquecimiento asíncrono-ish: EDHREC themes, combos, precio, relevancia
    # Solo para el top-N para no sobrecargar
    enriched_commanders = []
    for s in scores[:top]:
        entry = {
            "name":            s.name,
            "colors":          s.colors,
            "archetype":       s.archetype.key  if s.archetype else None,
            "archetype_name":  s.archetype.name if s.archetype else None,
            "total_score":     round(s.total_score,   1),
            "synergy_density": round(s.synergy_density, 1),
            "bracket_ceiling": round(s.bracket_ceiling, 2),
            "rank_score":      round(s.rank_score, 1),
            # Campos enriquecidos (rellenados abajo)
            "themes":             [],
            "combos_in_pool":     0,
            "pool_relevance_pct": round(s.edhrec_relevance, 1),  # ya calculado en score
            "est_price_eur":      None,
        }

        # Temas EDHREC (llamada ligera usando cache ya precargado por score_commanders)
        try:
            from core.edhrec_advisor import EDHRecAdvisor
            _adv = EDHRecAdvisor(verbose=False)
            _edata = _adv.fetch_commander_data(s.name)
            entry["themes"] = _edata.get("themes", [])[:5]
        except Exception:
            pass

        # Combos disponibles en el pool para esta identidad
        try:
            from core.combo_advisor import find_combos_in_pool
            combo_res = find_combos_in_pool(pool_names, s.colors, s.name, verbose=False)
            entry["combos_in_pool"] = len(combo_res.get("complete", []))
        except Exception:
            pass

        # Precio estimado: suma las top-60 cartas del pool más relevantes para este color
        try:
            from core.price_advisor import calculate_deck_price, card_price_eur
            color_set = set(s.colors)
            relevant_pool = [
                c for c in pool
                if set(c.get("color_identity") or []).issubset(color_set)
            ]
            # Tomar las 60 más populares (por edhrec_rank)
            relevant_pool.sort(key=lambda c: c.get("edhrec_rank") or 999999)
            price_stats = calculate_deck_price(relevant_pool[:60])
            entry["est_price_eur"] = price_stats.get("total_eur")
        except Exception:
            pass

        enriched_commanders.append(entry)

    return {
        "pool_size": len(pool),
        "max_bracket": max_b,
        "max_bracket_reason": reason,
        "commanders": enriched_commanders,
    }


# ---------------------------------------------------------------------------
# POST /api/build
# ---------------------------------------------------------------------------

@app.post("/api/build")
async def build(
    collection: str = Form(..., description="JSON string de collection_enriched"),
    real_csv: UploadFile = File(None, description="CSV original de ManaBox (opcional)"),
    commander: str | None = Form(None),
    colors: str | None = Form(None),
    archetype: str | None = Form(None),
    use_edhrec: bool = Form(True),
    pin: str | None = Form(None),
    allowed_shared: str | None = Form(None),  # JSON array de nombres que el usuario permite compartir
):
    """Construye un mazo y devuelve HTML + exportaciones."""
    import traceback
    try:
        coll = json.loads(collection)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"collection JSON inválido: {e}")

    # CSV opcional: si no se sube, se sintetiza desde la colección enriquecida.
    # Esto permite forjar desde una colección guardada/restaurada por PIN sin re-subir.
    real_bytes = b""
    if real_csv is not None:
        try:
            real_bytes = await real_csv.read()
        except Exception:
            real_bytes = b""
    if not real_bytes:
        real_bytes = _csv_from_collection(coll).encode("utf-8")

    basics = _load_basics_from_bytes(real_bytes)
    pool = build_real_pool(coll)

    # Cartas que el usuario explícitamente permite compartir
    user_allowed: set[str] = set()
    if allowed_shared:
        try:
            user_allowed = {n.lower() for n in json.loads(allowed_shared)}
        except Exception:
            pass

    # Cargar cartas reservadas por otros mazos del mismo PIN
    reserved_cards: dict[str, str] = {}  # {card_name_lower: commander_del_mazo_dueño}
    if pin and pin.strip():
        try:
            other_decks = _supa_load_decks(pin.strip())
            for d in other_decks:
                owner = d.get("commander", d.get("deck_key", "?"))
                dd = d.get("deck_data", {})
                for c in dd.get("cards", []):
                    card_name = c.get("name", "")
                    if card_name and card_name.lower() not in user_allowed:
                        reserved_cards[card_name.lower()] = owner
        except Exception as e:
            print(f"  [RESERVED] Error cargando reservas: {e}")

    try:
        deck = build_deck(
            pool,
            commander_name=commander,
            colors=colors,
            archetype_key=archetype,
            use_edhrec=use_edhrec,
            reserved_cards=reserved_cards if reserved_cards else None,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # NOTA: El LLM Critic + guía de juego ya se ejecutan DENTRO de build_deck()
    # con el contexto correcto (pool filtrado por color + EDHREC + reservas).
    # No volver a llamarlo aquí (causaba doble coste y sobrescritura con peor contexto).

    full_list = deck.all_cards_with_basics(basics)
    bracket = estimate_bracket(full_list)

    # Generar key versionado — nunca sobrescribir un mazo existente del mismo comandante
    base_key = _safe_filename(deck.commander["name"])
    existing_index = load_index(_DECKS_DIR)
    existing_decks = existing_index.get("decks", {})
    safe = base_key
    version = 1
    while safe in existing_decks:
        version += 1
        safe = f"{base_key}_v{version}"

    # Guardar en directorio temporal del servidor
    deck_dir = _DECKS_DIR
    mox_path = deck_dir / f"{safe}_moxfield.txt"
    csv_path = deck_dir / f"{safe}_manabox.csv"

    # Guardar el CSV real temporalmente para to_manabox_csv
    tmp_real = _WORK_DIR / "upload" / "real.csv"
    tmp_real.parent.mkdir(parents=True, exist_ok=True)
    tmp_real.write_bytes(real_bytes)

    mox_path.write_text(to_moxfield_txt(deck, basics), encoding="utf-8")
    csv_path.write_text(to_manabox_csv(deck, str(tmp_real), basics), encoding="utf-8")

    html_data = _build_deck_data_json(deck, bracket)

    # Añadir conflictos al html_data para mostrarlos en el grimorio
    html_data["conflicts"] = [
        {
            "card": c.card_name,
            "reserved_by": c.reserved_by,
            "alternative": c.alternative,
            "slot": c.slot,
        }
        for c in deck.conflicts
    ]

    # ── SINERGIAS y ESTADÍSTICAS del mazo ────────────────────────────────
    try:
        from core.synergy_detector import detect_synergies, compute_deck_stats
        all_deck_cards_dicts = [dc.card for dc in deck.cards]
        synergy_packages = detect_synergies(all_deck_cards_dicts)
        deck_stats = compute_deck_stats(all_deck_cards_dicts)
        html_data["synergy_packages"] = synergy_packages
        html_data["deck_stats"]       = deck_stats
        # Mapa {nombre_carta → sinergias} para el tooltip
        from core.synergy_detector import build_card_synergy_map
        html_data["card_synergy_map"] = build_card_synergy_map(
            all_deck_cards_dicts, synergy_packages
        )
    except Exception as e:
        print(f"  [SYNERGY] Error: {e}")
        html_data["synergy_packages"] = []
        html_data["deck_stats"]       = {}
        html_data["card_synergy_map"] = {}

    # ── PRECIOS del mazo ──────────────────────────────────────────────────
    try:
        from core.price_advisor import calculate_deck_price
        all_deck_cards = [dc.card for dc in deck.cards]
        price_stats = calculate_deck_price(all_deck_cards)
        html_data["price"] = price_stats
    except Exception as e:
        print(f"  [PRICE] Error calculando precios: {e}")
        html_data["price"] = {}

    # ── EDHREC themes e inclusión ─────────────────────────────────────────
    try:
        from core.edhrec_advisor import EDHRecAdvisor
        _edhrec_adv = EDHRecAdvisor(verbose=False)
        _edhrec_data = _edhrec_adv.fetch_commander_data(deck.commander["name"])
        html_data["edhrec_themes"] = _edhrec_data.get("themes", [])
        # Top 10 cartas por inclusion_pct para mostrar en el grimorio
        all_cards = _edhrec_data.get("all_cards", {})
        top_inc = sorted(
            [{"name": n, "inclusion_pct": v.get("inclusion_pct", 0), "synergy": round(v.get("synergy", 0), 2)}
             for n, v in all_cards.items() if v.get("inclusion_pct", 0) > 0],
            key=lambda x: -x["inclusion_pct"]
        )[:12]
        html_data["edhrec_top_inclusion"] = top_inc
    except Exception as e:
        print(f"  [EDHREC THEMES] {e}")
        html_data["edhrec_themes"] = []
        html_data["edhrec_top_inclusion"] = []

    # ── COMBOS del mazo (Commander Spellbook) ─────────────────────────────
    try:
        from core.combo_advisor import find_combos_in_pool
        pool_names = {dc.card.get("name","") for dc in deck.cards} | {deck.commander.get("name","")}
        combo_results = find_combos_in_pool(
            pool_names, deck.colors, deck.commander.get("name",""), verbose=True
        )
        html_data["combos"] = combo_results
    except Exception as e:
        print(f"  [COMBOS] Error detectando combos: {e}")
        html_data["combos"] = {"complete": [], "near_1": [], "near_2": []}

    register_deck(
        output_dir=deck_dir,
        deck_key=safe,
        commander_card=deck.commander,
        archetype_key=deck.archetype.key,
        colors=deck.colors,
        bracket=bracket.bracket,
        bracket_score=bracket.score,
        cards=[dc.card for dc in deck.cards],
        needed_basics=deck.needed_basics,
        html_data=html_data,
    )

    try:
        index = load_index(deck_dir)
        grimorio_html = build_multi_html_from_index(deck_dir, index.get("decks", {}))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando grimorio HTML: {e}\n{traceback.format_exc()}")

    # Preparar lista de cartas para el simulador
    try:
        sim_cards = _build_sim_cards(deck)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error preparando simulador: {e}\n{traceback.format_exc()}")

    # Guardar mazo en Supabase vinculado al PIN si se proporcionó
    saved_to_pin = False
    if pin and pin.strip():
        try:
            full_deck_data = {
                "commander_card": deck.commander,
                "archetype_key": deck.archetype.key,
                "colors": deck.colors,
                "bracket": bracket.bracket,
                "bracket_score": round(bracket.score, 2),
                "cards": [dc.card for dc in deck.cards],
                "needed_basics": deck.needed_basics,
                "html_data": html_data,  # incluye categories con imgs
            }
            saved_to_pin = _supa_save_deck(
                pin.strip(), safe, deck.commander["name"],
                deck.archetype.key, deck.colors, bracket.bracket, full_deck_data,
            )
        except Exception as e:
            saved_to_pin = False

    return {
        "ok": True,
        "commander": deck.commander["name"],
        "archetype": deck.archetype.name,
        "colors": deck.colors,
        "card_count": deck.card_count,
        "needed_basics": deck.needed_basics,
        "bracket": bracket.bracket,
        "bracket_score": round(bracket.score, 2),
        "deck_key": safe,
        "grimorio_html": grimorio_html,
        "moxfield_txt": mox_path.read_text(encoding="utf-8"),
        "manabox_csv": csv_path.read_text(encoding="utf-8"),
        "sim_cards": sim_cards,
        "saved_to_pin": saved_to_pin,
        "conflicts": [
            {
                "card": c.card_name,
                "reserved_by": c.reserved_by,
                "alternative": c.alternative,
                "slot": c.slot,
            }
            for c in deck.conflicts
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/multi
# ---------------------------------------------------------------------------

@app.post("/api/multi")
async def multi(
    collection: str = Form(...),
    real_csv: UploadFile = File(...),
    commanders: str = Form(..., description="JSON array de nombres de comandantes"),
    use_edhrec: bool = Form(True),
):
    """Construye múltiples mazos y devuelve grimorio HTML combinado."""
    try:
        coll = json.loads(collection)
        commander_list: list[str] = json.loads(commanders)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    real_bytes = await real_csv.read()
    basics = _load_basics_from_bytes(real_bytes)
    pool = build_real_pool(coll)
    tmp_real = _WORK_DIR / "upload" / "real.csv"
    tmp_real.parent.mkdir(parents=True, exist_ok=True)
    tmp_real.write_bytes(real_bytes)

    results = []
    errors = []
    for cname in commander_list:
        try:
            deck = build_deck(pool, commander_name=cname, use_edhrec=use_edhrec)
            full = deck.all_cards_with_basics(basics)
            bracket = estimate_bracket(full)
            safe = _safe_filename(deck.commander["name"])

            (_DECKS_DIR / f"{safe}_moxfield.txt").write_text(
                to_moxfield_txt(deck, basics), encoding="utf-8"
            )
            (_DECKS_DIR / f"{safe}_manabox.csv").write_text(
                to_manabox_csv(deck, str(tmp_real), basics), encoding="utf-8"
            )

            html_data = _build_deck_data_json(deck, bracket)
            register_deck(
                output_dir=_DECKS_DIR,
                deck_key=safe,
                commander_card=deck.commander,
                archetype_key=deck.archetype.key,
                colors=deck.colors,
                bracket=bracket.bracket,
                bracket_score=bracket.score,
                cards=[dc.card for dc in deck.cards],
                needed_basics=deck.needed_basics,
                html_data=html_data,
            )
            results.append({"commander": cname, "bracket": bracket.bracket, "archetype": deck.archetype.name})
        except Exception as e:
            errors.append({"commander": cname, "error": str(e)})

    index = load_index(_DECKS_DIR)
    grimorio_html = build_multi_html_from_index(_DECKS_DIR, index.get("decks", {}))

    return {
        "ok": True,
        "built": results,
        "errors": errors,
        "grimorio_html": grimorio_html,
    }


# ---------------------------------------------------------------------------
# POST /api/upgrade
# ---------------------------------------------------------------------------

@app.post("/api/upgrade")
async def upgrade(
    collection: str = Form(...),
    deck_key: str = Form(...),
    target_bracket: int | None = Form(None),
    max_price: float = Form(10.0),
    allow_purchases: bool = Form(True),
):
    """Propone swaps para subir de bracket en un mazo ya construido."""
    from core.deck_index import get_deck
    from core.upgrader import analyze_upgrade

    try:
        coll = json.loads(collection)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    deck_data = get_deck(_DECKS_DIR, deck_key)
    if not deck_data:
        raise HTTPException(status_code=404, detail=f"Mazo '{deck_key}' no encontrado")

    pool = build_real_pool(coll)
    target = target_bracket or min(deck_data["bracket"] + 1, 4)

    try:
        report = analyze_upgrade(
            deck_cards=deck_data["cards"],
            commander=deck_data["commander_card"],
            archetype_key=deck_data["archetype"],
            pool=pool,
            target_bracket=target,
            allow_purchases=allow_purchases,
            max_price=max_price,
            min_suggestions=5,
            max_suggestions=15,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Serializar el report a dict
    report_dict = {
        "commander": deck_data["commander"],
        "current_bracket": deck_data["bracket"],
        "target_bracket": target,
        "swaps": [
            {"out": s.out.get("name", ""), "in": s.in_card.get("name", ""), "reason": s.reason}
            for s in (report.swaps or [])
        ],
        "purchases": [
            {"name": p.get("name", ""), "price": p.get("price"), "reason": p.get("reason", "")}
            for p in (report.purchases or [])
        ],
        "summary": str(report),
    }
    return report_dict


# ---------------------------------------------------------------------------
# GET /api/decks/{deck_key}/cards — cartas para el simulador
# ---------------------------------------------------------------------------

@app.get("/api/decks/{deck_key}/cards")
async def deck_cards_for_sim(deck_key: str):
    """Devuelve las 99 cartas del mazo para el simulador."""
    from core.deck_index import get_deck
    deck_data = get_deck(_DECKS_DIR, deck_key)
    if not deck_data:
        raise HTTPException(status_code=404, detail=f"Mazo '{deck_key}' no encontrado")

    BASIC_IDS = {
        "Plains":   "bc8d829c-22f9-4a35-bb4c-a0dfd7ab18a0",
        "Island":   "b278f8b3-7799-4a67-a81b-96e61aa28f8e",
        "Swamp":    "72b4d0b9-40f3-4a1e-8cf6-baab3bf3e4fc",
        "Mountain": "f0e9fb8a-cc60-4e79-b6de-54e4e73d8873",
        "Forest":   "a3fb7228-e76b-4240-a9b1-58a9c7ab98d2",
    }
    BASIC_NAMES = {"W":"Plains","U":"Island","B":"Swamp","R":"Mountain","G":"Forest"}

    def img(sid):
        if not sid or len(sid) < 2: return ""
        return f"https://cards.scryfall.io/normal/front/{sid[0]}/{sid[1]}/{sid}.jpg"

    cards = []
    for c in deck_data.get("cards", []):
        sid = c.get("scryfall_id") or c.get("id") or ""
        cards.append({
            "name": c.get("name",""),
            "scryfall_id": sid,
            "img": img(sid),
            "type_line": c.get("type_line",""),
            "cmc": int(c.get("cmc") or 0),
            "is_land": bool(c.get("is_land")),
            "category": "",
            "role": "",
        })

    colors = deck_data.get("colors", "W")
    needed = deck_data.get("needed_basics", 37)
    per = needed // max(len(colors),1)
    rem = needed % max(len(colors),1)
    for i, c in enumerate(colors):
        name = BASIC_NAMES.get(c, "Plains")
        sid = BASIC_IDS.get(name, "")
        for _ in range(per + (1 if i < rem else 0)):
            cards.append({"name":name,"scryfall_id":sid,"img":img(sid),
                          "type_line":"Basic Land","cmc":0,"is_land":True,
                          "category":"Tierras Básicas","role":"Land"})
    return {"commander": deck_data.get("commander",""), "cards": cards}


# ---------------------------------------------------------------------------
# GET /api/grimorio — devuelve el grimorio HTML actual del servidor
# ---------------------------------------------------------------------------

@app.get("/api/grimorio", response_class=HTMLResponse)
async def grimorio():
    index = load_index(_DECKS_DIR)
    if not index.get("decks"):
        return HTMLResponse("<p>No hay mazos construidos todavía. Usa /api/build primero.</p>")
    return HTMLResponse(build_multi_html_from_index(_DECKS_DIR, index["decks"]))


# ---------------------------------------------------------------------------
# GET /api/search — búsqueda Scryfall filtrada a la colección del usuario
# ---------------------------------------------------------------------------

@app.get("/api/search")
async def search_collection(
    q: str,
    collection_id: str | None = None,
):
    """
    Busca cartas con sintaxis Scryfall y filtra a las que están en la colección.
    Si collection_id no se pasa, devuelve resultados de Scryfall sin filtrar.
    """
    import urllib.request as ur
    import urllib.parse

    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Parámetro q requerido")

    UA = "Mozilla/5.0 (compatible; DeckForge/1.0)"

    # 1. Buscar en Scryfall
    url = ("https://api.scryfall.com/cards/search?"
           + urllib.parse.urlencode({"q": q.strip(), "format": "json", "page": 1}))
    req = ur.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with ur.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error Scryfall: {e}")

    scryfall_cards = data.get("data", [])
    total_scryfall = data.get("total_cards", len(scryfall_cards))

    # 2. Filtrar a la colección si hay collection_id
    collection_names: set[str] | None = None
    if collection_id:
        col_path = _SESSION_COLLECTIONS_DIR / f"{collection_id}.json"
        if col_path.exists():
            try:
                col = json.loads(col_path.read_text(encoding="utf-8"))
                collection_names = {c["name"].lower() for c in col.get("real", [])}
            except Exception:
                pass

    def _img(sid: str) -> str:
        if not sid or len(sid) < 2: return ""
        return f"https://cards.scryfall.io/normal/front/{sid[0]}/{sid[1]}/{sid}.jpg"

    results = []
    for card in scryfall_cards:
        sid  = card.get("id", "")
        name = card.get("name", "")
        in_collection = (
            collection_names is None or
            name.lower() in collection_names
        )
        prices = card.get("prices") or {}
        results.append({
            "name":          name,
            "scryfall_id":   sid,
            "img":           _img(sid),
            "type_line":     card.get("type_line", ""),
            "oracle_text":   (card.get("oracle_text") or "")[:300],
            "cmc":           int(card.get("cmc") or 0),
            "colors":        card.get("color_identity", []),
            "rarity":        card.get("rarity", ""),
            "set_name":      card.get("set_name", ""),
            "price_eur":     prices.get("eur"),
            "in_collection": in_collection,
        })

    # Ordenar: primero las de la colección
    results.sort(key=lambda c: (0 if c["in_collection"] else 1, c["name"]))

    return {
        "total_scryfall": total_scryfall,
        "total_in_collection": sum(1 for c in results if c["in_collection"]),
        "has_more": data.get("has_more", False),
        "results": results[:60],
    }


# ---------------------------------------------------------------------------
# GET /api/decks — lista mazos construidos en esta sesión
# ---------------------------------------------------------------------------

@app.get("/api/decks")
async def list_decks():
    index = load_index(_DECKS_DIR)
    decks = index.get("decks", {})
    return {
        "count": len(decks),
        "decks": [
            {
                "key": k,
                "commander": v.get("commander"),
                "archetype": v.get("archetype"),
                "colors": v.get("colors"),
                "bracket": v.get("bracket"),
            }
            for k, v in decks.items()
        ],
    }


# ---------------------------------------------------------------------------
# DELETE /api/decks/{deck_key} — borra un mazo (sesión + Supabase)
# ---------------------------------------------------------------------------

@app.delete("/api/decks/{deck_key}")
async def delete_deck(deck_key: str, pin: str | None = None):
    index = load_index(_DECKS_DIR)
    decks = index.get("decks", {})
    removed = False
    if deck_key in decks:
        del decks[deck_key]
        index["decks"] = decks
        save_index(index, _DECKS_DIR)
        removed = True
    supa_removed = False
    if pin and pin.strip():
        supa_removed = _supa_delete_deck(pin.strip(), deck_key)
    return {"ok": True, "removed": removed, "supa_removed": supa_removed}


# ---------------------------------------------------------------------------
# GET /api/pin-shared-cards — cartas de otros mazos del PIN, para el gestor
# ---------------------------------------------------------------------------

@app.get("/api/pin-shared-cards")
async def pin_shared_cards(
    pin: str,
    colors: str = "",        # identidad de color del mazo a construir (ej "WUR")
):
    """
    Devuelve las cartas de otros mazos del PIN que también encajan
    en la identidad de color dada. El usuario puede elegir cuáles excluir.
    """
    if not pin or not pin.strip():
        return {"decks": []}

    try:
        other_decks = _supa_load_decks(pin.strip())
    except Exception:
        return {"decks": []}

    color_set = set(colors.upper()) if colors else set()

    from core.exporters import _scryfall_img

    result = []
    for d in other_decks:
        owner = d.get("commander", d.get("deck_key", "?"))
        deck_key = d.get("deck_key", "")
        dd = d.get("deck_data", {})
        shared_cards = []
        for c in dd.get("cards", []):
            name = c.get("name", "")
            if not name:
                continue
            # Solo mostrar las que encajan en la identidad de color del nuevo mazo
            card_ci = set(c.get("color_identity") or [])
            if color_set and not card_ci.issubset(color_set):
                continue
            sid = c.get("scryfall_id") or ""
            shared_cards.append({
                "name": name,
                "img":  _scryfall_img(sid),
                "type": c.get("type_line", ""),
                "cmc":  int(c.get("cmc") or 0),
            })
        if shared_cards:
            result.append({
                "deck_key": deck_key,
                "commander": owner,
                "cards": sorted(shared_cards, key=lambda x: x["cmc"]),
            })

    return {"decks": result}


# ---------------------------------------------------------------------------
# POST /api/import-deck — importa un mazo exportado de ManaBox
# ---------------------------------------------------------------------------

@app.post("/api/import-deck")
async def import_deck(
    deck_csv: UploadFile = File(..., description="CSV de mazo exportado de ManaBox"),
    commander: str | None = Form(None, description="Nombre del comandante (si no se detecta)"),
    deck_name: str | None = Form(None, description="Nombre para el mazo"),
    pin: str | None = Form(None, description="PIN de sesión para guardar y detectar conflictos"),
):
    """
    Importa un mazo exportado desde ManaBox.
    Enriquece las cartas con Scryfall, detecta el comandante,
    detecta conflictos con otros mazos del mismo PIN y registra
    el mazo en el grimorio.
    """
    import csv as csv_mod
    import traceback

    raw_bytes = await deck_csv.read()
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = raw_bytes.decode("latin-1")

    # 1. Parsear el CSV
    reader = csv_mod.DictReader(io.StringIO(content))
    rows = [r for r in reader]
    if not rows:
        raise HTTPException(status_code=400, detail="El CSV está vacío o tiene formato incorrecto.")

    # 2. Cargar bulk de Scryfall para enriquecer (reutiliza el caché de ingest)
    from ingest import _download_bulk, _load_bulk_index, _extract, BULK_FILE
    try:
        _download_bulk(force=False)
        bulk_index = _load_bulk_index()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cargando datos de Scryfall: {e}")

    # 3. Enriquecer cartas del CSV
    enriched_cards: list[dict] = []
    not_found: list[str] = []
    for row in rows:
        sid = (row.get("Scryfall ID") or row.get("scryfall_id") or "").strip()
        name = (row.get("Name") or row.get("name") or "").strip()
        if not name:
            continue

        card_data = bulk_index.get(sid)
        if not card_data:
            card_data = next((c for c in bulk_index.values() if c.get("name") == name), None)
        if not card_data:
            not_found.append(name)
            continue

        fields = _extract(card_data)
        fields["quantity"] = int(row.get("Quantity") or row.get("quantity") or 1)
        enriched_cards.append(fields)

    if not enriched_cards:
        raise HTTPException(status_code=400, detail=f"No se encontraron cartas válidas. Cartas no reconocidas: {not_found[:5]}")

    # 4. Detectar comandante
    def _scryfall_img_local(sid: str) -> str:
        if not sid or len(sid) < 2: return ""
        return f"https://cards.scryfall.io/normal/front/{sid[0]}/{sid[1]}/{sid}.jpg"

    commander_card = None
    if commander:
        commander_card = next((c for c in enriched_cards if c["name"].lower() == commander.lower()), None)
        if not commander_card:
            raise HTTPException(status_code=404, detail=f"Comandante '{commander}' no encontrado en el CSV.")
    else:
        # Auto-detectar: primera carta legendary creature
        candidates = [c for c in enriched_cards if c.get("can_be_commander")]
        if candidates:
            # Elegir la más popular por edhrec_rank
            commander_card = min(candidates, key=lambda c: c.get("edhrec_rank") or 999999)
        else:
            # Fallback: legendary creature
            for c in enriched_cards:
                tl = c.get("type_line", "")
                if "Legendary" in tl and "Creature" in tl:
                    commander_card = c
                    break
        if not commander_card:
            raise HTTPException(status_code=400, detail="No se detectó un comandante. Especifícalo manualmente.")

    # 5. Cartas del mazo (sin el comandante)
    deck_cards = [c for c in enriched_cards if c["name"] != commander_card["name"]]
    deck_ci = set(commander_card.get("color_identity") or [])

    # 6. Detectar arquetipo
    from core.archetypes import detect_archetype, ARCHETYPES
    archetype_key = detect_archetype(commander_card) or "counters"
    archetype = ARCHETYPES[archetype_key]

    # 7. Clasificar cartas y construir categorías
    from core import classifier as cls
    from core.pool import is_basic_land
    categories: dict[str, list[dict]] = {}
    from core.exporters import _build_deck_data_json, ROLE_ICONS

    def card_record_from_enriched(card: dict) -> dict:
        sid = card.get("scryfall_id") or ""
        roles = list(cls.classify(card))
        # Determinar categoría
        if card.get("is_land") and not is_basic_land(card):
            cat = "Tierras No-Básicas"
        elif "ramp" in roles and not card.get("is_land"):
            cat = "Ramp"
        elif "draw" in roles:
            cat = "Card Draw"
        elif "removal" in roles or "sweeper" in roles or "counter" in roles:
            cat = "Removal & Interaction"
        elif "equipment" in roles:
            cat = "Equipment"
        elif "threat" in roles:
            cat = "Wincons & Amenazas"
        else:
            cat = "Soporte"
        return {
            "name": card["name"],
            "scryfall_id": sid,
            "img": _scryfall_img_local(sid),
            "cmc": int(card.get("cmc") or 0),
            "type": card.get("type_line", ""),
            "oracle": (card.get("oracle_text") or "")[:200],
            "colors": card.get("color_identity", []),
            "rank": card.get("edhrec_rank"),
            "role": roles[0] if roles else "",
            "justification": "Importada desde ManaBox.",
            "roles": roles,
            "role_icons": [ROLE_ICONS.get(r, "") for r in roles if ROLE_ICONS.get(r)],
            "is_land": card.get("is_land", False),
            "is_creature": card.get("is_creature", False),
            "rarity": card.get("rarity", ""),
            "_cat": cat,
        }

    cmd_sid = commander_card.get("scryfall_id") or ""
    cmd_record = {
        **card_record_from_enriched(commander_card),
        "role": "Commander",
        "justification": "Comandante del mazo.",
    }
    categories["Comandante"] = [cmd_record]

    for card in deck_cards:
        rec = card_record_from_enriched(card)
        cat = rec.pop("_cat", "Soporte")
        categories.setdefault(cat, []).append(rec)

    # 8. Detectar conflictos con otros mazos del PIN
    conflicts_list = []
    if pin and pin.strip():
        try:
            other_decks = _supa_load_decks(pin.strip())
            reserved: dict[str, str] = {}
            for d in other_decks:
                owner = d.get("commander", d.get("deck_key", "?"))
                dd = d.get("deck_data", {})
                for c in dd.get("cards", []):
                    n = c.get("name", "")
                    if n:
                        reserved[n.lower()] = owner
            for card in deck_cards:
                n = card["name"]
                if n.lower() in reserved:
                    conflicts_list.append({
                        "card": n,
                        "reserved_by": reserved[n.lower()],
                    })
        except Exception as e:
            print(f"  [IMPORT] Error detectando conflictos: {e}")

    # 9. Estimar bracket
    from core.bracket import estimate_bracket
    from core.builder import DeckCard, BuiltDeck
    # Crear BuiltDeck sintético para el bracket
    built_cards = []
    for card in deck_cards:
        built_cards.append(DeckCard(
            card=card,
            category="Imported",
            role="",
            justification="Importada desde ManaBox.",
        ))
    synth_deck = BuiltDeck(
        commander=commander_card,
        archetype=archetype,
        colors="".join(sorted(deck_ci)) or "C",
        cards=built_cards,
        needed_basics=max(0, 99 - len(built_cards)),
    )
    bracket = estimate_bracket(synth_deck)

    # 10. Construir html_data completo
    from core.exporters import ARCHETYPE_DESCRIPTIONS, BRACKET_LABELS, _color_pips, _extract_wincons_from_deck
    colors_str = "".join(sorted(deck_ci)) or "C"
    html_data = {
        "commander": commander_card["name"],
        "commander_img": _scryfall_img_local(cmd_sid),
        "archetype_key": archetype_key,
        "archetype_name": archetype.name,
        "archetype_desc": ARCHETYPE_DESCRIPTIONS.get(archetype_key, archetype.description),
        "wincons": _extract_wincons_from_deck(synth_deck),
        "colors": colors_str,
        "color_pips": _color_pips(colors_str),
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
        "card_count": len(enriched_cards),
        "needed_basics": synth_deck.needed_basics,
        "categories": categories,
        "gameplay_guide": "",
    }

    # 11. Registrar en índice local
    safe = "".join(c if c.isalnum() else "_" for c in commander_card["name"].lower()).strip("_")
    safe = f"import_{safe}"
    register_deck(
        output_dir=_DECKS_DIR,
        deck_key=safe,
        commander_card=commander_card,
        archetype_key=archetype_key,
        colors=colors_str,
        bracket=bracket.bracket,
        bracket_score=bracket.score,
        cards=deck_cards,
        needed_basics=synth_deck.needed_basics,
        html_data=html_data,
    )

    # 12. Guardar en Supabase bajo el PIN
    saved_to_pin = False
    if pin and pin.strip():
        try:
            full_deck_data = {
                "commander_card": commander_card,
                "archetype_key": archetype_key,
                "colors": colors_str,
                "bracket": bracket.bracket,
                "bracket_score": round(bracket.score, 2),
                "cards": deck_cards,
                "needed_basics": synth_deck.needed_basics,
                "html_data": html_data,
            }
            saved_to_pin = _supa_save_deck(
                pin.strip(), safe, commander_card["name"],
                archetype_key, colors_str, bracket.bracket, full_deck_data,
            )
        except Exception as e:
            print(f"  [IMPORT] Error guardando en Supabase: {e}")

    # 13. Grimorio actualizado
    index = load_index(_DECKS_DIR)
    grimorio_html = build_multi_html_from_index(_DECKS_DIR, index.get("decks", {}))

    return {
        "ok": True,
        "commander": commander_card["name"],
        "deck_key": safe,
        "archetype": archetype.name,
        "colors": colors_str,
        "bracket": bracket.bracket,
        "card_count": len(enriched_cards),
        "not_found": not_found,
        "conflicts": conflicts_list,
        "saved_to_pin": saved_to_pin,
        "grimorio_html": grimorio_html,
    }
