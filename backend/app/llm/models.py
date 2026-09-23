from __future__ import annotations
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, model_validator


class CitationSet(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"required": ["pattern_description", "evidence_explanation", "uncertainty_explanation", "action_explanation", "case_summary"]},
    )
    pattern_description: list[str] = []
    evidence_explanation: list[str] = []
    uncertainty_explanation: list[str] = []
    action_explanation: list[str] = []
    case_summary: list[str] = []

    def __getitem__(self, field: str) -> list[str]:
        return getattr(self, field)

    def items(self):
        return self.model_dump().items()

class Synthesis(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"required": ["pattern_description", "evidence_explanation", "uncertainty_explanation", "action_explanation", "case_summary", "citations"]},
    )
    pattern_description: str = ""
    evidence_explanation: str
    uncertainty_explanation: str
    action_explanation: str
    case_summary: str
    citations: CitationSet
    @model_validator(mode="after")
    def cited_fields(self) -> "Synthesis":
        value = self.citations.model_dump()
        required = {"evidence_explanation", "uncertainty_explanation", "action_explanation", "case_summary"}
        if self.pattern_description.strip(): required.add("pattern_description")
        if not required <= set(value): raise ValueError("each factual synthesis field requires citations")
        if any(not refs for field, refs in value.items() if field in required): raise ValueError("factual synthesis fields require at least one citation")
        return self

@dataclass(frozen=True)
class LLMUsage:
    provider: str; model: str; input_tokens: int; output_tokens: int; total_tokens: int; latency_s: float; fallback: bool
