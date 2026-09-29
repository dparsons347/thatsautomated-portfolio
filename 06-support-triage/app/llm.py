"""Claude via LangChain, with structured output for both model calls."""
from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.runnables import Runnable

from .config import Settings
from .schemas import Classification, Draft


def _model(s: Settings, max_tokens: int) -> ChatAnthropic:
    return ChatAnthropic(
        model=s.claude_model,
        api_key=s.anthropic_api_key,
        base_url=s.anthropic_base_url,
        max_tokens=max_tokens,
        default_request_timeout=s.llm_timeout_seconds,
        # One retry inside the call. Longer outages are n8n's job (queue and retry).
        max_retries=1,
    )


def classifier(s: Settings) -> Runnable:
    return _model(s, 600).with_structured_output(Classification, method="json_schema").with_config(run_name="claude-classify")


def drafter(s: Settings) -> Runnable:
    return _model(s, 1200).with_structured_output(Draft, method="json_schema").with_config(run_name="claude-draft")
