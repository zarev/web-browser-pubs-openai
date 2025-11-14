"""Example entry point that drives the BrowserUse agent."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from browser_agent.agent import BrowserUseAgent


async def main() -> None:
    agent = BrowserUseAgent()
    task = (
        "Go to https://journals.aps.org/ . Navigate to PRX, list all open "
        "source articles and their PDF links in JSON."
        " Capture full page screenshots before leaving each page."
    )
    result: Any = await agent.run_with_gemini_fallback(task)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
