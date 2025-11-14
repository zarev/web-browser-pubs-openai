"""Run BrowserUse against a source URL and collect PDF metadata."""

from __future__ import annotations

from typing import Any, Dict, List

from browser_agent.agent import BrowserUseAgent


async def fetch_pdfs_for_source(source_url: str, label: str | None = None) -> Dict[str, Any]:
    agent = BrowserUseAgent()
    task = f"""
        Navigate to {source_url}.
        Capture a screenshot of the landing page.
        Identify open-access friendly paper listings and record their titles in JSON under the key "pdfs" with at least title and landing_url.
        Do NOT download PDFs directly from {source_url}. Instead, for every title call save_pdf with:
            - title (required)
            - landing_url (page where you found the title)
            - url ONLY if the PDF link already belongs to an approved open-access domain (arxiv.org, biorxiv.org, medrxiv.org, hal.science, zenodo.org, osf.io, ncbi.nlm.nih.gov).
        Capture screenshots for any page that contains the titles before leaving it.
        Provide a final JSON summary containing label, total_titles, and any successfully queued filenames.
    """
    result = await agent.run_with_gemini_fallback(task)
    pdfs: List[Dict[str, Any]] = []
    data = result.get("data")
    if isinstance(data, dict):
        if "pdfs" in data:
            pdfs = data["pdfs"]
        elif "papers" in data:
            pdfs = data["papers"]
    return {
        "label": label,
        "url": source_url,
        "pdfs": pdfs,
        "raw_result": result,
    }
