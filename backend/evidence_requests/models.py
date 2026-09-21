"""Strict request/response models. Simulated responses are never facts."""
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class RequestType(str, Enum):
    CUSTOMER_VALIDATION = "customer_validation"; STEP_UP_AUTH = "step_up_auth"; ANALYST_INFO = "analyst_info"
class RequestStatus(str, Enum): PENDING = "pending"; RESOLVED = "resolved"
class ResponseSource(str, Enum): CUSTOMER = "customer"; STEP_UP_AUTH = "step_up_auth"; ANALYST = "analyst"; SIMULATION = "simulation"
class CustomerResult(str, Enum): CONFIRMED = "confirmed"; DENIED = "denied"; NO_REPLY = "no_reply"; UNKNOWN = "unknown"
class StepUpResult(str, Enum): PASSED = "passed"; FAILED = "failed"; NOT_COMPLETED = "not_completed"; UNKNOWN = "unknown"

def now() -> datetime: return datetime.now(timezone.utc)
class StrictModel(BaseModel): model_config = ConfigDict(extra="forbid")
class EvidenceRequest(StrictModel):
    request_id: str; case_id: str; type: RequestType; question: str; reason: str
    requested_at: datetime = Field(default_factory=now); status: RequestStatus = RequestStatus.PENDING
    @field_validator("request_id", "case_id", "question", "reason")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip(): raise ValueError("field must not be empty")
        return value.strip()
class EvidenceResponse(StrictModel):
    request_id: str; case_id: str; type: RequestType; result: str; details: dict[str, Any] = Field(default_factory=dict)
    source: ResponseSource; simulated: bool; assumption: str; received_at: datetime = Field(default_factory=now)
    @model_validator(mode="after")
    def validate_response(self) -> "EvidenceResponse":
        allowed = CustomerResult._value2member_map_ if self.type is RequestType.CUSTOMER_VALIDATION else StepUpResult._value2member_map_ if self.type is RequestType.STEP_UP_AUTH else None
        if allowed is not None and self.result not in allowed: raise ValueError("result is invalid for evidence request type")
        if self.simulated and self.source is not ResponseSource.SIMULATION: raise ValueError("simulated evidence must use source=simulation")
        if self.simulated and not self.assumption.strip(): raise ValueError("simulated evidence requires a plain-language assumption")
        if self.type is RequestType.ANALYST_INFO:
            required = {"finding", "supporting_entity_ids", "confidence", "notes"}
            if not required <= set(self.details): raise ValueError("analyst_info details require finding, supporting_entity_ids, confidence, and notes")
        return self
