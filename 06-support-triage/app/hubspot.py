"""Customer lookup in HubSpot: contact by email, plus its deals."""
from __future__ import annotations

import threading
from typing import Optional, Protocol

import httpx

from .schemas import Customer, Deal

API = "https://api.hubapi.com"
CONTACT_PROPS = ["firstname", "lastname", "email", "company", "lifecyclestage", "hs_lead_status"]
DEAL_PROPS = ["dealname", "dealstage", "amount", "closedate", "pipeline"]


class CrmError(Exception):
    """The CRM could not be reached or refused the request."""


class CustomerLookup(Protocol):
    def lookup(self, email: str) -> Optional[Customer]: ...


class NoCrm:
    """Used when no HubSpot token is configured. Every sender is unknown."""

    def lookup(self, email: str) -> Optional[Customer]:
        return None


class HubSpotLookup:
    def __init__(self, token: str, portal_id: str = "", *, client: Optional[httpx.Client] = None,
                 timeout: float = 8.0):
        self._portal_id = portal_id
        self._client = client or httpx.Client(base_url=API, timeout=timeout)
        self._headers = {"Authorization": f"Bearer {token}"}
        self._stage_labels: Optional[dict[str, str]] = None
        self._lock = threading.Lock()

    def _call(self, method: str, path: str, **kw) -> dict:
        try:
            r = self._client.request(method, path, headers=self._headers, **kw)
        except httpx.HTTPError as exc:
            raise CrmError(f"HubSpot unreachable: {exc.__class__.__name__}") from exc
        if r.status_code >= 400:
            raise CrmError(f"HubSpot {method} {path} returned {r.status_code}")
        return r.json()

    def _stages(self) -> dict[str, str]:
        with self._lock:
            if self._stage_labels is None:
                data = self._call("GET", "/crm/v3/pipelines/deals")
                self._stage_labels = {
                    s["id"]: s.get("label", s["id"])
                    for p in data.get("results", [])
                    for s in p.get("stages", [])
                }
            return self._stage_labels

    def lookup(self, email: str) -> Optional[Customer]:
        email = (email or "").strip().lower()
        if not email:
            return None
        found = self._call("POST", "/crm/v3/objects/contacts/search", json={
            "filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}],
            "properties": CONTACT_PROPS,
            "limit": 1,
        })
        results = found.get("results") or []
        if not results:
            return None
        c = results[0]
        props = c.get("properties") or {}
        cid = str(c["id"])
        name = " ".join(x for x in (props.get("firstname"), props.get("lastname")) if x)
        url = f"https://app.hubspot.com/contacts/{self._portal_id}/record/0-1/{cid}" if self._portal_id else ""
        return Customer(
            contact_id=cid,
            name=name,
            email=props.get("email") or email,
            company=props.get("company") or "",
            lifecycle_stage=props.get("lifecyclestage") or "",
            lead_status=props.get("hs_lead_status") or "",
            url=url,
            deals=self._deals(cid),
        )

    def _deals(self, contact_id: str) -> list[Deal]:
        assoc = self._call("GET", f"/crm/v4/objects/contacts/{contact_id}/associations/deals")
        ids = [str(a["toObjectId"]) for a in assoc.get("results", [])][:10]
        if not ids:
            return []
        data = self._call("POST", "/crm/v3/objects/deals/batch/read", json={
            "properties": DEAL_PROPS,
            "inputs": [{"id": i} for i in ids],
        })
        stages = self._stages()
        deals = []
        for d in data.get("results", []):
            p = d.get("properties") or {}
            deals.append(Deal(
                name=p.get("dealname") or "(unnamed deal)",
                stage=stages.get(p.get("dealstage") or "", p.get("dealstage") or ""),
                amount=p.get("amount"),
                close_date=(p.get("closedate") or "")[:10] or None,
            ))
        deals.sort(key=lambda d: d.close_date or "", reverse=True)
        return deals
