from __future__ import annotations
import os, time
from dataclasses import dataclass
from typing import Protocol
from .models import LLMUsage, Synthesis

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
        try: response = self.client.responses.parse(model=self.settings.model, input=[{"role":"system","content":system_prompt},{"role":"user","content":context}], text_format=Synthesis)
        except Exception as error: raise LLMUnavailable("Structured LLM synthesis failed.") from error
        parsed = response.output_parsed
        if not isinstance(parsed, Synthesis): raise LLMUnavailable("Provider returned no structured synthesis.")
        usage = response.usage
        return parsed, LLMUsage(self.settings.provider, self.settings.model, int(getattr(usage,"input_tokens",0)), int(getattr(usage,"output_tokens",0)), int(getattr(usage,"total_tokens",0)), time.perf_counter()-started, False)
def create_client(settings: LLMSettings) -> StructuredLLM:
    if settings.provider != "openai": raise LLMUnavailable("LLM synthesis is disabled.")
    return OpenAIStructuredLLM(settings)
