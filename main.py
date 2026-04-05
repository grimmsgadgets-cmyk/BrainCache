"""
main.py — FastAPI application entry point for BrainCache.
Stage 1: sources CRUD, manual polling, article feed,
Ollama status check.
"""

import asyncio
import logging
import os
import shlex
import tempfile
from contextlib import asynccontextmanager
from typing import Optional

import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import scraper
import ollama_client
import session as session_module
import notebook as notebook_module
import tts
import stt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r") as f:
        raw = yaml.safe_load(f)
    # Expand env vars in all string values
    expanded = {}
    for k, v in raw.items():
        expanded[k] = os.path.expandvars(v) if isinstance(v, str) else v
    return expanded


_CONFIG = _load_config()
DB_PATH: str = _CONFIG["db_path"]


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db(DB_PATH)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, ollama_client.pull_model_if_needed)
    logger.info("BrainCache startup complete — DB: %s", DB_PATH)
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="BrainCache", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SourceCreate(BaseModel):
    name: str
    url: str
    feed_type: str
    scrape_selector: Optional[str] = None


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    feed_type: Optional[str] = None
    scrape_selector: Optional[str] = None
    is_active: Optional[int] = None


class NotebookCreate(BaseModel):
    term: str
    source_article_url: Optional[str] = None


class NotebookResolve(BaseModel):
    is_resolved: bool


# ---------------------------------------------------------------------------
# Routes — Sources
# ---------------------------------------------------------------------------

@app.get("/api/sources")
async def api_get_sources():
    return db.get_all_sources(DB_PATH)


@app.post("/api/sources", status_code=201)
async def api_create_source(body: SourceCreate):
    if body.feed_type not in ("rss", "scrape"):
        raise HTTPException(
            status_code=422,
            detail="feed_type must be 'rss' or 'scrape'",
        )
    if body.feed_type == "scrape" and not body.scrape_selector:
        raise HTTPException(
            status_code=422,
            detail="scrape_selector is required when feed_type is 'scrape'",
        )
    return db.insert_source(
        DB_PATH,
        name=body.name,
        url=body.url,
        feed_type=body.feed_type,
        scrape_selector=body.scrape_selector,
    )


