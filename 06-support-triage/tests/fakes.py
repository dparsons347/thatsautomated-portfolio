"""Scripted stand-ins for Claude and HubSpot, so the graph can be tested without either."""
from __future__ import annotations

from typing import Callable, Optional

from langchain_core.runnables import RunnableLambda

from app.hubspot import CrmError
from app.schemas import Classification, Customer, Deal, Draft

KNOWN = {
    "daniel+priya@thatsautomated.com": Customer(
        contact_id="101", name="Priya Raman", email="daniel+priya@thatsautomated.com",
        company="Raman Family Dental", lifecycle_stage="customer",
        deals=[Deal(name="Raman Dental: appointment reminders", stage="Won", amount="2400", close_date="2026-07-15")]),
    "daniel+marcus@thatsautomated.com": Customer(
        contact_id="102", name="Marcus Webb", email="daniel+marcus@thatsautomated.com",
        company="Webb Roofing", lifecycle_stage="customer",
        deals=[Deal(name="Webb Roofing: estimate workflow", stage="Won", amount="3800", close_date="2026-08-20")]),
    "daniel+sam@thatsautomated.com": Customer(
        contact_id="103", name="Sam Ortiz", email="daniel+sam@thatsautomated.com",
        company="Ortiz Plumbing", lifecycle_stage="lead"),
}


class FakeCrm:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[str] = []

    def lookup(self, email: str) -> Optional[Customer]:
        self.calls.append(email)
        if self.fail:
            raise CrmError("HubSpot unreachable: ConnectError")
        return KNOWN.get(email)


def _user_text(messages) -> str:
    return messages[-1][1]


class ScriptedModel:
    """Returns a scripted result chosen by which subject line appears in the prompt."""

    def __init__(self, script: dict[str, object], raises: Optional[Exception] = None):
        self.script = script
        self.raises = raises
        self.prompts: list[str] = []

    def _pick(self, messages):
        text = _user_text(messages)
        self.prompts.append(text)
        if self.raises:
            raise self.raises
        # longest subject first so "Re: X" wins over "X"
        for subject in sorted(self.script, key=len, reverse=True):
            if f"Subject: {subject}\n" in text:
                return self.script[subject]
        raise AssertionError("no scripted answer for prompt:\n" + text[:400])

    def runnable(self):
        return RunnableLambda(self._pick)


def cls(category, confidence, sentiment="neutral", reason="scripted", summary="scripted") -> Classification:
    return Classification(category=category, confidence=confidence, reason=reason,
                          sentiment=sentiment, summary=summary)


def draft(reply="Thanks for reaching out — here is the answer.\n\nDaniel\nThat's Automated",
          grounded=True, missing="") -> Draft:
    return Draft(reply=reply, grounded=grounded, missing=missing)


Factory = Callable[..., object]
