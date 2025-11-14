"""Runtime configuration for the BrowserUse agent."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict

from pydantic import Field
from pydantic_settings import BaseSettings


class BrowserAgentSettings(BaseSettings):
    """Environment-driven settings to keep BrowserUse configurable."""

    openai_api_key: str | None = Field(default=None)
    gemini_api_key: str | None = Field(default=None)

    model_name: str = Field(default="gpt-4.1")
    gemini_model_name: str = Field(default="gemini-2.5-pro")
    gemini_model_priority: list[str] = Field(
        default_factory=lambda: [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-image",
            "gemini-2.5-pro",
        ]
    )
    browser_use_api_key: str | None = Field(default=None)
    headless: bool = Field(default=True)
    viewport_width: int = Field(default=1280)
    viewport_height: int = Field(default=800)

    max_steps: int = Field(default=40)
    step_timeout_seconds: int = Field(default=60)
    screenshot_dir: str = Field(default="data/screenshots")
    pdf_dir: str = Field(default="data/raw_pdfs")
    report_csv_path: str = Field(default="data/report.csv")
    oa_sources: list[str] = Field(
        default_factory=lambda: [
            "arxiv.org",
            "biorxiv.org",
            "medrxiv.org",
            "hal.science",
            "zenodo.org",
            "osf.io",
            "ncbi.nlm.nih.gov",
        ]
    )
    download_max_attempts: int = Field(default=4)
    download_backoff_seconds: float = Field(default=5.0)
    download_max_backoff_seconds: float = Field(default=45.0)
    warmup_timeout_seconds: int = Field(default=20)
    prompt_path: str | None = Field(default=None)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def browser_profile_kwargs(self) -> Dict[str, Any]:
        return {
            "headless": self.headless,
            "viewport": {"width": self.viewport_width, "height": self.viewport_height},
        }


@lru_cache(maxsize=1)
def get_settings() -> BrowserAgentSettings:
    return BrowserAgentSettings()  # pragma: no cover
