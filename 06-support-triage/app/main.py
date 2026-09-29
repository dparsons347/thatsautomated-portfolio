"""HTTP wrapper around the triage graph. Only n8n calls this, over the Docker network."""
from __future__ import annotations

import hmac
import logging
import os
import threading
import uuid
from typing import Any, Optional

import anthropic
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ValidationError

from .config import Settings
from .graph import build_graph
from .hubspot import HubSpotLookup, NoCrm
from .schemas import TriageRequest, TriageResponse
from .slack_verify import verify

log = logging.getLogger("triage")


class TraceLinks:
    """Builds LangSmith run URLs. Looks up the org and project once, then caches."""

    def __init__(self, project: str):
        self._project = project
        self._prefix: Optional[str] = None
        self._lock = threading.Lock()

    def url(self, run_id: str) -> Optional[str]:
        if os.environ.get("LANGSMITH_TRACING", "").lower() != "true" or not os.environ.get("LANGSMITH_API_KEY"):
            return None
        with self._lock:
            if self._prefix is None:
                try:
                    from langsmith import Client
                    c = Client()
                    proj = c.read_project(project_name=self._project)
                    self._prefix = f"{c._host_url}/o/{c._get_tenant_id()}/projects/p/{proj.id}/r/"
                except Exception as exc:  # the project appears after the first trace lands
                    log.info("trace link not ready yet: %s", exc)
                    return None
        return f"{self._prefix}{run_id}?poll=true"


class SlackCheck(BaseModel):
    timestamp: str
    signature: str
    body: str


def create_app(settings: Optional[Settings] = None, graph: Any = None) -> FastAPI:
    s = settings or Settings.from_env()
    if graph is None:
        from . import llm
        crm = HubSpotLookup(s.hubspot_token, s.hubspot_portal_id) if s.hubspot_token else NoCrm()
        graph = build_graph(crm=crm, classifier=llm.classifier(s), drafter=llm.drafter(s),
                            booking_url=s.booking_url)
    links = TraceLinks(s.langsmith_project)
    app = FastAPI(title="Support triage", docs_url=None, redoc_url=None)

    def require_key(x_webhook_key: str = Header(default="")) -> None:
        # Same X-Webhook-Key header convention as the other portfolio services.
        # Fail closed: no key configured means nobody gets in.
        if not s.triage_api_key or not hmac.compare_digest(x_webhook_key, s.triage_api_key):
            raise HTTPException(status_code=401, detail="bad api key")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "model": s.claude_model, "threshold": s.confidence_threshold,
                "crm": "hubspot" if s.hubspot_token else "none",
                "tracing": os.environ.get("LANGSMITH_TRACING", "false")}

    @app.post("/triage", response_model=TriageResponse, dependencies=[Depends(require_key)])
    def triage(req: TriageRequest):
        threshold = req.threshold if req.threshold is not None else s.confidence_threshold
        run_id = str(uuid.uuid4())
        state = req.model_dump()
        state["thread_history"] = [m.model_dump() for m in req.thread_history]
        state["threshold"] = threshold
        config = {
            "run_name": "support-triage",
            "run_id": run_id,
            "tags": ["p6"],
            "metadata": {"message_id": req.message_id, "thread_id": req.thread_id,
                         "from_email": req.from_email, "threshold": threshold},
        }
        try:
            out = graph.invoke(state, config=config)
        except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.APIStatusError) as exc:
            log.warning("model unavailable for %s: %s", req.message_id, exc)
            return JSONResponse(status_code=503, content={
                "error": "model_unavailable", "detail": f"{exc.__class__.__name__}: {str(exc)[:200]}",
                "run_id": run_id})
        except (ValidationError, OutputParserException) as exc:
            log.warning("model returned bad output for %s: %s", req.message_id, exc)
            return JSONResponse(status_code=502, content={
                "error": "bad_model_output", "detail": str(exc)[:300], "run_id": run_id})

        c = out["classification"]
        return TriageResponse(
            message_id=req.message_id,
            category=c["category"], confidence=round(float(c["confidence"]), 2),
            reason=c["reason"], sentiment=c["sentiment"], summary=c["summary"],
            is_reply=out.get("is_reply", False),
            route=out["route"], needs_human=out["needs_human"],
            gate_reasons=out.get("gate_reasons") or [],
            threshold=threshold,
            customer=out.get("customer"), lookup_error=out.get("lookup_error"),
            draft=out.get("draft"),
            run_id=run_id, trace_url=links.url(run_id),
        )

    @app.post("/slack/verify", dependencies=[Depends(require_key)])
    def slack_verify(check: SlackCheck) -> dict:
        ok, why = verify(s.slack_signing_secret, check.timestamp, check.signature, check.body)
        return {"valid": ok, "reason": why}

    return app
