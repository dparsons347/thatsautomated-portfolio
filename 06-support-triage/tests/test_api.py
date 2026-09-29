import anthropic
import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.graph import build_graph
from app.main import create_app
from app.slack_verify import sign
from emails import BY_KEY
from tests.fakes import FakeCrm, ScriptedModel
from tests.test_graph import CLASSIFY, DRAFT

KEY = "test-key"


def settings(**over):
    base = dict(anthropic_api_key="x", anthropic_base_url="https://api.anthropic.com",
                claude_model="claude-sonnet-5-5", llm_timeout_seconds=5, confidence_threshold=0.75,
                hubspot_token="", hubspot_portal_id="", triage_api_key=KEY,
                slack_signing_secret="shh", booking_url="https://example.test/book",
                langsmith_project="test")
    base.update(over)
    return Settings(**base)


def client(raises=None, **over):
    g = build_graph(crm=FakeCrm(), classifier=ScriptedModel(CLASSIFY, raises=raises).runnable(),
                    drafter=ScriptedModel(DRAFT).runnable(), booking_url="https://example.test/book")
    return TestClient(create_app(settings(**over), graph=g))


def body(key, **extra):
    e = BY_KEY[key]
    b = {"message_id": f"m-{key}", "thread_id": f"t-{key}", "from_email": e["from_email"],
         "from_name": e["from_name"], "subject": e["subject"], "body": e["body"],
         "thread_history": e.get("history", []), "prior_category": e.get("prior_category")}
    b.update(extra)
    return b


def test_health_is_open():
    assert client().get("/health").json()["ok"] is True


def test_triage_needs_the_key():
    c = client()
    assert c.post("/triage", json=body("sales_new")).status_code == 401
    assert c.post("/triage", json=body("sales_new"), headers={"x-webhook-key": "wrong"}).status_code == 401


def test_no_key_configured_fails_closed():
    c = client(triage_api_key="")
    assert c.post("/triage", json=body("sales_new"), headers={"x-webhook-key": ""}).status_code == 401


def test_triage_returns_the_card_fields():
    r = client().post("/triage", json=body("existing_client"), headers={"x-webhook-key": KEY})
    assert r.status_code == 200
    j = r.json()
    assert j["category"] == "existing_client"
    assert j["route"] == "person" and j["needs_human"] is True
    assert j["customer"]["company"] == "Webb Roofing"
    assert j["draft"] is None
    assert j["run_id"]
    assert j["threshold"] == 0.75


def test_threshold_override_per_request():
    c = client()
    h = {"x-webhook-key": KEY}
    assert c.post("/triage", json=body("lead_seller", threshold=0.55), headers=h).json()["route"] == "draft"
    assert c.post("/triage", json=body("lead_seller"), headers=h).json()["route"] == "person"


def test_model_outage_is_a_503_not_a_guess():
    err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://dead.invalid/v1/messages"))
    r = client(raises=err).post("/triage", json=body("sales_new"), headers={"x-webhook-key": KEY})
    assert r.status_code == 503
    assert r.json()["error"] == "model_unavailable"


def test_slack_verify_endpoint():
    c = client()
    import time
    ts = str(int(time.time()))
    raw = "payload=%7B%22type%22%3A%22block_actions%22%7D"
    good = {"timestamp": ts, "signature": sign("shh", ts, raw), "body": raw}
    assert c.post("/slack/verify", json=good, headers={"x-webhook-key": KEY}).json()["valid"] is True
    bad = dict(good, body=raw + "x")
    assert c.post("/slack/verify", json=bad, headers={"x-webhook-key": KEY}).json() == {
        "valid": False, "reason": "signature mismatch"}
