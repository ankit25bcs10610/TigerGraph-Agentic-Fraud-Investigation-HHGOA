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


def test_grounding_accepts_prose_and_rejects_invented_ids():
    from backend.app.llm.grounding import GroundingError, validate_synthesis
    from backend.app.llm.models import Synthesis

    cite = {"evidence_explanation": ["ref"], "uncertainty_explanation": ["ref"], "action_explanation": ["ref"], "case_summary": ["ref"]}
    prose = Synthesis(evidence_explanation="The Customer used a Device that Two other cards share.", uncertainty_explanation="The Card history is short.",
                      action_explanation="Decline and monitor.", case_summary="Transaction T-2005 looks like card testing.", citations=cite)
    assert validate_synthesis(prose, {"ref"}, {"T-2005"}) is prose
    invented = prose.model_copy(update={"case_summary": "Linked to card C99999-K4."})
    import pytest
    with pytest.raises(GroundingError):
        validate_synthesis(invented, {"ref"}, {"T-2005"})
