"""Strict Pydantic models for the README Answer Format."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    # Enum values are intentionally parsed from their exact wire-format
    # strings; scalar fields below use Strict* types to prevent coercion.
    model_config = ConfigDict(extra="forbid")


class CaseStatus(str, Enum):
    OPEN = "open"
    CLOSED_FRAUD = "closed_fraud"
    CLOSED_LEGITIMATE = "closed_legitimate"
    ESCALATED = "escalated"


class Verdict(str, Enum):
    FRAUD = "fraud"
    LEGITIMATE = "legitimate"
    UNCERTAIN = "uncertain"


class FraudPattern(str, Enum):
    CARD_TESTING = "card_testing"
    CARD_NOT_PRESENT_FRAUD = "card_not_present_fraud"
    CARD_NOT_PRESENT_NEW_DEVICE = "card_not_present_new_device"
    OUT_OF_REGION_USE = "out_of_region_use"
    ACCOUNT_TAKEOVER = "account_takeover"
    UNDOCUMENTED = "undocumented"
    NONE = "none"


class EvidenceSource(str, Enum):
    GRAPH = "graph"
    DOCUMENT = "document"
    CUSTOMER = "customer"
    EXTERNAL = "external"


class EvidenceRequestType(str, Enum):
    CUSTOMER_VALIDATION = "customer_validation"
    STEP_UP_AUTH = "step_up_auth"
    ANALYST_INFO = "analyst_info"


class ApprovalRoute(str, Enum):
    AUTO = "auto"
    L1 = "L1"
    L2 = "L2"


class PolicyAction(str, Enum):
    ALLOW_TRANSACTION = "ALLOW_TRANSACTION"
    DECLINE_TRANSACTION = "DECLINE_TRANSACTION"
    MONITOR_CARD = "MONITOR_CARD"
    MONITOR_CONNECTED_CARDS = "MONITOR_CONNECTED_CARDS"
    WARN_CUSTOMER = "WARN_CUSTOMER"
    VERIFY_WITH_CUSTOMER = "VERIFY_WITH_CUSTOMER"
    STEP_UP_AUTH = "STEP_UP_AUTH"
    BLOCK_CARD = "BLOCK_CARD"
    BLOCK_ALL_CARDS = "BLOCK_ALL_CARDS"
    GENERATE_REPORT = "GENERATE_REPORT"
    CREATE_CASE = "CREATE_CASE"
    FILE_REPORT = "FILE_REPORT"
    ESCALATE_TO_ANALYST = "ESCALATE_TO_ANALYST"
    CLOSE_NO_FRAUD = "CLOSE_NO_FRAUD"


class Evidence(StrictModel):
    claim: StrictStr
    source: EvidenceSource
    ref: StrictStr
    entity_ids: list[StrictStr]


class EvidenceRequest(StrictModel):
    type: EvidenceRequestType
    asked_after_step: StrictInt = Field(ge=0)
    assumed_response: StrictStr


class Action(StrictModel):
    action: PolicyAction
    route: ApprovalRoute
    reason: StrictStr


class Case(StrictModel):
    status: CaseStatus
    verdict: Verdict
    fraud_probability: Annotated[StrictFloat, Field(ge=0.0, le=1.0)]
    pattern: FraudPattern
    pattern_description: StrictStr
    affected_txn_ids: list[StrictStr]
    first_suspicious_txn_id: StrictStr
    connected_card_ids: list[StrictStr]
    connected_device_profiles: list[StrictStr]
    exposure_usd: Annotated[StrictFloat, Field(ge=0.0)]
    evidence: list[Evidence]
    similar_prior_cases: list[StrictStr]
    summary: StrictStr
    written_to_graph: StrictBool
    graph_case_id: StrictStr

    @model_validator(mode="after")
    def validate_pattern_description(self) -> "Case":
        description_is_empty = self.pattern_description == ""
        if self.pattern is FraudPattern.UNDOCUMENTED and description_is_empty:
            raise ValueError(
                "pattern_description is required when pattern is 'undocumented'"
            )
        if self.pattern is not FraudPattern.UNDOCUMENTED and not description_is_empty:
            raise ValueError(
                "pattern_description must be empty unless pattern is 'undocumented'"
            )
        if self.verdict is Verdict.LEGITIMATE:
            if self.affected_txn_ids:
                raise ValueError(
                    "affected_txn_ids must be empty for a legitimate verdict"
                )
            if self.exposure_usd != 0:
                raise ValueError("exposure_usd must be 0 for a legitimate verdict")
        return self


class NextBestActions(StrictModel):
    initial: list[Action]
    final: list[Action]
    what_changed: StrictStr


class SAR(StrictModel):
    file: StrictBool
    reason: StrictStr
    narrative: StrictStr
    subjects: list[StrictStr]
    total_amount_usd: Annotated[StrictFloat, Field(ge=0.0)]
    activity_dates: list[StrictStr]

    @field_validator("activity_dates")
    @classmethod
    def validate_activity_dates(cls, value: list[str]) -> list[str]:
        for item in value:
            try:
                date.fromisoformat(item)
            except ValueError as exc:
                raise ValueError(
                    "activity_dates must contain ISO dates in YYYY-MM-DD format"
                ) from exc
        return value

    @model_validator(mode="after")
    def validate_file_shape(self) -> "SAR":
        if self.file:
            if not self.narrative:
                raise ValueError("narrative is required when sar.file is true")
            if len(self.activity_dates) != 2:
                raise ValueError(
                    "activity_dates must contain first and last date when sar.file is true"
                )
        else:
            if self.narrative != "":
                raise ValueError("narrative must be empty when sar.file is false")
            if self.subjects:
                raise ValueError("subjects must be empty when sar.file is false")
            if self.total_amount_usd != 0:
                raise ValueError(
                    "total_amount_usd must be 0 when sar.file is false"
                )
            if self.activity_dates:
                raise ValueError(
                    "activity_dates must be empty when sar.file is false"
                )
        return self


class Answer(StrictModel):
    case_id: StrictStr
    case: Case
    evidence_requests: list[EvidenceRequest]
    next_best_actions: NextBestActions
    sar: SAR
    stop_reason: StrictStr
    tool_calls: StrictInt = Field(ge=0)
    tokens: StrictInt = Field(ge=0)
    latency_s: Annotated[StrictFloat, Field(ge=0.0)]

    @field_validator("case_id", "stop_reason")
    @classmethod
    def validate_nonempty_text(cls, value: str) -> str:
        if not value:
            raise ValueError("value must not be empty")
        return value

    @model_validator(mode="after")
    def validate_report_action_consistency(self) -> "Answer":
        final_files_report = any(
            item.action is PolicyAction.FILE_REPORT
            for item in self.next_best_actions.final
        )
        if self.sar.file != final_files_report:
            raise ValueError(
                "sar.file must agree with whether FILE_REPORT appears in final actions"
            )
        return self
