"""Grounded context construction and graceful deterministic fallback."""
from __future__ import annotations
import json, time
from typing import Any
from .client import LLMSettings, LLMUnavailable, create_client
from .grounding import id_tokens, validate_synthesis
from .models import LLMUsage, Synthesis
from .prompts import CITATION_GUIDE, SYSTEM_PROMPT

def _references(context: dict[str, Any]) -> tuple[set[str], set[str]]:
    refs, ids = set(), set()
    for evidence in context.get("graph_evidence", []) + context.get("similar_prior_cases", []) + context.get("retrieved_policy", []) + context.get("retrieved_patterns", []):
        if isinstance(evidence, dict):
            if evidence.get("ref"): refs.add(str(evidence["ref"]))
            ids.update(str(value) for value in evidence.get("entity_ids", []) if value)
    refs.update(str(value) for value in context.get("policy_rule_ids", []) if value)
    ids.update(str(value) for value in context.get("entity_ids", []) if value)
    return refs, ids

class GroundedSynthesisService:
    def __init__(self, settings: LLMSettings | None = None) -> None: self.settings = settings or LLMSettings.from_environment()
    def synthesize(self, context: dict[str, Any]) -> tuple[Synthesis, LLMUsage]:
        refs, ids = _references(context)
        # The model may mention an identifier or figure only if it appears in the supplied records.
        ids |= id_tokens(json.dumps(context, default=str))
        if not refs: refs.add("deterministic_pipeline")
        try:
            result, usage = create_client(self.settings).synthesize(SYSTEM_PROMPT + " " + CITATION_GUIDE, json.dumps(context, default=str))
            return validate_synthesis(result, refs, ids), usage
        except LLMUnavailable:
            return self._fallback(context, refs)
    def _fallback(self, context: dict[str, Any], refs: set[str]) -> tuple[Synthesis, LLMUsage]:
        citation = sorted(refs)[0]; pattern = context.get("detected_pattern", "")
        result = Synthesis(pattern_description=str(context.get("pattern_description", "")) if pattern == "undocumented" else "", evidence_explanation="Deterministic investigation evidence is available in the cited records.", uncertainty_explanation="No LLM synthesis was available; uncertainty remains governed by deterministic evidence grading.", action_explanation="Proposed actions are produced by the deterministic policy and approval modules.", case_summary="Investigation result is based on the deterministic pipeline and grounded records.", citations={field:[citation] for field in ("evidence_explanation", "uncertainty_explanation", "action_explanation", "case_summary")})
        return result, LLMUsage(self.settings.provider, self.settings.model, 0, 0, 0, 0.0, True)