@app.put("/api/sources/{source_id}")
async def api_update_source(source_id: int, body: SourceUpdate):
    existing = db.get_source_by_id(DB_PATH, source_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Source not found")
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return existing
    return db.update_source(DB_PATH, source_id, **updates)


@app.delete("/api/sources/{source_id}", status_code=204)
async def api_delete_source(source_id: int):
    if not db.get_source_by_id(DB_PATH, source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    db.delete_source(DB_PATH, source_id)


@app.post("/api/sources/{source_id}/poll")
async def api_poll_source(source_id: int):
    source = db.get_source_by_id(DB_PATH, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    new_count = scraper.poll_source(source, DB_PATH)
    return {"new_articles": new_count}


@app.post("/api/sources/{source_id}/test")
async def api_test_source(source_id: int):
    source = db.get_source_by_id(DB_PATH, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    detected = scraper.test_source(source)
    return {"detected": detected}


# ---------------------------------------------------------------------------
# Routes — Articles
# ---------------------------------------------------------------------------

@app.get("/api/articles")
async def api_get_articles(source_id: Optional[int] = None):
    return db.get_all_articles(DB_PATH, source_id=source_id)


# ---------------------------------------------------------------------------
# Routes — Poll all
# ---------------------------------------------------------------------------

@app.post("/api/poll")
async def api_poll_all():
    counts = scraper.poll_all_sources(DB_PATH)
    total = sum(counts.values())
    return {"total": total, "sources": counts}


# ---------------------------------------------------------------------------
# Routes — Ollama status
# ---------------------------------------------------------------------------

@app.get("/api/ollama/status")
async def api_ollama_status():
    ready = ollama_client.check_ollama_ready()
    return {
        "ready": ready,
        "model": ollama_client.OLLAMA_MODEL,
        "host": ollama_client.OLLAMA_HOST,
    }


# ---------------------------------------------------------------------------
# Routes — Voice status
# ---------------------------------------------------------------------------

@app.get("/api/voice/status")
async def api_voice_status():
    return {
        "tts": {
            "available": tts.check_piper_available(_CONFIG),
            "binary": _CONFIG.get("piper_binary", ""),
            "model": _CONFIG.get("piper_model", ""),
        },
        "stt": {
            "available": stt.check_whisper_available(_CONFIG),
            "binary": _CONFIG.get("whisper_binary", ""),
            "model": _CONFIG.get("whisper_model", ""),
        },
    }


# ---------------------------------------------------------------------------
# Routes — Audio transcription
# ---------------------------------------------------------------------------

@app.post("/api/session/audio")
async def api_transcribe_audio(audio: UploadFile = File(...)):
    audio_bytes = await audio.read()
    content_type = audio.content_type or ""
    filename = audio.filename or ""

    tmp_wav = None
    tmp_webm = None
    try:
        is_webm = (
            "webm" in content_type
            or "ogg" in content_type
            or "opus" in content_type
            or filename.endswith(".webm")
            or filename.endswith(".ogg")
        )

        if is_webm:
            tmp_webm_file = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
            tmp_webm = tmp_webm_file.name
            tmp_webm_file.write(audio_bytes)
            tmp_webm_file.close()

            tmp_wav_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_wav = tmp_wav_file.name
            tmp_wav_file.close()

            ok = stt.save_webm_as_wav(audio_bytes, tmp_wav)
            if not ok:
                return {"text": ""}
        else:
            tmp_wav_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_wav = tmp_wav_file.name
            tmp_wav_file.write(audio_bytes)
            tmp_wav_file.close()

        text = await asyncio.to_thread(stt.transcribe_audio, tmp_wav, _CONFIG)
        return {"text": text}

    finally:
        for path in (tmp_wav, tmp_webm):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# WebSocket — Feynman session
# ---------------------------------------------------------------------------

@app.websocket("/ws/session")
async def ws_session(websocket: WebSocket):
    await websocket.accept()

    try:
        # Wait for start message
        msg = await websocket.receive_json()
        if msg.get("type") != "start":
            await websocket.send_json({"type": "error", "message": "Expected start message"})
            return
        url = (msg.get("url") or "").strip()
        if not url:
            await websocket.send_json({"type": "error", "message": "URL is required"})
            return

        # 1. Fetch article full text
        await websocket.send_json({"type": "status", "message": "Fetching article..."})
        full_text = await asyncio.to_thread(scraper.fetch_full_article_text, url)

        # 3. Update full_text in DB
        await asyncio.to_thread(db.update_article_full_text, DB_PATH, url, full_text)
        # 4. Mark in_progress
        await asyncio.to_thread(db.update_article_session_status, DB_PATH, url, "in_progress")

        # 5. Get article metadata
        article = await asyncio.to_thread(db.get_article_by_url, DB_PATH, url)
        title = (article.get("title") or url) if article else url
        summary = (article.get("summary") or "") if article else ""

        # 6-7. Generate pre-read prompt
        await websocket.send_json({"type": "status", "message": "Generating pre-read prompt..."})
        pre_read = await asyncio.to_thread(
            session_module.generate_pre_read_prompt, title, summary
        )
        hypothesis_question = pre_read.get("hypothesis_question", "")
        unknown_terms = pre_read.get("unknown_terms", [])

        # 8. Send pre-read phase
        await websocket.send_json({
            "type": "phase",
            "phase": "pre",
            "prompt": hypothesis_question,
        })
        tts.speak_prompt(hypothesis_question, _CONFIG)

        # 9. Wait for pre-read response
        pre_msg = await websocket.receive_json()

        # 10. Log response
        await asyncio.to_thread(
            db.insert_session_log,
            DB_PATH, url, "pre", hypothesis_question,
            pre_msg.get("text", ""),
        )

        # 11-13. Generate notebook entries for unknown terms
        await websocket.send_json({"type": "status", "message": "Generating notebook entries..."})
        notebook_entries = []
        for term in unknown_terms:
            entry = await asyncio.to_thread(
                notebook_module.generate_notebook_entry, DB_PATH, term, url
            )
            notebook_entries.append(entry)
        await websocket.send_json({"type": "terms", "entries": notebook_entries})

        # 14-15. Generate Socratic questions
        await websocket.send_json({"type": "status", "message": "Generating Socratic questions..."})
        questions = await asyncio.to_thread(
            session_module.generate_socratic_questions, full_text
        )

        # 16. Send each question, wait for response, log
        for i, question in enumerate(questions):
            await websocket.send_json({
                "type": "question",
                "index": i,
                "total": len(questions),
                "text": question,
            })
            tts.speak_prompt(question, _CONFIG)
            q_msg = await websocket.receive_json()
            await asyncio.to_thread(
                db.insert_session_log,
                DB_PATH, url, f"post_{i}", question,
                q_msg.get("text", ""),
            )

        # 17-20. Generate and send summary
        await websocket.send_json({"type": "status", "message": "Generating session summary..."})
        all_logs = await asyncio.to_thread(db.get_session_logs_by_article, DB_PATH, url)
        summary_data = await asyncio.to_thread(
            session_module.generate_session_summary, url, all_logs
        )
        await websocket.send_json({"type": "summary", "data": summary_data})

        # 21-22. Mark complete
        await asyncio.to_thread(db.update_article_session_status, DB_PATH, url, "complete")
        tts.speak_prompt("Session complete", _CONFIG)
        await websocket.send_json({"type": "complete"})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from session")
    except Exception as exc:
        logger.error("Session WebSocket error: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Routes — Notebook
# ---------------------------------------------------------------------------

@app.post("/api/notebook", status_code=200)
async def api_create_notebook_entry(body: NotebookCreate):
    term = body.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="term is required")
    entry = await asyncio.to_thread(
        notebook_module.generate_notebook_entry,
        DB_PATH, term, body.source_article_url,
    )
    return entry


@app.get("/api/notebook")
async def api_get_notebook():
    return db.get_all_notebook_entries(DB_PATH)


@app.put("/api/notebook/{entry_id}/resolve")
async def api_resolve_notebook_entry(entry_id: int, body: NotebookResolve):
    entry = db.update_notebook_entry_resolved(DB_PATH, entry_id, body.is_resolved)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@app.delete("/api/notebook/{entry_id}", status_code=204)
async def api_delete_notebook_entry(entry_id: int):
    deleted = db.delete_notebook_entry(DB_PATH, entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
