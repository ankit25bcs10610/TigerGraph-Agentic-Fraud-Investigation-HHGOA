import pytest
from backend.app.output.models import CaseOutput
from backend.app.output.validator import CatalogResolver, OutputValidationError, StopContext, validate_output

def payload(): return {"case_id":"HHG-X","case":{"status":"closed_fraud","verdict":"fraud","fraud_probability":.9,"pattern":"none","pattern_description":"","affected_txn_ids":["T1"],"first_suspicious_txn_id":"T1","connected_card_ids":["C1-K2"],"connected_device_profiles":[],"exposure_usd":5.0,"evidence":[{"claim":"fact","source":"graph","ref":"q","entity_ids":["T1"]}],"similar_prior_cases":["CC1"],"summary":"s","written_to_graph":True,"graph_case_id":"IC1"},"evidence_requests":[],"next_best_actions":{"initial":[],"final":[],"what_changed":"nothing"},"sar":{"file":False,"reason":"no report","narrative":"","subjects":[],"total_amount_usd":0.0,"activity_dates":[]},"stop_reason":"two sources","tool_calls":[],"tokens":0,"latency_s":0.0}
def resolver(): return CatalogResolver({"Transaction":{"T1"},"Card":{"C1-K2"},"ClosedCase":{"CC1"},"InvestigationCase":{"IC1"}})
def test_valid_output(): validate_output(CaseOutput.model_validate(payload()),resolver(),stop=StopContext(independent_evidence_count=2))
@pytest.mark.parametrize("change",[("case.fraud_probability",1.1),("case.exposure_usd",-1),("case.affected_txn_ids",["T1","T1"]),("case.connected_card_ids",["C999"])])
def test_invalid_references_and_values(change):
    raw=payload(); target,key=change[0].split("."); raw[target][key]=change[1]
    with pytest.raises(Exception): validate_output(CaseOutput.model_validate(raw),resolver(),stop=StopContext(independent_evidence_count=2))
def test_legitimate_and_missing_graph_case_rejected():
    raw=payload(); raw["case"].update({"verdict":"legitimate","affected_txn_ids":[],"exposure_usd":0.0,"fraud_probability":.1,"written_to_graph":False,"graph_case_id":""}); raw["sar"]["file"]=True
    with pytest.raises(Exception): CaseOutput.model_validate(raw)
    raw=payload(); raw["case"]["graph_case_id"]="missing"
    with pytest.raises(OutputValidationError): validate_output(CaseOutput.model_validate(raw),resolver(),stop=StopContext(independent_evidence_count=2))
