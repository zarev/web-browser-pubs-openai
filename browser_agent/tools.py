"""Custom BrowserUse tools for harvesting flows."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from browser_use.agent.views import ActionResult
from browser_use.tools.service import Tools
from pydantic import BaseModel, Field
from playwright.async_api import async_playwright

from browser_agent.config import BrowserAgentSettings
from browser_agent.pdf_downloader import PdfDownloader
from browser_agent.utils import slugify


class SavePdfArgs(BaseModel):
    title: str = Field(min_length=1, description="Paper title to drive open-access lookup")
    url: str | None = None
    filename: str | None = None
    landing_url: str | None = None


class ScreenshotArgs(BaseModel):
    url: str
    filename: str | None = None


class InlineScreenshotArgs(BaseModel):
    url: str


class HarvestTools(Tools):
    """Tools collection with custom PDF and screenshot helpers."""

    def __init__(self, settings: BrowserAgentSettings):
        super().__init__()
        self.settings = settings
        self.downloader = PdfDownloader(settings)
        self._register_save_pdf()
        self._register_capture_screenshot()
        self._register_inline_screenshot()

    def _register_save_pdf(self) -> None:
        settings = self.settings

        @self.registry.action("Queue an open-access PDF lookup and download", param_model=SavePdfArgs)
        async def save_pdf(params: SavePdfArgs):
            result = await asyncio.to_thread(
                self.downloader.download,
                params.url,
                params.filename,
                params.title,
                params.landing_url,
            )
            return ActionResult(
                extracted_content=result.message,
                long_term_memory=result.message,
            )

    def _register_capture_screenshot(self) -> None:
        settings = self.settings

        @self.registry.action("Capture a screenshot of a URL", param_model=ScreenshotArgs)
        async def capture_screenshot(params: ScreenshotArgs):
            target_dir = Path(settings.screenshot_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            final_name = (params.filename or slugify(params.url)) + ".png"
            target_path = target_dir / final_name

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=settings.headless)
                page = await browser.new_page(
                    viewport={"width": settings.viewport_width, "height": settings.viewport_height}
                )
                await page.goto(params.url, wait_until="networkidle")
                await page.screenshot(path=target_path, full_page=True)
                await browser.close()

            message = f"Screenshot saved to {target_path}"
            return ActionResult(extracted_content=message, long_term_memory=message)

    def _register_inline_screenshot(self) -> None:
        settings = self.settings

        @self.registry.action("Capture a screenshot and return base64", param_model=InlineScreenshotArgs)
        async def inline_screenshot(params: InlineScreenshotArgs):
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=settings.headless)
                page = await browser.new_page(
                    viewport={"width": settings.viewport_width, "height": settings.viewport_height}
                )
                await page.goto(params.url, wait_until="networkidle")
                buffer = await page.screenshot(full_page=True)
                await browser.close()
            encoded = base64.b64encode(buffer).decode("utf-8")
            return ActionResult(extracted_content=encoded)


def build_tools(settings: BrowserAgentSettings) -> HarvestTools:
    return HarvestTools(settings)
