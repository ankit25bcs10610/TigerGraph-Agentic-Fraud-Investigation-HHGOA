from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator
from backend.models.answer import Case, EvidenceRequest, NextBestActions, SAR
class CaseOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: StrictStr; case: Case; evidence_requests: list[EvidenceRequest]
    next_best_actions: NextBestActions; sar: SAR; stop_reason: StrictStr
    tool_calls: list[dict[str, Any]]; tokens: StrictInt = Field(ge=0); latency_s: StrictFloat = Field(ge=0)
    @model_validator(mode="after")
    def shape(self) -> "CaseOutput":
        if not self.case_id.strip() or not self.stop_reason.strip(): raise ValueError("case_id and stop_reason are required")
        if self.case.verdict.value == "legitimate" and self.sar.file: raise ValueError("legitimate cases cannot file a SAR")
        return self
