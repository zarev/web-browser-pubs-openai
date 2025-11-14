"""BrowserUse agent wrapper with Gemini fallback and model cycling."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Tuple

from browser_use import Agent, ChatBrowserUse, ChatGoogle, ChatOpenAI
from browser_use.agent.views import AgentHistoryList
from browser_use.browser.profile import BrowserProfile

from browser_agent.config import BrowserAgentSettings, get_settings
from browser_agent.prompts import BASE_PROMPT
from browser_agent.tools import build_tools


@dataclass
class ModelAttempt:
    model: str
    status: str
    message: str | None = None


class ModelOverloadError(RuntimeError):
    """Raised when every prioritized model reports an overload error."""

    def __init__(self, attempts: List[ModelAttempt]):
        self.attempts = attempts
        super().__init__("All prioritized models reported overload errors")


class BrowserUseAgent:
    """High-level helper that orchestrates BrowserUse + Gemini."""

    def __init__(self, settings: BrowserAgentSettings | None = None):
        self.settings = settings or get_settings()
        self.browser_profile = BrowserProfile(**self.settings.browser_profile_kwargs())
        self.tools = build_tools(self.settings)

    def _llm_candidates(self) -> Iterable[Tuple[str, Any]]:
        if self.settings.openai_api_key:
            yield (self.settings.model_name, ChatOpenAI(model=self.settings.model_name, api_key=self.settings.openai_api_key))
            return

        if self.settings.gemini_api_key:
            for model_name in self._gemini_model_sequence():
                yield (model_name, ChatGoogle(model=model_name, api_key=self.settings.gemini_api_key))
            return

        yield ("browser-use", ChatBrowserUse())

    def _gemini_model_sequence(self) -> List[str]:
        priority = list(self.settings.gemini_model_priority or [])
        base = self.settings.gemini_model_name
        if base and base not in priority:
            priority.insert(0, base)
        if not priority:
            priority.append("gemini-2.5-pro")

        seen: set[str] = set()
        ordered: List[str] = []
        for name in priority:
            if name and name not in seen:
                ordered.append(name)
                seen.add(name)
        return ordered

    async def run(self, task: str, **kwargs: Any) -> Dict[str, Any]:
        """Execute a BrowserUse task and return a structured payload."""
        attempts: List[ModelAttempt] = []
        max_steps = kwargs.get("max_steps", self.settings.max_steps)

        for model_name, llm in self._llm_candidates():
            try:
                history = await self._execute_agent(llm, task, max_steps)
            except Exception as exc:
                message = str(exc)
                if self._is_model_overloaded_message(message):
                    attempts.append(ModelAttempt(model=model_name, status="overloaded", message=message))
                    continue
                raise

            if self._history_indicates_overload(history):
                attempts.append(ModelAttempt(model=model_name, status="overloaded", message="Model reported overload during run"))
                continue

            result = self._history_to_result(history)
            attempts.append(ModelAttempt(model=model_name, status="success"))
            result["model_used"] = model_name
            result["model_attempts"] = [asdict(attempt) for attempt in attempts]
            return result

        raise ModelOverloadError(attempts)

    async def _execute_agent(self, llm: Any, task: str, max_steps: int) -> AgentHistoryList:
        agent = Agent(
            task=f"{BASE_PROMPT}\n\n{task}",
            llm=llm,
            browser_profile=self.browser_profile,
            tools=self.tools,
            step_timeout=self.settings.step_timeout_seconds,
            use_vision=True,
            include_recent_events=True,
        )
        return await agent.run(max_steps=max_steps)

    async def run_with_gemini_fallback(self, task: str, fallback_prompt: str | None = None) -> Dict[str, Any]:
        """Run BrowserUse and optionally ask Gemini when the result lacks data."""
        try:
            result = await self.run(task)
        except ModelOverloadError as exc:
            return {
                "error": str(exc),
                "model_attempts": [asdict(attempt) for attempt in exc.attempts],
            }

        if result.get("data"):
            return result

        if not self.settings.gemini_api_key:
            result["warning"] = "Gemini fallback unavailable; set GEMINI_API_KEY."
            return result

        fallback_prompt = fallback_prompt or "Summarize the attached screenshots and list any PDF URLs."
        from pipelines.send_to_gemini import analyze_with_gemini

        gemini_summary = await analyze_with_gemini(prompt=fallback_prompt)
        result["gemini_fallback"] = gemini_summary
        return result

    def _history_to_result(self, history: AgentHistoryList) -> Dict[str, Any]:
        history_dict = history.model_dump()
        final_text = history.final_result()
        data = self._parse_json(final_text) if final_text else None
        result: Dict[str, Any] = {
            "history": history_dict,
            "final_text": final_text,
            "data": data,
        }
        if history.usage:
            result["usage"] = history.usage.model_dump()
        return result

    @staticmethod
    def _parse_json(payload: str | None) -> Any:
        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _is_model_overloaded_message(message: str | None) -> bool:
        if not message:
            return False
        lowered = message.lower()
        return "model is overloaded" in lowered or "503" in lowered and "unavailable" in lowered

    def _history_indicates_overload(self, history: AgentHistoryList) -> bool:
        payload = history.model_dump()
        for entry in payload.get("history", []):
            for result in entry.get("result", []):
                error = result.get("error")
                if self._is_model_overloaded_message(error):
                    return True
        return False


async def run_task(task: str) -> Dict[str, Any]:
    agent = BrowserUseAgent()
    return await agent.run_with_gemini_fallback(task)


def run_task_sync(task: str) -> Dict[str, Any]:
    return asyncio.run(run_task(task))
