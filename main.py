"""
main.py — FastAPI application entry point for BrainCache.
Stage 1: sources CRUD, manual polling, article feed,
Ollama status check.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import scraper
import ollama_client

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
