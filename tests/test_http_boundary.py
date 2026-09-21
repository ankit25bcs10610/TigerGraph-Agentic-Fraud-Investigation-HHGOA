from fastapi.testclient import TestClient

from backend.main import create_app


class Provider:
    def list(self):
        return [{"case_id": "demo-1"}]

    def get(self, case_id):
        if case_id != "demo-1":
            raise KeyError(case_id)
        return {"case_id": case_id}


class Workflow:
    def start_investigation(self, case_input):
        return {"case_id": case_input["case_id"]}

    def resume_with_approval(self, case_id, decision):
        return {"case_id": case_id, "approval": decision}

    def resume_with_evidence(self, case_id, evidence):
        return {"case_id": case_id, "evidence": evidence}

    def get_investigation_state(self, case_id):
        return {"case_id": case_id}


def test_reference_routes_are_wired():
    client = TestClient(create_app(Workflow(), Provider()))
    assert client.get("/health").json()["workflow_configured"] is True
    assert client.get("/cases").json() == [{"case_id": "demo-1"}]
    assert client.post("/investigations/start", json={"case_id": "demo-1"}).status_code == 200
    assert client.post("/investigations/demo-1/evidence", json={"evidence": {"result": "unknown"}}).status_code == 200
    assert client.post("/investigations/demo-1/approval", headers={"x-user-role": "fraud_approver"}, json={"action": "MONITOR_CARD", "approved": True}).status_code == 200


def test_unconfigured_runtime_is_explicit():
    client = TestClient(create_app())
    assert client.get("/health").json()["workflow_configured"] is False
    assert client.get("/cases").status_code == 503
