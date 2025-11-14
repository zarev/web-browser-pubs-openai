"""Robust PDF downloader with OA fallbacks and reporting."""

from __future__ import annotations

import csv
import logging
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from backend.db import get_connection, insert_paper, upsert_source  # type: ignore
from browser_agent.config import BrowserAgentSettings
from browser_agent.utils import slugify

LOGGER = logging.getLogger("browser_agent.downloader")
DUCKDUCKGO_HTML = "https://duckduckgo.com/html/"
USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
]


@dataclass
class PdfCandidate:
    url: str
    source_domain: str
    landing_url: str | None = None
    via_open_access: bool = False
    discovered_from_title: bool = False


@dataclass
class PdfDownloadResult:
    status: str
    url: str | None
    final_url: str | None
    title: str | None
    saved_path: Path | None
    source_domain: str
    via_open_access: bool
    message: str

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "url": self.url,
            "final_url": self.final_url,
            "title": self.title,
            "saved_path": str(self.saved_path) if self.saved_path else None,
            "source_domain": self.source_domain,
            "via_open_access": self.via_open_access,
            "message": self.message,
        }


class PdfDownloader:
    def __init__(self, settings: BrowserAgentSettings):
        self.settings = settings
        self.pdf_dir = Path(settings.pdf_dir)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.report_path = Path(settings.report_csv_path)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self._report_lock = threading.Lock()
        self._cached_sources: dict[str, int] = {}
        self._oa_hosts = {host.lower() for host in settings.oa_sources}

    def download(self, url: str | None, filename: str | None = None, title: str | None = None, landing_url: str | None = None) -> PdfDownloadResult:
        base_domain = "unknown"
        normalized_title = title.strip() if title else ""
        if not normalized_title:
            message = "Title is required for open-access lookup"
            result = PdfDownloadResult(
                status="FAILED",
                url=url,
                final_url=None,
                title=normalized_title,
                saved_path=None,
                source_domain=base_domain,
                via_open_access=False,
                message=message,
            )
            self._record_report_row(result)
            return result

        candidates: list[PdfCandidate] = []
        oa_candidates = self._find_all_open_access_candidates(normalized_title)
        candidates.extend(oa_candidates)
        if url:
            parsed = urlparse(url)
            base_domain = parsed.netloc.lower() or base_domain
            if base_domain in self._oa_hosts:
                candidates.append(
                    PdfCandidate(
                        url=url,
                        source_domain=base_domain,
                        landing_url=landing_url,
                        via_open_access=True,
                        discovered_from_title=False,
                    )
                )
            else:
                LOGGER.info("Skipping direct download from non-OA host %s; relying on title lookup", base_domain)

        if not candidates:
            message = "No open-access source found for this title"
            result = PdfDownloadResult(
                status="FAILED",
                url=url,
                final_url=None,
                title=normalized_title,
                saved_path=None,
                source_domain=base_domain,
                via_open_access=False,
                message=message,
            )
            self._record_report_row(result)
            return result

        final_result: PdfDownloadResult | None = None
        for candidate in candidates:
            result = self._attempt_download(candidate, filename, normalized_title)
            if result.status == "DOWNLOADED":
                final_result = result
                break
            final_result = result

        assert final_result is not None  # candidates list always non-empty
        if final_result.via_open_access and final_result.status in {"DOWNLOADED", "SKIPPED"}:
            self._record_open_access_entry(final_result)
        self._record_report_row(final_result)
        return final_result

    def _attempt_download(self, candidate: PdfCandidate, filename: str | None, title: str | None) -> PdfDownloadResult:
        target_name = filename or f"{slugify(title or candidate.url)}.pdf"
        target_path = self.pdf_dir / target_name
        if target_path.exists():
            message = f"File already exists: {target_path.name}"
            LOGGER.info(message)
            return PdfDownloadResult(
                status="SKIPPED",
                url=candidate.url,
                final_url=candidate.url,
                title=title,
                saved_path=target_path,
                source_domain=candidate.source_domain,
                via_open_access=candidate.via_open_access,
                message=message,
            )

        landing_url = candidate.landing_url or self._derive_landing(candidate.url)
        session = requests.Session()
        session.headers["User-Agent"] = random.choice(USER_AGENTS)
        self._warm_up(session, landing_url)

        backoff = self.settings.download_backoff_seconds
        last_error = "Request failed"
        try:
            for attempt in range(1, self.settings.download_max_attempts + 1):
                session.headers["User-Agent"] = random.choice(USER_AGENTS)
                try:
                    response = session.get(
                        candidate.url,
                        stream=True,
                        timeout=self.settings.step_timeout_seconds,
                        allow_redirects=True,
                    )
                except requests.RequestException as exc:
                    last_error = f"Request error: {exc}"
                    LOGGER.warning(
                        "Download attempt %s/%s failed for %s: %s",
                        attempt,
                        self.settings.download_max_attempts,
                        candidate.url,
                        exc,
                    )
                else:
                    final_url = response.url
                    if response.status_code >= 400:
                        last_error = f"HTTP {response.status_code}"
                        LOGGER.warning("HTTP %s for %s", response.status_code, candidate.url)
                    else:
                        first_chunk: bytes = b""
                        body_iter = response.iter_content(chunk_size=1048576)
                        try:
                            first_chunk = next(body_iter)
                        except StopIteration:
                            first_chunk = b""
                        if not self._looks_like_pdf(response.headers.get("Content-Type"), first_chunk):
                            last_error = "Non-PDF content returned"
                            LOGGER.warning("Non-PDF content for %s", candidate.url)
                        else:
                            temp_path = target_path.with_suffix(".part")
                            with temp_path.open("wb") as handle:
                                if first_chunk:
                                    handle.write(first_chunk)
                                for chunk in body_iter:
                                    if chunk:
                                        handle.write(chunk)
                            temp_path.rename(target_path)
                            message = f"Saved {target_path.name}"
                            LOGGER.info(message)
                            return PdfDownloadResult(
                                status="DOWNLOADED",
                                url=candidate.url,
                                final_url=final_url,
                                title=title,
                                saved_path=target_path,
                                source_domain=candidate.source_domain,
                                via_open_access=candidate.via_open_access,
                                message=message,
                            )
                time.sleep(min(backoff, self.settings.download_max_backoff_seconds))
                backoff = min(backoff * 2, self.settings.download_max_backoff_seconds)
        finally:
            session.close()

        return PdfDownloadResult(
            status="FAILED",
            url=candidate.url,
            final_url=None,
            title=title,
            saved_path=None,
            source_domain=candidate.source_domain,
            via_open_access=candidate.via_open_access,
            message=last_error,
        )

    def _record_report_row(self, result: PdfDownloadResult) -> None:
        with self._report_lock:
            new_file = not self.report_path.exists()
            with self.report_path.open("a", newline="") as handle:
                writer = csv.writer(handle)
                if new_file:
                    writer.writerow(["title", "requested_url", "final_url", "status", "source_domain", "via_open_access", "message", "saved_path"])
                writer.writerow([
                    result.title or "",
                    result.url,
                    result.final_url or "",
                    result.status,
                    result.source_domain,
                    "yes" if result.via_open_access else "no",
                    result.message,
                    str(result.saved_path) if result.saved_path else "",
                ])

    def _record_open_access_entry(self, result: PdfDownloadResult) -> None:
        base_url = f"https://{result.source_domain}"
        try:
            with get_connection() as conn:
                source_id = self._cached_sources.get(result.source_domain)
                if source_id is None:
                    source_id = upsert_source(conn, base_url, f"OA mirror: {result.source_domain}")
                    self._cached_sources[result.source_domain] = source_id
                if result.final_url:
                    insert_paper(conn, source_id, result.final_url, result.title)
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("Failed to record OA source %s: %s", base_url, exc)

    def _normalized_oa_hosts(self) -> set[str]:
        return self._oa_hosts

    def _find_all_open_access_candidates(self, title: str) -> list[PdfCandidate]:
        candidates: list[PdfCandidate] = []
        for domain in self.settings.oa_sources:
            discovered = self._search_domain_for_title(domain, title)
            if discovered:
                LOGGER.info("Found OA candidate on %s", domain)
                parsed = urlparse(discovered)
                landing = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else None
                candidates.append(
                    PdfCandidate(
                        url=discovered,
                        source_domain=parsed.netloc or domain,
                        landing_url=landing,
                        via_open_access=True,
                        discovered_from_title=True,
                    )
                )
        return candidates

    def _search_domain_for_title(self, domain: str, title: str) -> str | None:
        query = f'site:{domain} "{title}" pdf'
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        try:
            response = requests.get(DUCKDUCKGO_HTML, params={"q": query}, headers=headers, timeout=self.settings.warmup_timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            LOGGER.debug("DuckDuckGo search failed for %s: %s", domain, exc)
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.select("a.result__a"):
            raw_href = anchor.get("href")
            if not raw_href:
                continue
            href = str(raw_href)
            target = self._extract_redirect_url(href)
            if not target:
                continue
            parsed = urlparse(target)
            if domain in parsed.netloc:
                return target
        return None

    @staticmethod
    def _extract_redirect_url(href: str) -> str | None:
        if href.startswith("/l/?"):
            parsed = urlparse(href)
            params = parse_qs(parsed.query)
            raw = params.get("uddg", [])
            if raw:
                return unquote(raw[0])
            return None
        return href

    def _warm_up(self, session: requests.Session, landing_url: str | None) -> None:
        if not landing_url:
            return
        try:
            session.get(landing_url, timeout=self.settings.warmup_timeout_seconds, allow_redirects=True)
        except requests.RequestException as exc:
            LOGGER.debug("Warm-up request failed for %s: %s", landing_url, exc)

    @staticmethod
    def _derive_landing(url: str) -> str | None:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
        path_parts = parsed.path.rsplit("/", 1)
        parent = path_parts[0] if len(path_parts) > 1 else ""
        landing_path = parent if parent else "/"
        return urlunparse((parsed.scheme, parsed.netloc, landing_path, "", "", ""))

    @staticmethod
    def _looks_like_pdf(content_type: str | None, first_chunk: bytes) -> bool:
        if content_type and "pdf" in content_type.lower():
            return True
        return first_chunk.startswith(b"%PDF")