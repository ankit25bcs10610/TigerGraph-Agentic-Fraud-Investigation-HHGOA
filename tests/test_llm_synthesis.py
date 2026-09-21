import pytest
from backend.app.llm.client import LLMSettings
from backend.app.llm.grounding import GroundingError, validate_synthesis
from backend.app.llm.models import Synthesis
from backend.app.llm.synthesis import GroundedSynthesisService

@pytest.mark.parametrize("verdict", ["fraud", "legitimate", "uncertain"])
def test_disabled_llm_preserves_deterministic_context(verdict: str) -> None:
    context = {"fraud_probability": 0.42, "verdict": verdict, "final_actions": [{"action":"MONITOR_CARD"}], "graph_evidence":[{"ref":"graph:transaction_context","entity_ids":["C123"]}]}
    output, usage = GroundedSynthesisService(LLMSettings("disabled", "", None)).synthesize(context)
    assert usage.fallback and output.citations["case_summary"] == ["graph:transaction_context"]
    assert context["fraud_probability"] == 0.42 and context["final_actions"][0]["action"] == "MONITOR_CARD"

def test_grounding_rejects_unknown_ids() -> None:
    synthesis = Synthesis(evidence_explanation="Card C999 was used.", uncertainty_explanation="Uncertain.", action_explanation="Policy applies.", case_summary="Review C999.", citations={field:["graph:x"] for field in ("evidence_explanation","uncertainty_explanation","action_explanation","case_summary")})
    with pytest.raises(GroundingError): validate_synthesis(synthesis, {"graph:x"}, {"C123"})
