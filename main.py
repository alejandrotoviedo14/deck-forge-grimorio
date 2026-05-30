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
from core.deck_index import register_deck, load_index

app = FastAPI(title="Deck Forge API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directorio temporal compartido por sesión del servidor
_WORK_DIR = Path(tempfile.mkdtemp(prefix="deck_forge_"))
_DECKS_DIR = _WORK_DIR / "decks"
_DECKS_DIR.mkdir(parents=True, exist_ok=True)

# Directorio de colecciones guardadas (persiste en la sesión del servidor)
_COLLECTIONS_DIR = _WORK_DIR / "collections"
_COLLECTIONS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def _save_upload(upload: UploadFile, dest: Path) -> Path:
    dest.write_bytes(upload.file.read())
    return dest


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

@app.get("/", response_class=HTMLResponse)
async def index():
    ui = Path(__file__).parent / "web" / "index.html"
    if ui.exists():
        return HTMLResponse(ui.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Deck Forge API</h1><p>Docs: <a href='/docs'>/docs</a></p>")


# ---------------------------------------------------------------------------
# GET /api/collections — lista colecciones guardadas
# ---------------------------------------------------------------------------

@app.get("/api/collections")
async def list_collections():
    """Lista todas las colecciones guardadas en esta sesión."""
    cols = []
    for f in sorted(_COLLECTIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            meta = json.loads((f.parent / f.stem).with_suffix(".meta.json").read_text())
        except Exception:
            meta = {}
        cols.append({
            "id": f.stem,
            "name": meta.get("name", f.stem),
            "real_count": meta.get("real_count", 0),
            "uploaded_at": meta.get("uploaded_at", ""),
        })
    return {"collections": cols}


# ---------------------------------------------------------------------------
# POST /api/collections/save — guarda una colección con nombre
# ---------------------------------------------------------------------------

@app.post("/api/collections/save")
async def save_collection(
    collection: str = Form(...),
    name: str = Form(...),
):
    """Guarda una colección JSON con un nombre amigable."""
    import time
    try:
        coll = json.loads(collection)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    col_id = _safe_filename(name) or f"col_{int(time.time())}"
    col_path = _COLLECTIONS_DIR / f"{col_id}.json"
    meta_path = _COLLECTIONS_DIR / f"{col_id}.meta.json"

    col_path.write_text(json.dumps(coll, ensure_ascii=False), encoding="utf-8")
    meta_path.write_text(json.dumps({
        "name": name,
        "id": col_id,
        "real_count": len(coll.get("real", [])),
        "uploaded_at": time.strftime("%Y-%m-%d %H:%M"),
    }), encoding="utf-8")

    return {"ok": True, "id": col_id, "name": name}


# ---------------------------------------------------------------------------
# GET /api/collections/{id} — carga una colección guardada
# ---------------------------------------------------------------------------

@app.get("/api/collections/{col_id}")
async def get_collection(col_id: str):
    col_path = _COLLECTIONS_DIR / f"{col_id}.json"
    if not col_path.exists():
        raise HTTPException(status_code=404, detail="Colección no encontrada")
    return json.loads(col_path.read_text(encoding="utf-8"))


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
    max_b, reason = estimate_max_bracket_for_pool(pool)
    scores = score_commanders(pool, min_colors=min_colors, require_legal=False)

    return {
        "pool_size": len(pool),
        "max_bracket": max_b,
        "max_bracket_reason": reason,
        "commanders": [
            {
                "name": s.name,
                "colors": s.colors,
                "archetype": s.archetype.key if s.archetype else None,
                "archetype_name": s.archetype.name if s.archetype else None,
                "total_score": round(s.total_score, 1),
                "synergy_density": round(s.synergy_density, 1),
                "bracket_ceiling": round(s.bracket_ceiling, 2),
                "rank_score": round(s.rank_score, 1),
            }
            for s in scores[:top]
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/build
# ---------------------------------------------------------------------------

@app.post("/api/build")
async def build(
    collection: str = Form(..., description="JSON string de collection_enriched"),
    real_csv: UploadFile = File(..., description="CSV original de ManaBox"),
    commander: str | None = Form(None),
    colors: str | None = Form(None),
    archetype: str | None = Form(None),
    use_edhrec: bool = Form(True),
):
    """Construye un mazo y devuelve HTML + exportaciones."""
    try:
        coll = json.loads(collection)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"collection JSON inválido: {e}")

    real_bytes = await real_csv.read()
    basics = _load_basics_from_bytes(real_bytes)
    pool = build_real_pool(coll)

    try:
        deck = build_deck(
            pool,
            commander_name=commander,
            colors=colors,
            archetype_key=archetype,
            use_edhrec=use_edhrec,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # LLM Critic — mejora el mazo y genera guía de juego si hay API key
    try:
        from core.llm_critic import LLMCritic
        critic = LLMCritic(verbose=False)
        if critic.api_key:
            deck = critic.review_and_improve(deck, pool)
            deck.gameplay_guide = critic.generate_gameplay_guide(deck)
        else:
            deck.gameplay_guide = ""
    except Exception:
        deck.gameplay_guide = ""

    full_list = deck.all_cards_with_basics(basics)
    bracket = estimate_bracket(full_list)

    safe = _safe_filename(deck.commander["name"])

    # Guardar en directorio temporal del servidor
    deck_dir = _DECKS_DIR
    mox_path = deck_dir / f"{safe}_moxfield.txt"
    csv_path = deck_dir / f"{safe}_manabox.csv"

    # Guardar el CSV real temporalmente para to_manabox_csv
    tmp_real = _WORK_DIR / "upload" / "real.csv"
    tmp_real.write_bytes(real_bytes)

    mox_path.write_text(to_moxfield_txt(deck, basics), encoding="utf-8")
    csv_path.write_text(to_manabox_csv(deck, str(tmp_real), basics), encoding="utf-8")

    html_data = _build_deck_data_json(deck, bracket)
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

    index = load_index(deck_dir)
    grimorio_html = build_multi_html_from_index(deck_dir, index.get("decks", {}))

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
# GET /api/grimorio — devuelve el grimorio HTML actual del servidor
# ---------------------------------------------------------------------------

@app.get("/api/grimorio", response_class=HTMLResponse)
async def grimorio():
    index = load_index(_DECKS_DIR)
    if not index.get("decks"):
        return HTMLResponse("<p>No hay mazos construidos todavía. Usa /api/build primero.</p>")
    return HTMLResponse(build_multi_html_from_index(_DECKS_DIR, index["decks"]))


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
