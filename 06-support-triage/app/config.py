"""Settings, read once from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    anthropic_base_url: str
    claude_model: str
    llm_timeout_seconds: float
    confidence_threshold: float
    hubspot_token: str
    hubspot_portal_id: str
    triage_api_key: str
    slack_signing_secret: str
    booking_url: str
    langsmith_project: str

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            anthropic_api_key=e("ANTHROPIC_API_KEY", ""),
            # Point this at a dead host to demo the outage path.
            anthropic_base_url=e("ANTHROPIC_BASE_URL", "") or "https://api.anthropic.com",
            claude_model=e("CLAUDE_MODEL", "") or "claude-sonnet-5-5",
            llm_timeout_seconds=_float("LLM_TIMEOUT_SECONDS", 30.0),
            confidence_threshold=_float("CONFIDENCE_THRESHOLD", 0.75),
            hubspot_token=e("HUBSPOT_TOKEN", ""),
            hubspot_portal_id=e("HUBSPOT_PORTAL_ID", ""),
            triage_api_key=e("TRIAGE_API_KEY", ""),
            slack_signing_secret=e("SLACK_SIGNING_SECRET", ""),
            booking_url=e("BOOKING_URL", "") or "https://thatsautomated.com/contact",
            langsmith_project=e("LANGSMITH_PROJECT", "") or "p6-support-triage",
        )
