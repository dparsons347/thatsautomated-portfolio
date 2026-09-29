"""The triage graph: lookup -> classify -> gate -> (draft).

The model does two narrow jobs (classify, draft). Everything that decides what
happens next is plain code in `decide()`, so it can be unit tested without a model.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional, TypedDict

from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph

from . import prompts
from .hubspot import CrmError, CustomerLookup
from .schemas import DRAFT_CATEGORIES, Classification, Customer, Draft

FAQ = (Path(__file__).parent / "faq.md").read_text()


class TriageState(TypedDict, total=False):
    # input
    message_id: str
    thread_id: str
    from_email: str
    from_name: str
    subject: str
    body: str
    thread_history: list[dict]
    prior_category: Optional[str]
    threshold: float
    # filled in by nodes
    is_reply: bool
    customer: Optional[dict]
    lookup_error: Optional[str]
    classification: dict
    route: str
    needs_human: bool
    gate_reasons: list[str]
    draft: Optional[str]


# ---------- pure helpers (unit tested directly) ----------

def decide(c: Classification, *, is_reply: bool, prior_category: Optional[str],
           threshold: float) -> tuple[str, bool, list[str]]:
    """Return (route, needs_human, reasons). Route is draft, person, or archive."""
    reasons: list[str] = []
    if c.category == "unclear":
        reasons.append("Category is unclear")
    if c.confidence < threshold:
        reasons.append(f"Confidence {c.confidence:.2f} is below the {threshold:.2f} threshold")
    if is_reply and c.sentiment == "negative":
        reasons.append("Negative reply on an open thread")
    if is_reply and prior_category and prior_category != c.category:
        reasons.append(f"Thread moved from {prior_category} to {c.category}")
    if c.category == "existing_client":
        reasons.append("Known client, goes to the account owner")
    if reasons:
        return "person", True, reasons
    if c.category in DRAFT_CATEGORIES:
        return "draft", False, []
    return "archive", False, []


def customer_block(customer: Optional[dict], lookup_error: Optional[str]) -> str:
    if lookup_error:
        return f"(CRM lookup failed: {lookup_error}. Treat the sender as unknown.)"
    if not customer:
        return "(No CRM record. The sender is not a known contact.)"
    c = Customer(**customer)
    lines = [f"Name: {c.name or '(none)'}", f"Company: {c.company or '(none)'}",
             f"Lifecycle stage: {c.lifecycle_stage or '(none)'}"]
    if c.deals:
        lines.append("Deals:")
        lines += [f"- {d.name} | stage {d.stage} | amount {d.amount or '-'} | close {d.close_date or '-'}"
                  for d in c.deals]
    else:
        lines.append("Deals: none")
    return "\n".join(lines)


def thread_block(history: list[dict]) -> str:
    if not history:
        return "(none, this is a new conversation)"
    out = []
    for i, m in enumerate(history, 1):
        who = "Us" if m.get("direction") == "outbound" else (m.get("from_email") or "Sender")
        cat = f" [classified {m['category']}]" if m.get("category") else ""
        body = (m.get("body") or "").strip()[:1500]
        out.append(f"{i}. {who}{cat}:\n{body}")
    return "\n\n".join(out)


_DASH = re.compile(r"\s*[—–]\s*")


def tidy(text: str) -> str:
    """House style: no em or en dashes in anything we send."""
    return _DASH.sub(", ", text).strip()


# ---------- graph ----------

def build_graph(*, crm: CustomerLookup, classifier: Runnable, drafter: Runnable,
                booking_url: str) -> Any:
    """classifier returns a Classification, drafter returns a Draft (both take a message list)."""

    def lookup(state: TriageState) -> dict:
        try:
            cust = crm.lookup(state["from_email"])
            return {"customer": cust.model_dump() if cust else None, "lookup_error": None}
        except CrmError as exc:
            # A CRM outage should not stop triage. The card says the lookup failed.
            return {"customer": None, "lookup_error": str(exc)}

    def classify(state: TriageState) -> dict:
        history = state.get("thread_history") or []
        user = prompts.classify_user(
            from_name=state.get("from_name", ""), from_email=state["from_email"],
            subject=state.get("subject", ""), body=state["body"],
            customer_block=customer_block(state.get("customer"), state.get("lookup_error")),
            thread_block=thread_block(history),
        )
        result: Classification = classifier.invoke(
            [("system", prompts.CLASSIFY_SYSTEM), ("user", user)])
        return {"classification": result.model_dump(), "is_reply": bool(history)}

    def gate(state: TriageState) -> dict:
        c = Classification(**state["classification"])
        route, needs_human, reasons = decide(
            c, is_reply=state.get("is_reply", False),
            prior_category=state.get("prior_category"), threshold=state["threshold"])
        return {"route": route, "needs_human": needs_human, "gate_reasons": reasons}

    def draft(state: TriageState) -> dict:
        category = state["classification"]["category"]
        template = (prompts.SALES_TEMPLATE.format(booking_url=booking_url)
                    if category == "sales" else prompts.SUPPORT_TEMPLATE)
        user = prompts.draft_user(
            category=category, from_name=state.get("from_name") or state["from_email"],
            subject=state.get("subject", ""), body=state["body"],
            customer_block=customer_block(state.get("customer"), state.get("lookup_error")),
            template=template,
        )
        result: Draft = drafter.invoke(
            [("system", prompts.DRAFT_SYSTEM.format(faq=FAQ)), ("user", user)])
        out: dict = {"draft": tidy(result.reply)}
        if not result.grounded:
            missing = result.missing.strip() or "facts the standard answers do not cover"
            out.update(route="person", needs_human=True,
                       gate_reasons=[f"Draft needs a person: {missing}"])
        return out

    g = StateGraph(TriageState)
    g.add_node("lookup", lookup)
    g.add_node("classify", classify)
    g.add_node("gate", gate)
    g.add_node("draft", draft)
    g.add_edge(START, "lookup")
    g.add_edge("lookup", "classify")
    g.add_edge("classify", "gate")
    g.add_conditional_edges("gate", lambda s: "draft" if s["route"] == "draft" else END,
                            {"draft": "draft", END: END})
    g.add_edge("draft", END)
    return g.compile()
