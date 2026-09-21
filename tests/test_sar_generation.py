from backend.models.answer import FraudPattern, Verdict
from backend.policy.approvals import get_approval_route
from backend.policy.sar import evaluate_sar, generate_grounded_sar

def rows(): return [{"TransactionID":"T1","TransactionAmt":600,"ts":"2016-11-01 10:00:00"},{"TransactionID":"T2","TransactionAmt":500,"ts":"2016-11-02 10:00:00"}]
def build(**kwargs):
    decision = evaluate_sar(**kwargs)
    return generate_grounded_sar(decision=decision, customer_id="C1", card_id="C1-K1", connected_card_ids=(), episode_transactions=rows(), pattern=FraudPattern.CARD_NOT_PRESENT_FRAUD, known_subject_ids=("C1","C1-K1"), investigation_case_created=True)
def test_confirmed_exposure_report_is_l2_and_grounded():
    result = build(verdict=Verdict.FRAUD, fraud_probability=.9, exposure_usd=1100)
    assert result.sar.file and result.approval_route.value == "L2"
    assert result.sar.total_amount_usd == 1100 and result.sar.activity_dates == ["2016-11-01", "2016-11-02"]
    assert all(subject in {"C1","C1-K1"} for subject in result.sar.subjects)
def test_shared_and_undocumented_cases_report():
    assert build(verdict=Verdict.FRAUD, fraud_probability=.8, exposure_usd=1, shared_fraud_origin=True).sar.file
    assert build(verdict=Verdict.FRAUD, fraud_probability=.8, exposure_usd=1, coordinated_undocumented_abuse=True).sar.file
def test_below_threshold_legitimate_and_uncertain_do_not_report():
    for verdict in (Verdict.LEGITIMATE, Verdict.UNCERTAIN):
        assert not build(verdict=verdict, fraud_probability=.5, exposure_usd=10).sar.file
    assert not build(verdict=Verdict.FRAUD, fraud_probability=.8, exposure_usd=10).sar.file
