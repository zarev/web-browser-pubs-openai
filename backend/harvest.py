from __future__ import annotations

import html
import logging
import os
import re
import time
from collections import deque
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from db import get_connection, insert_paper, upsert_source

LOGGER = logging.getLogger("harvest")
USER_AGENT = os.getenv(
    "HARVEST_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
)
REQUEST_TIMEOUT = int(os.getenv("HARVEST_REQUEST_TIMEOUT", "45"))
FETCH_RETRY_ATTEMPTS = int(os.getenv("HARVEST_FETCH_RETRIES", "6"))
BASE_BACKOFF_SECONDS = float(os.getenv("HARVEST_BACKOFF_SECONDS", "5.0"))
MAX_BACKOFF_SECONDS = float(os.getenv("HARVEST_MAX_BACKOFF_SECONDS", "120.0"))
RATE_LIMIT_DELAY_SECONDS = float(os.getenv("HARVEST_RATE_LIMIT_SECONDS", "0.5"))
EXPORTER_PATTERN = re.compile(r"(https?://[^'\"<>\s]+PubExporter\.py[^'\"<>\s]*)", re.IGNORECASE)


class RateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = max(min_interval, 0.0)
        self._last_request_ts = 0.0

    def wait(self):
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_request_ts
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_ts = time.monotonic()


def _collect_links_from_html(html_text: str, base_url: str) -> tuple[list[tuple[str, str | None]], list[str]]:
    """Return (pdf_links, followup_pages) for a blob of HTML."""
    soup = BeautifulSoup(html_text, "html.parser")
    pdf_links: list[tuple[str, str | None]] = []
    followup_pages: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", "")).strip()
        if not href:
            continue
        resolved = urljoin(base_url, href)
        lower_href = resolved.lower()
        if ".pdf" in lower_href:
            title = anchor.get_text(strip=True) or None
            pdf_links.append((resolved, title))
        elif "/record/" in lower_href and "/files" in lower_href:
            followup_pages.append(resolved)
    return pdf_links, followup_pages


def _discover_exporter_urls(html_text: str) -> list[str]:
    urls = set()
    for match in EXPORTER_PATTERN.findall(html_text):
        urls.add(html.unescape(match))
    return list(urls)


def _fetch_text(session: requests.Session, target_url: str, limiter: RateLimiter) -> str | None:
    backoff = BASE_BACKOFF_SECONDS
    for attempt in range(1, FETCH_RETRY_ATTEMPTS + 1):
        limiter.wait()
        try:
            resp = session.get(target_url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            LOGGER.warning("Request error for %s (attempt %s/%s): %s", target_url, attempt, FETCH_RETRY_ATTEMPTS, exc)
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = backoff
            else:
                delay = backoff
            LOGGER.info("429 from %s, sleeping %.1fs", target_url, delay)
            time.sleep(delay)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        if 500 <= resp.status_code < 600:
            LOGGER.warning("Server error %s for %s (attempt %s/%s)", resp.status_code, target_url, attempt, FETCH_RETRY_ATTEMPTS)
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            LOGGER.error("HTTP error for %s: %s", target_url, exc)
            return None

        return resp.text

    LOGGER.error("Exceeded retries for %s", target_url)
    return None


def harvest_source(url: str, label: str | None = None) -> dict:
    LOGGER.info("Harvesting source %s", url)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    limiter = RateLimiter(RATE_LIMIT_DELAY_SECONDS)

    with get_connection() as conn:
        source_id = upsert_source(conn, url, label)
        html_text = _fetch_text(session, url, limiter)
        if html_text is None:
            return {"source_id": source_id, "fetched": False, "inserted": 0, "links_found": 0}

        pdf_map: dict[str, str | None] = {}
        file_queue: deque[str] = deque()
        seen_follow_pages: set[str] = set()

        def record_pdfs(pairs: Iterable[tuple[str, str | None]]):
            for pdf_url, title in pairs:
                if pdf_url not in pdf_map:
                    pdf_map[pdf_url] = title

        def enqueue_followups(pages: Iterable[str]):
            for page in pages:
                if page not in seen_follow_pages:
                    seen_follow_pages.add(page)
                    file_queue.append(page)

        initial_pdfs, initial_followups = _collect_links_from_html(html_text, url)
        record_pdfs(initial_pdfs)
        enqueue_followups(initial_followups)

        for exporter_url in _discover_exporter_urls(html_text):
            exporter_html = _fetch_text(session, exporter_url, limiter)
            if not exporter_html:
                continue
            pdfs, followups = _collect_links_from_html(exporter_html, exporter_url)
            record_pdfs(pdfs)
            enqueue_followups(followups)

        while file_queue:
            follow_url = file_queue.popleft()
            follow_html = _fetch_text(session, follow_url, limiter)
            if not follow_html:
                continue
            pdfs, more_followups = _collect_links_from_html(follow_html, follow_url)
            record_pdfs(pdfs)
            enqueue_followups(more_followups)

        inserted = 0
        for pdf_url, title in pdf_map.items():
            try:
                if insert_paper(conn, source_id, pdf_url, title):
                    inserted += 1
            except Exception as exc:  # pragma: no cover
                LOGGER.error("Failed to insert %s for source %s: %s", pdf_url, url, exc)

        return {
            "source_id": source_id,
            "fetched": True,
            "inserted": inserted,
            "links_found": len(pdf_map),
        }
