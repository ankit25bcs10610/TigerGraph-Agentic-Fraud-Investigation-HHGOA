"""Choosing the agent's next graph tool.

``RulePlanner`` encodes the investigator's default order. ``LLMPlanner`` lets
a model pick the next tool from the tools currently available, with a reason,
inside a step budget. The model can only choose from the allow-list the agent
offers; anything else (an unknown tool, a malformed reply, a provider error)
falls back to the rule planner, and the trace records that it did.

The planner decides *what to look at*. It never sees or sets the fraud
probability, the verdict, the actions or the approval routes.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Sequence

FINISH = "finish"


@dataclass(frozen=True)
class ToolOption:
    name: str
    description: str
    default_reason: str


@dataclass(frozen=True)
class Choice:
    tool: str
    reason: str
    planner: str          # "rules" | "llm" | "llm-fallback"


class RulePlanner:
    name = "rules"

    def choose(self, observations: str, options: Sequence[ToolOption], budget_left: int) -> Choice:
        if not options or budget_left <= 0:
            return Choice(FINISH, "Every applicable tool has been called.", self.name)
        option = options[0]
        return Choice(option.name, option.default_reason, self.name)


class LLMPlanner:
    """Asks a model which tool to call next; validates the answer against the allow-list."""

    name = "llm"
    SYSTEM = ("You direct a fraud investigation over a graph database. Pick the single most useful next tool from the options, "
              "or 'finish' when the evidence gathered is enough to assess the case. Use only the listed tool names. "
              "Reply as JSON: {\"tool\": \"<name or finish>\", \"reason\": \"<one sentence citing the observations>\"}.")

    def __init__(self, complete: Callable[[str, str], str] | None = None, fallback: RulePlanner | None = None) -> None:
        self._complete = complete or self._openai
        self.fallback = fallback or RulePlanner()

    @staticmethod
    def _openai(system: str, prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.chat.completions.create(model=os.getenv("LLM_MODEL", "gpt-4o-mini"), temperature=0,
                                                  response_format={"type": "json_object"},
                                                  messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}])
        return response.choices[0].message.content or ""

    def choose(self, observations: str, options: Sequence[ToolOption], budget_left: int) -> Choice:
        if not options or budget_left <= 0:
            return Choice(FINISH, "No tools left within the step budget.", self.name)
        menu = "\n".join(f"- {option.name}: {option.description}" for option in options)
        prompt = f"Observations so far:\n{observations}\n\nAvailable tools ({budget_left} steps left):\n{menu}\n- {FINISH}: stop gathering and assess the case"
        try:
            reply = json.loads(self._complete(self.SYSTEM, prompt))
            tool, reason = str(reply.get("tool", "")).strip(), str(reply.get("reason", "")).strip()
        except Exception:  # noqa: BLE001 - provider or parsing failure: rule planner decides
            choice = self.fallback.choose(observations, options, budget_left)
            return Choice(choice.tool, choice.reason, "llm-fallback")
        if tool == FINISH and reason:
            return Choice(FINISH, reason, self.name)
        if tool in {option.name for option in options} and reason:
            return Choice(tool, reason, self.name)
        choice = self.fallback.choose(observations, options, budget_left)
        return Choice(choice.tool, choice.reason, "llm-fallback")


def open_planner() -> Any:
    """The LLM planner when an OpenAI model is configured (and not switched off), otherwise rules."""
    enabled = os.getenv("LLM_PROVIDER", "disabled").strip().lower() == "openai" and os.getenv("OPENAI_API_KEY") and os.getenv("LLM_PLANNER", "on").lower() != "off"
    return LLMPlanner() if enabled else RulePlanner()
