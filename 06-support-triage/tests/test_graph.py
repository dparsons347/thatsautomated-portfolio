"""The ten canned emails through the real graph, with Claude and HubSpot scripted."""
from __future__ import annotations

import pytest

from app.graph import build_graph
from emails import BY_KEY, EMAILS
from tests.fakes import FakeCrm, ScriptedModel, cls, draft

# What the "model" says for each email. The lead seller is scripted the way the real model
# usually lands on it: sales, with low confidence.
CLASSIFY = {
    "Automating our lead entry": cls("sales", 0.93),
    "Reminder texts stopped": cls("support", 0.90),
    "September invoice and the Opelika office": cls("existing_client", 0.88),
    "Guest post collaboration for thatsautomated.com": cls("vendor", 0.97),
    "Following up": cls("unclear", 0.35),
    "Re: Automating our lead entry": cls("sales", 0.80, sentiment="negative"),
    "ACTION REQUIRED: mailbox storage full": cls("spam", 0.98),
    "Interested in automation for our clients": cls("sales", 0.60),
    "Exporting last month's reminders": cls("support", 0.86),
    "Saturday coverage?": cls("support", 0.84),
}
DRAFT = {subject: draft() for subject in CLASSIFY}
DRAFT["Exporting last month's reminders"] = draft(grounded=False, missing="whether the reminder log can be exported")

EXPECTED_ROUTE = {
    "sales_new": "draft", "support_login": "draft", "existing_client": "person",
    "vendor_pitch": "archive", "ambiguous": "person", "angry_reply": "person",
    "spam": "archive", "lead_seller": "person",
    "support_not_covered": "person", "support_hours": "draft",
}


def make(crm=None, classify=None, drafts=None):
    c = ScriptedModel(classify or CLASSIFY)
    d = ScriptedModel(drafts or DRAFT)
    g = build_graph(crm=crm or FakeCrm(), classifier=c.runnable(), drafter=d.runnable(),
                    booking_url="https://example.test/book")
    return g, c, d


def state_for(e, threshold=0.75):
    return {
        "message_id": e["key"], "thread_id": e["key"], "from_email": e["from_email"],
        "from_name": e["from_name"], "subject": e["subject"], "body": e["body"],
        "thread_history": e.get("history", []), "prior_category": e.get("prior_category"),
        "threshold": threshold,
    }


def test_ten_canned_emails_are_in_the_set():
    assert len(EMAILS) == 10
    assert set(EXPECTED_ROUTE) == set(BY_KEY)


@pytest.mark.parametrize("key", list(EXPECTED_ROUTE))
def test_route_for_each_canned_email(key):
    g, _, drafter = make()
    out = g.invoke(state_for(BY_KEY[key]))
    assert out["route"] == EXPECTED_ROUTE[key], out.get("gate_reasons")
    assert out["needs_human"] == (EXPECTED_ROUTE[key] == "person")
    drafted = bool(drafter.prompts)
    # Draft only runs for sales and support that passed the gate (or that the draft itself sent to a person).
    assert drafted == (key in {"sales_new", "support_login", "support_not_covered", "support_hours"})
    if not drafted:
        assert out.get("draft") is None


def test_known_client_context_reaches_the_model():
    g, classifier, _ = make()
    g.invoke(state_for(BY_KEY["existing_client"]))
    prompt = classifier.prompts[0]
    assert "Company: Webb Roofing" in prompt
    assert "Webb Roofing: estimate workflow | stage Won" in prompt


def test_unknown_sender_is_marked_unknown():
    g, classifier, _ = make()
    out = g.invoke(state_for(BY_KEY["sales_new"]))
    assert out["customer"] is None
    assert "No CRM record" in classifier.prompts[0]


def test_angry_reply_carries_thread_and_goes_to_a_person():
    g, classifier, _ = make()
    out = g.invoke(state_for(BY_KEY["angry_reply"]))
    assert out["is_reply"] is True
    assert "Negative reply on an open thread" in out["gate_reasons"]
    prompt = classifier.prompts[0]
    assert "[classified sales]" in prompt
    assert "Us:" in prompt  # our earlier reply is in the context


def test_reply_that_changes_category_goes_to_a_person():
    script = dict(CLASSIFY)
    script["Re: Automating our lead entry"] = cls("existing_client", 0.9, sentiment="neutral")
    g, _, _ = make(classify=script)
    out = g.invoke(state_for(BY_KEY["angry_reply"]))
    assert out["route"] == "person"
    assert "Thread moved from sales to existing_client" in out["gate_reasons"]


def test_threshold_decides_the_borderline_case():
    e = BY_KEY["lead_seller"]
    g, _, _ = make()
    assert g.invoke(state_for(e, threshold=0.55))["route"] == "draft"  # set too low: a lead seller gets a sales draft
    out = g.invoke(state_for(e, threshold=0.75))
    assert out["route"] == "person"
    assert out["gate_reasons"] == ["Confidence 0.60 is below the 0.75 threshold"]


def test_ungrounded_draft_is_kept_but_sent_to_a_person():
    g, _, _ = make()
    out = g.invoke(state_for(BY_KEY["support_not_covered"]))
    assert out["draft"]
    assert out["gate_reasons"] == ["Draft needs a person: whether the reminder log can be exported"]


def test_drafts_follow_house_style():
    g, _, _ = make()
    out = g.invoke(state_for(BY_KEY["support_login"]))
    assert "—" not in out["draft"]


def test_crm_outage_does_not_stop_triage():
    g, classifier, _ = make(crm=FakeCrm(fail=True))
    out = g.invoke(state_for(BY_KEY["support_login"]))
    assert out["route"] == "draft"
    assert out["lookup_error"].startswith("HubSpot unreachable")
    assert "CRM lookup failed" in classifier.prompts[0]


def test_sales_draft_uses_booking_link():
    g, _, drafter = make()
    g.invoke(state_for(BY_KEY["sales_new"]))
    assert "https://example.test/book" in drafter.prompts[0]
