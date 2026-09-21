from __future__ import annotations
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Synthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern_description: str = ""
    evidence_explanation: str
    uncertainty_explanation: str
    action_explanation: str
    case_summary: str
    citations: dict[str, list[str]] = Field(default_factory=dict)
    @model_validator(mode="after")
    def cited_fields(self) -> "Synthesis":
        value = self.citations
        required = {"evidence_explanation", "uncertainty_explanation", "action_explanation", "case_summary"}
        if self.pattern_description.strip(): required.add("pattern_description")
        if not required <= set(value): raise ValueError("each factual synthesis field requires citations")
        if any(not refs for field, refs in value.items() if field in required): raise ValueError("factual synthesis fields require at least one citation")
        return self

@dataclass(frozen=True)
class LLMUsage:
    provider: str; model: str; input_tokens: int; output_tokens: int; total_tokens: int; latency_s: float; fallback: bool
