"""
db.py — SQLite setup, schema, and all query helpers.
Single database file at /app/data/braincache.db.
All timestamps stored as ISO-8601 strings in UTC.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional


def now_iso() -> str:
    """Current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _row_to_dict(row) -> dict:
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Schema + seed
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    url              TEXT NOT NULL,
    feed_type        TEXT NOT NULL,
    scrape_selector  TEXT,
    is_active        INTEGER DEFAULT 1,
    added_at         TEXT,
    last_polled_at   TEXT,
    last_error       TEXT
);

CREATE TABLE IF NOT EXISTS articles (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id        INTEGER REFERENCES sources(id),
    url              TEXT UNIQUE NOT NULL,
    title            TEXT,
    published_date   TEXT,
    summary          TEXT,
    full_text        TEXT,
    scraped_at       TEXT,
    session_status   TEXT DEFAULT 'not_started'
);

CREATE TABLE IF NOT EXISTS notebook_entries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    term                TEXT NOT NULL,
    hypothesis_prompt   TEXT,
    plain_explanation   TEXT,
    mitre_reference     TEXT,
    socratic_questions  TEXT,
    resolution_target   TEXT,
    is_resolved         INTEGER DEFAULT 0,
    created_at          TEXT,
    resolved_at         TEXT,
    source_article_url  TEXT
);

