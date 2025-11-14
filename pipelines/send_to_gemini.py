"""Utility helpers to call Gemini for text + screenshot fallbacks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import google.generativeai as genai

from browser_agent.config import get_settings


def _get_model(model_name: str | None = None):
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required for Gemini fallback.")
    model_to_use = model_name or settings.gemini_model_name
    genai.configure(api_key=settings.gemini_api_key)  # type: ignore[attr-defined]
    return genai.GenerativeModel(model_to_use)  # type: ignore[attr-defined]


async def analyze_with_gemini(prompt: str, screenshot_path: str | None = None) -> str:
    model = _get_model()

    def _run():
        if screenshot_path:
            image_bytes = Path(screenshot_path).read_bytes()
            return model.generate_content([prompt, {"mime_type": "image/png", "data": image_bytes}]).text
        return model.generate_content(prompt).text

    return await asyncio.to_thread(_run)


async def markdown_from_pdf(pdf_path: Path | str) -> str:
    model = _get_model()
    pdf_path = Path(pdf_path)

    def _run():
        data = pdf_path.read_bytes()
        response = model.generate_content([
            "Convert this PDF into clean Markdown. Each section and subsection must be clearly identified with markdown format. If it's missing after the conversion you must infer it. ",
            {"mime_type": "application/pdf", "data": data},
        ])
        return response.text or ""

    return await asyncio.to_thread(_run)
