"""
scraper.py — Multi-source article scraping for BrainCache.
Supports rss (feedparser) and scrape (httpx + BS4) feed types.
No scheduler in Stage 1 — polling triggered via API only.
"""

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

import db

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Gecko/20100101 Firefox/120.0) "
        "BrainCache/1.0"
    )
}
_TIMEOUT = httpx.Timeout(30.0)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_published(entry) -> str | None:
    """Extract a published date string from a feedparser entry."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            pass
    # Fall back to raw string
    raw = getattr(entry, "published", None) or getattr(entry, "updated", None)
    return raw or None


def _strip_html(html: str, max_len: int = 1000) -> str:
    """Strip HTML tags and truncate."""
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


# ---------------------------------------------------------------------------
# Fetch functions
# ---------------------------------------------------------------------------

def fetch_rss_source(source: dict) -> list[dict]:
    """
    Parse an RSS/Atom feed and return a list of article dicts.
    Each dict: url, title, published_date, summary.
    """
    feed = feedparser.parse(source["url"])

    if feed.bozo and not feed.entries:
        logger.warning(
            "Feed '%s' returned a bozo error and has no entries: %s",
            source.get("name"), feed.bozo_exception,
        )
        return []

    articles = []
    for entry in feed.entries:
        url = getattr(entry, "link", None) or getattr(entry, "id", None)
        if not url:
            continue
        title = getattr(entry, "title", None)
        published_date = _parse_published(entry)
        raw_summary = (
            getattr(entry, "summary", None)
            or getattr(entry, "description", None)
            or ""
        )
        summary = _strip_html(raw_summary, max_len=1000)
        articles.append({
            "url": url,
            "title": title,
            "published_date": published_date,
            "summary": summary,
        })

    return articles


def fetch_scrape_source(source: dict) -> list[dict]:
    """
    Scrape a web page using a CSS selector and return article dicts.
    Each dict: url, title, published_date=None, summary=None.
    """
    selector = source.get("scrape_selector")
    if not selector:
        logger.error(
            "Source '%s' has feed_type='scrape' but no scrape_selector.",
            source.get("name"),
        )
        return []

    try:
        resp = httpx.get(
            source["url"],
            headers=_HEADERS,
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("HTTP error scraping '%s': %s", source.get("name"), exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    elements = soup.select(selector)
    base_url = source["url"]

    articles = []
    for el in elements:
        # The element itself may be an <a>, or contain one
        anchor = el if el.name == "a" else el.find("a")
        if anchor is None:
            continue
        href = anchor.get("href", "").strip()
        if not href:
            continue
        url = urljoin(base_url, href)
        title = anchor.get_text(separator=" ").strip() or None
        articles.append({
            "url": url,
            "title": title,
            "published_date": None,
            "summary": None,
        })

    return articles


# ---------------------------------------------------------------------------
# Poll functions
# ---------------------------------------------------------------------------

def poll_source(source: dict, db_path: str) -> int:
    """
    Fetch articles for a single source, insert new ones, update timestamps.
    Returns count of new articles inserted.
    """
    feed_type = source.get("feed_type", "")
    try:
        if feed_type == "rss":
            articles = fetch_rss_source(source)
        elif feed_type == "scrape":
            articles = fetch_scrape_source(source)
        else:
            logger.error(
                "Unknown feed_type '%s' for source '%s'",
                feed_type, source.get("name"),
            )
            articles = []

        new_count = 0
        for art in articles:
            result = db.insert_article(
                db_path,
                source_id=source["id"],
                url=art["url"],
                title=art.get("title"),
                published_date=art.get("published_date"),
                summary=art.get("summary"),
            )
            if result is not None:
                new_count += 1

        db.update_source(
            db_path,
            source["id"],
            last_polled_at=db.now_iso(),
            last_error=None,
        )
        return new_count

    except Exception as exc:
        error_msg = str(exc)
        logger.error(
            "Error polling source '%s': %s", source.get("name"), error_msg
        )
        db.update_source(
            db_path,
            source["id"],
            last_polled_at=db.now_iso(),
            last_error=error_msg,
        )
        return 0


def poll_all_sources(db_path: str) -> dict[str, int]:
    """
    Poll every active source. Returns dict of source_name -> new article count.
    One source failing never stops the others.
    """
    sources = db.get_active_sources(db_path)
    results: dict[str, int] = {}
    for source in sources:
        name = source.get("name", str(source["id"]))
        try:
            count = poll_source(source, db_path)
            results[name] = count
        except Exception as exc:
            logger.error(
                "Unexpected error polling source '%s': %s", name, exc
            )
            results[name] = 0
    return results


def test_source(source: dict) -> int:
    """Fetch without saving. Returns count of articles detected."""
    feed_type = source.get("feed_type", "")
    if feed_type == "rss":
        articles = fetch_rss_source(source)
    elif feed_type == "scrape":
        articles = fetch_scrape_source(source)
    else:
        logger.error(
            "Unknown feed_type '%s' for source '%s'",
            feed_type, source.get("name"),
        )
        articles = []
    return len(articles)


# ---------------------------------------------------------------------------
# Full-text fetch
# ---------------------------------------------------------------------------

def fetch_full_article_text(url: str) -> str:
    """
    Fetch a URL and return cleaned plain text of the article body.
    """
    try:
        resp = httpx.get(
            url,
            headers=_HEADERS,
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("HTTP error fetching full text for '%s': %s", url, exc)
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove noise elements
    for tag in soup.select(
        "script, style, nav, header, footer, aside, "
        "form, noscript, iframe"
    ):
        tag.decompose()

    # Try content containers in order of preference
    content = (
        soup.find("article")
        or soup.select_one(".entry-content")
        or soup.select_one(".post-content")
        or soup.find("main")
        or soup.select_one("#content")
        or soup.find("body")
    )

    if content is None:
        return ""

    text = content.get_text(separator="\n")

    # Collapse runs of 3+ blank lines down to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
