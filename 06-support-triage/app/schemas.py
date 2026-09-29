"""Request, response and model-output shapes."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["sales", "support", "existing_client", "vendor", "spam", "unclear"]
Sentiment = Literal["positive", "neutral", "negative"]
Route = Literal["draft", "person", "archive"]

CATEGORIES: tuple[str, ...] = ("sales", "support", "existing_client", "vendor", "spam", "unclear")
DRAFT_CATEGORIES: frozenset[str] = frozenset({"sales", "support"})


class ThreadMessage(BaseModel):
    """An earlier message on the same Gmail thread, oldest first."""

    from_email: str = ""
    body: str = ""
    category: Optional[str] = None
    direction: Literal["inbound", "outbound"] = "inbound"


class TriageRequest(BaseModel):
    message_id: str
    thread_id: str = ""
    from_email: str
    from_name: str = ""
    subject: str = ""
    body: str
    thread_history: list[ThreadMessage] = Field(default_factory=list)
    prior_category: Optional[str] = None
    # Optional override so the threshold can be changed from n8n without a redeploy.
    threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class Deal(BaseModel):
    name: str
    stage: str = ""
    amount: Optional[str] = None
    close_date: Optional[str] = None


class Customer(BaseModel):
    contact_id: str
    name: str = ""
    email: str = ""
    company: str = ""
    lifecycle_stage: str = ""
    lead_status: str = ""
    url: str = ""
    deals: list[Deal] = Field(default_factory=list)


class Classification(BaseModel):
    """What the classify node asks Claude to return."""

    category: Category = Field(description="One of the six categories.")
    confidence: float = Field(ge=0.0, le=1.0, description="0 to 1. How sure you are of the category.")
    reason: str = Field(description="One sentence, under 25 words, saying why this category.")
    sentiment: Sentiment = Field(description="The sender's tone in THIS message.")
    summary: str = Field(description="One line: what the sender wants.")


class Draft(BaseModel):
    """What the draft node asks Claude to return."""

    reply: str = Field(description="The reply body, plain text, no subject line.")
    grounded: bool = Field(
        description="True only if every fact in the reply comes from the standard answers or the sender's own message."
    )
    missing: str = Field(default="", description="If not grounded: what a person needs to answer.")


class TriageResponse(BaseModel):
    message_id: str
    category: Category
    confidence: float
    reason: str
    sentiment: Sentiment
    summary: str
    is_reply: bool
    route: Route
    needs_human: bool
    gate_reasons: list[str]
    threshold: float
    customer: Optional[Customer] = None
    lookup_error: Optional[str] = None
    draft: Optional[str] = None
    run_id: Optional[str] = None
    trace_url: Optional[str] = None
