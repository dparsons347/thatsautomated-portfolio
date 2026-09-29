import json

import httpx
import pytest

from app.hubspot import API, CrmError, HubSpotLookup


def transport(routes, calls):
    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path))
        assert request.headers["authorization"] == "Bearer tok"
        key = (request.method, request.url.path)
        if key not in routes:
            return httpx.Response(404, json={})
        status, payload = routes[key]
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


def lookup(routes, calls=None):
    calls = calls if calls is not None else []
    c = httpx.Client(base_url=API, transport=transport(routes, calls))
    return HubSpotLookup("tok", "247523905", client=c)


CONTACT = {"results": [{"id": "501", "properties": {
    "firstname": "Marcus", "lastname": "Webb", "email": "daniel+marcus@thatsautomated.com",
    "company": "Webb Roofing", "lifecyclestage": "customer", "hs_lead_status": None}}]}


def test_known_contact_with_deals():
    routes = {
        ("POST", "/crm/v3/objects/contacts/search"): (200, CONTACT),
        ("GET", "/crm/v4/objects/contacts/501/associations/deals"): (200, {"results": [{"toObjectId": 9}, {"toObjectId": 8}]}),
        ("POST", "/crm/v3/objects/deals/batch/read"): (200, {"results": [
            {"id": "8", "properties": {"dealname": "Old", "dealstage": "s-lost", "amount": "900", "closedate": "2025-01-02T00:00:00Z"}},
            {"id": "9", "properties": {"dealname": "Estimate workflow", "dealstage": "s-won", "amount": "3800", "closedate": "2026-08-20T00:00:00Z"}},
        ]}),
        ("GET", "/crm/v3/pipelines/deals"): (200, {"results": [{"stages": [
            {"id": "s-won", "label": "Won"}, {"id": "s-lost", "label": "Lost"}]}]}),
    }
    c = lookup(routes).lookup("Daniel+Marcus@thatsautomated.com ")
    assert c.name == "Marcus Webb" and c.company == "Webb Roofing"
    assert c.url == "https://app.hubspot.com/contacts/247523905/record/0-1/501"
    assert [(d.name, d.stage, d.close_date) for d in c.deals] == [
        ("Estimate workflow", "Won", "2026-08-20"), ("Old", "Lost", "2025-01-02")]


def test_search_is_by_exact_lowercased_email():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": []})
    lk = HubSpotLookup("tok", client=httpx.Client(base_url=API, transport=httpx.MockTransport(handler)))
    assert lk.lookup("A@B.COM") is None
    f = seen["body"]["filterGroups"][0]["filters"][0]
    assert f == {"propertyName": "email", "operator": "EQ", "value": "a@b.com"}


def test_contact_without_deals_skips_deal_calls():
    calls = []
    routes = {
        ("POST", "/crm/v3/objects/contacts/search"): (200, CONTACT),
        ("GET", "/crm/v4/objects/contacts/501/associations/deals"): (200, {"results": []}),
    }
    c = lookup(routes, calls).lookup("daniel+marcus@thatsautomated.com")
    assert c.deals == []
    assert ("POST", "/crm/v3/objects/deals/batch/read") not in calls


def test_hubspot_error_raises_crm_error():
    routes = {("POST", "/crm/v3/objects/contacts/search"): (401, {"message": "expired"})}
    with pytest.raises(CrmError, match="401"):
        lookup(routes).lookup("x@y.com")


def test_empty_email_does_not_call_hubspot():
    calls = []
    assert lookup({}, calls).lookup("") is None
    assert calls == []