CREATE TABLE IF NOT EXISTS session_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    article_url   TEXT,
    phase         TEXT,
    prompt_text   TEXT,
    user_response TEXT,
    timestamp     TEXT
);
"""

_SEED_SOURCES = [
    ("The DFIR Report",    "https://thedfirreport.com/reports/",               "scrape", "article h2 a"),
    ("Bleeping Computer",  "https://www.bleepingcomputer.com/feed/",            "rss",    None),
    ("Krebs on Security",  "https://krebsonsecurity.com/feed/",                 "rss",    None),
    ("Recorded Future",    "https://www.recordedfuture.com/feed",               "rss",    None),
    ("Secureworks",        "https://www.secureworks.com/rss/blog",              "rss",    None),
    ("Unit 42 Palo Alto",  "https://unit42.paloaltonetworks.com/feed/",         "rss",    None),
]


def init_db(db_path: str) -> None:
    """Creates all tables. Inserts seed sources if table empty."""
    conn = get_connection(db_path)
    with conn:
        conn.executescript(_SCHEMA)
        row = conn.execute("SELECT COUNT(*) FROM sources").fetchone()
        if row[0] == 0:
            ts = now_iso()
            conn.executemany(
                "INSERT INTO sources (name, url, feed_type, scrape_selector, added_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [(n, u, ft, sel, ts) for n, u, ft, sel in _SEED_SOURCES],
            )
    conn.close()


# ---------------------------------------------------------------------------
# Sources helpers
# ---------------------------------------------------------------------------

def get_all_sources(db_path: str) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_active_sources(db_path: str) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM sources WHERE is_active = 1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_source_by_id(db_path: str, source_id: int) -> Optional[dict]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    conn.close()
    return _row_to_dict(row)


def insert_source(
    db_path: str,
    name: str,
    url: str,
    feed_type: str,
    scrape_selector: Optional[str] = None,
) -> dict:
    conn = get_connection(db_path)
    ts = now_iso()
    with conn:
        cur = conn.execute(
            "INSERT INTO sources (name, url, feed_type, scrape_selector, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, url, feed_type, scrape_selector, ts),
        )
        row = conn.execute(
            "SELECT * FROM sources WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    conn.close()
    return dict(row)


_ALLOWED_SOURCE_FIELDS = {
    "name", "url", "feed_type", "scrape_selector",
    "is_active", "last_polled_at", "last_error",
}


def update_source(
    db_path: str, source_id: int, **fields
) -> Optional[dict]:
    valid = {k: v for k, v in fields.items() if k in _ALLOWED_SOURCE_FIELDS}
    if not valid:
        return get_source_by_id(db_path, source_id)
    assignments = ", ".join(f"{k} = ?" for k in valid)
    values = list(valid.values()) + [source_id]
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            f"UPDATE sources SET {assignments} WHERE id = ?", values
        )
        row = conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
    conn.close()
    return _row_to_dict(row)


def delete_source(db_path: str, source_id: int) -> bool:
    conn = get_connection(db_path)
    with conn:
        cur = conn.execute(
            "DELETE FROM sources WHERE id = ?", (source_id,)
        )
    conn.close()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Articles helpers
# ---------------------------------------------------------------------------

def get_all_articles(
    db_path: str, source_id: Optional[int] = None
) -> list[dict]:
    conn = get_connection(db_path)
    if source_id is not None:
        rows = conn.execute(
            "SELECT a.*, s.name AS source_name "
            "FROM articles a "
            "LEFT JOIN sources s ON a.source_id = s.id "
            "WHERE a.source_id = ? "
            "ORDER BY a.id DESC",
            (source_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT a.*, s.name AS source_name "
            "FROM articles a "
            "LEFT JOIN sources s ON a.source_id = s.id "
            "ORDER BY a.id DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_article_by_url(db_path: str, url: str) -> Optional[dict]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT a.*, s.name AS source_name "
        "FROM articles a "
        "LEFT JOIN sources s ON a.source_id = s.id "
        "WHERE a.url = ?",
        (url,),
    ).fetchone()
    conn.close()
    return _row_to_dict(row)


def insert_article(
    db_path: str,
    source_id: int,
    url: str,
    title: Optional[str] = None,
    published_date: Optional[str] = None,
    summary: Optional[str] = None,
) -> Optional[dict]:
    conn = get_connection(db_path)
    ts = now_iso()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO articles "
                "(source_id, url, title, published_date, summary, scraped_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (source_id, url, title, published_date, summary, ts),
            )
            row = conn.execute(
                "SELECT a.*, s.name AS source_name "
                "FROM articles a "
                "LEFT JOIN sources s ON a.source_id = s.id "
                "WHERE a.id = ?",
                (cur.lastrowid,),
            ).fetchone()
        conn.close()
        return dict(row)
    except sqlite3.IntegrityError:
        conn.close()
        return None


def update_article_full_text(db_path: str, url: str, full_text: str) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "UPDATE articles SET full_text = ? WHERE url = ?",
            (full_text, url),
        )
    conn.close()


_VALID_SESSION_STATUSES = {"not_started", "in_progress", "complete"}


def update_article_session_status(db_path: str, url: str, status: str) -> None:
    if status not in _VALID_SESSION_STATUSES:
        raise ValueError(
            f"Invalid session status '{status}'. "
            f"Must be one of: {_VALID_SESSION_STATUSES}"
        )
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "UPDATE articles SET session_status = ? WHERE url = ?",
            (status, url),
        )
    conn.close()


# ---------------------------------------------------------------------------
# Notebook helpers
# ---------------------------------------------------------------------------

def _deserialize_notebook_row(row) -> Optional[dict]:
    if row is None:
        return None
    d = dict(row)
    raw = d.get("socratic_questions")
    if raw:
        try:
            d["socratic_questions"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            d["socratic_questions"] = []
    else:
        d["socratic_questions"] = []
    return d


def get_all_notebook_entries(db_path: str) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM notebook_entries "
        "ORDER BY is_resolved ASC, created_at DESC"
    ).fetchall()
    conn.close()
    return [_deserialize_notebook_row(r) for r in rows]


def get_notebook_entry_by_term(
    db_path: str, term: str
) -> Optional[dict]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM notebook_entries WHERE LOWER(term) = LOWER(?)",
        (term,),
    ).fetchone()
    conn.close()
    return _deserialize_notebook_row(row)


def insert_notebook_entry(
    db_path: str,
    term: str,
    hypothesis_prompt: Optional[str] = None,
    plain_explanation: Optional[str] = None,
    mitre_reference: Optional[str] = None,
    socratic_questions: Optional[list] = None,
    resolution_target: Optional[str] = None,
    source_article_url: Optional[str] = None,
) -> dict:
    conn = get_connection(db_path)
    ts = now_iso()
    sq_json = json.dumps(socratic_questions) if socratic_questions else json.dumps([])
    with conn:
        cur = conn.execute(
            "INSERT INTO notebook_entries "
            "(term, hypothesis_prompt, plain_explanation, mitre_reference, "
            "socratic_questions, resolution_target, source_article_url, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (term, hypothesis_prompt, plain_explanation, mitre_reference,
             sq_json, resolution_target, source_article_url, ts),
        )
        row = conn.execute(
            "SELECT * FROM notebook_entries WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    conn.close()
    return _deserialize_notebook_row(row)


def update_notebook_entry_resolved(
    db_path: str, entry_id: int, is_resolved: bool
) -> Optional[dict]:
    resolved_at = now_iso() if is_resolved else None
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "UPDATE notebook_entries "
            "SET is_resolved = ?, resolved_at = ? "
            "WHERE id = ?",
            (1 if is_resolved else 0, resolved_at, entry_id),
        )
        row = conn.execute(
            "SELECT * FROM notebook_entries WHERE id = ?", (entry_id,)
        ).fetchone()
    conn.close()
    return _deserialize_notebook_row(row)


def delete_notebook_entry(db_path: str, entry_id: int) -> bool:
    conn = get_connection(db_path)
    with conn:
        cur = conn.execute(
            "DELETE FROM notebook_entries WHERE id = ?", (entry_id,)
        )
    conn.close()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Session log helpers
# ---------------------------------------------------------------------------

def insert_session_log(
    db_path: str,
    article_url: str,
    phase: str,
    prompt_text: str,
    user_response: str,
) -> dict:
    conn = get_connection(db_path)
    ts = now_iso()
    with conn:
        cur = conn.execute(
            "INSERT INTO session_logs "
            "(article_url, phase, prompt_text, user_response, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (article_url, phase, prompt_text, user_response, ts),
        )
        row = conn.execute(
            "SELECT * FROM session_logs WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    conn.close()
    return dict(row)


def get_session_logs_by_article(
    db_path: str, article_url: str
) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM session_logs WHERE article_url = ? ORDER BY id",
        (article_url,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
