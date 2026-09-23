from __future__ import annotations
import os, time
from dataclasses import dataclass
from typing import Protocol
from pydantic import BaseModel, ConfigDict
from .models import LLMUsage, Synthesis


class _WireSynthesis(BaseModel):
    """Strict-mode schema for OpenAI structured outputs: every field required, no free-form maps.

    Converted to ``Synthesis`` after parsing, so grounding validation is unchanged.
    """
    model_config = ConfigDict(extra="forbid")
    pattern_description: str
    evidence_explanation: str
    uncertainty_explanation: str
    action_explanation: str
    case_summary: str
    pattern_description_citations: list[str]
    evidence_explanation_citations: list[str]
    uncertainty_explanation_citations: list[str]
    action_explanation_citations: list[str]
    case_summary_citations: list[str]

    def to_synthesis(self) -> Synthesis:
        fields = ("evidence_explanation", "uncertainty_explanation", "action_explanation", "case_summary")
        citations = {name: getattr(self, f"{name}_citations") for name in fields}
        if self.pattern_description.strip():
            citations["pattern_description"] = self.pattern_description_citations
        return Synthesis(pattern_description=self.pattern_description, evidence_explanation=self.evidence_explanation,
                         uncertainty_explanation=self.uncertainty_explanation, action_explanation=self.action_explanation,
                         case_summary=self.case_summary, citations=citations)

class LLMUnavailable(RuntimeError): pass
class StructuredLLM(Protocol):
    def synthesize(self, system_prompt: str, context: str) -> tuple[Synthesis, LLMUsage]: ...
@dataclass(frozen=True)
class LLMSettings:
    provider: str; model: str; api_key: str | None
    @classmethod
    def from_environment(cls, environ: dict[str, str] | None = None) -> "LLMSettings":
        values = os.environ if environ is None else environ
        provider, model, key = values.get("LLM_PROVIDER", "disabled").strip(), values.get("LLM_MODEL", "").strip(), values.get("OPENAI_API_KEY", "").strip() or None
        if provider == "disabled": return cls(provider, model, None)
        if provider != "openai" or not model or not key: raise LLMUnavailable("LLM_PROVIDER=openai requires LLM_MODEL and OPENAI_API_KEY.")
        return cls(provider, model, key)
class OpenAIStructuredLLM:
    def __init__(self, settings: LLMSettings) -> None:
        try:
            from openai import OpenAI
        except ImportError as error: raise LLMUnavailable("OpenAI SDK is unavailable.") from error
        self.client, self.settings = OpenAI(api_key=settings.api_key), settings
    def synthesize(self, system_prompt: str, context: str) -> tuple[Synthesis, LLMUsage]:
        started = time.perf_counter()
        parsed, response, last_error = None, None, None
        for _attempt in range(2):  # one retry: an uncited field is rejected, never accepted
            try: response = self.client.responses.parse(model=self.settings.model, input=[{"role":"system","content":system_prompt},{"role":"user","content":context}], text_format=_WireSynthesis)
            except Exception as error: raise LLMUnavailable(f"Structured LLM synthesis failed: {type(error).__name__}") from error
            wire = response.output_parsed
            if not isinstance(wire, _WireSynthesis): last_error = LLMUnavailable("Provider returned no structured synthesis."); continue
            try: parsed = wire.to_synthesis(); break
            except ValueError as error: last_error = error
        if parsed is None: raise LLMUnavailable("Provider synthesis lacked required citations.") from last_error
        usage = response.usage
        return parsed, LLMUsage(self.settings.provider, self.settings.model, int(getattr(usage,"input_tokens",0)), int(getattr(usage,"output_tokens",0)), int(getattr(usage,"total_tokens",0)), time.perf_counter()-started, False)
def create_client(settings: LLMSettings) -> StructuredLLM:
    if settings.provider != "openai": raise LLMUnavailable("LLM synthesis is disabled.")
    return OpenAIStructuredLLM(settings)
