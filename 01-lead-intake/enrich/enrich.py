"""Lead enrichment for Project 1, as plain Python.

Same logic as the "Project 1: Enrich lead" n8n workflow: pick the company site
from the email domain, fetch it with a hard timeout and bounded retries, strip
it to text, have Claude describe the business as JSON, then score the lead
with visible rules. Every failure path still returns a score and a reason.

Standard library only. Network calls go through small injectable functions so
the tests never touch the network.

    python enrich.py --email sam@example.com --name "Sam Carter" \
        --company "Carter HVAC" --phone 334-555-0100 --message "Need a quote"

Needs ANTHROPIC_API_KEY in the environment for the summary step.
"""

import argparse
import html as html_lib
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request

FETCH_TIMEOUT_S = 10
FETCH_TRIES = 3
FETCH_WAIT_S = 2
CLAUDE_TIMEOUT_S = 30
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
MIN_TEXT_CHARS = 200
MAX_TEXT_CHARS = 8000
USER_AGENT = "Mozilla/5.0 (compatible; ThatsAutomatedLeadBot/1.0; +https://thatsautomated.com)"

PERSONAL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "live.com", "msn.com", "aol.com", "icloud.com", "me.com", "mac.com",
    "proton.me", "protonmail.com", "gmx.com", "mail.com", "yandex.com",
    "zoho.com", "att.net", "comcast.net", "bellsouth.net", "charter.net",
    "sbcglobal.net", "verizon.net", "cox.net",
}

SIZE_HINTS = ("1_10", "11_50", "51_200", "200_plus", "unknown")
SIZE_POINTS = {"1_10": 10, "11_50": 25, "51_200": 30, "200_plus": 20}
SIZE_LABEL = {"1_10": "1-10", "11_50": "11-50", "51_200": "51-200", "200_plus": "200+", "unknown": "unknown"}
URGENCY = re.compile(r"\b(today|tomorrow|asap|urgent|emergency|this week|right away)\b", re.I)

SUMMARY_SYSTEM = (
    "You read the text of a small business's public website and describe the business "
    "for a sales rep who is about to call them.\n\n"
    "Return ONLY a JSON object, no prose, no code fences, with exactly these keys:\n"
    '{"what_they_do": string, "size_hint": "1_10"|"11_50"|"51_200"|"200_plus"|"unknown", '
    '"location": string, "services": [string], "summary": string}\n\n'
    "Rules:\n"
    "- Use only what the page says. Do not guess or pad.\n"
    '- what_they_do: one short phrase, e.g. "residential and commercial plumbing".\n'
    "- size_hint: based only on explicit signals such as staff counts, number of locations, "
    'fleet size, or team pages. If there are none, use "unknown".\n'
    '- location: city and state if stated, else "".\n'
    "- services: up to 6 short items.\n"
    "- summary: two sentences, under 300 characters, plain words, no marketing language."
)


class FetchError(Exception):
    """The company site could not be read. The message is shown to the rep."""


# ---------------------------------------------------------------- website


def pick_website(email):
    """Return (site_url, personal_email, fail_reason) for a lead's email."""
    domain = email.split("@")[1].strip().lower() if "@" in email else ""
    if not domain:
        return "", False, "no email domain"
    if domain in PERSONAL_DOMAINS:
        return "", True, "personal email address, no company site to read"
    return "https://" + domain, False, ""


def _urlopen_text(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def fetch_site(url, opener=_urlopen_text, tries=FETCH_TRIES, timeout=FETCH_TIMEOUT_S,
               wait_s=FETCH_WAIT_S, sleep=time.sleep):
    """GET the page with a per-attempt timeout and a fixed number of tries.

    Timeouts, DNS failures, refused connections and 5xx are retried. A 4xx is
    not, since asking again will not change the answer. Raises FetchError with
    a short reason after the last try.
    """
    last = "request failed"
    for attempt in range(1, tries + 1):
        try:
            return opener(url, timeout)
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
            if e.code < 500:
                break
        except (socket.timeout, TimeoutError):
            last = "timed out after %ds" % timeout
        except urllib.error.URLError as e:
            reason = e.reason
            if isinstance(reason, (socket.timeout, TimeoutError)):
                last = "timed out after %ds" % timeout
            else:
                last = str(reason)
        except OSError as e:
            last = str(e) or e.__class__.__name__
        if attempt < tries:
            sleep(wait_s)
    raise FetchError("site unreachable: " + last[:120])


def extract_page_text(page_html):
    """Strip HTML to readable text. Returns (text, fail_reason)."""
    title_m = re.search(r"<title[^>]*>([\s\S]*?)</title>", page_html, re.I)
    desc_m = re.search(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']*)", page_html, re.I)
    title = html_lib.unescape(title_m.group(1)).strip() if title_m else ""
    desc = html_lib.unescape(desc_m.group(1)).strip() if desc_m else ""
    body = re.sub(r"<(script|style|noscript)[\s\S]*?</\1>", " ", page_html, flags=re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", " ", html_lib.unescape(body)).strip()
    if len(text) < MIN_TEXT_CHARS:
        return "", "site has too little readable text"
    return "\n".join(p for p in (title, desc, text) if p)[:MAX_TEXT_CHARS], ""


# ---------------------------------------------------------------- Claude


def _post_json(url, headers, payload, timeout):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_claude(page_text, api_key, post=_post_json, timeout=CLAUDE_TIMEOUT_S):
    """Ask Claude for the JSON company summary. Returns the raw text reply."""
    body = post(
        "https://api.anthropic.com/v1/messages",
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        {
            "model": CLAUDE_MODEL,
            "max_tokens": 600,
            "temperature": 0,
            "system": SUMMARY_SYSTEM,
            "messages": [{"role": "user", "content": "Company website text:\n\n" + page_text}],
        },
        timeout,
    )
    return "".join(part.get("text", "") for part in body.get("content", []))


def parse_summary(raw):
    """Pull the JSON object out of a model reply and clean each field.

    Tolerates code fences and prose around the object. Unknown size hints
    become "unknown". Returns (summary_dict, fail_reason); the dict is None
    when nothing usable came back.
    """
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None, "could not parse Claude output"
    try:
        p = json.loads(raw[start:end + 1])
    except ValueError:
        return None, "could not parse Claude output"
    if not isinstance(p, dict):
        return None, "could not parse Claude output"
    services = p.get("services")
    return {
        "what_they_do": str(p.get("what_they_do") or ""),
        "size_hint": p.get("size_hint") if p.get("size_hint") in SIZE_HINTS else "unknown",
        "location": str(p.get("location") or ""),
        "services": [str(s) for s in services[:6]] if isinstance(services, list) else [],
        "summary": str(p.get("summary") or "")[:400],
    }, ""


# ---------------------------------------------------------------- scoring


def score_lead(lead, summary, personal_email):
    """Rules-based 0-100 score. Returns (score, reasons)."""
    score, why = 20, ["20 base"]
    if summary:
        score += 20
        why.append("+20 company site read")
        pts = SIZE_POINTS.get(summary["size_hint"])
        if pts:
            score += pts
            why.append("+%d size %s" % (pts, SIZE_LABEL[summary["size_hint"]]))
    message = lead.get("message") or ""
    if lead.get("phone"):
        score += 10
        why.append("+10 phone given")
    if lead.get("company"):
        score += 5
        why.append("+5 company named")
    if len(message) > 60:
        score += 10
        why.append("+10 detailed request")
    if URGENCY.search(message):
        score += 10
        why.append("+10 urgency")
    if personal_email:
        score -= 10
        why.append("-10 personal email")
    return max(0, min(100, score)), why


# ---------------------------------------------------------------- pipeline


def enrich_lead(lead, fetch=fetch_site, summarize=None):
    """Run the whole enrichment for one lead dict and return the result.

    `summarize` takes page text and returns the raw model reply. It defaults to
    call_claude with ANTHROPIC_API_KEY. The result has the same fields the n8n
    workflow writes to HubSpot: enrichment_status, lead_score, company_summary,
    company_size_hint, plus fail_reason and score_reasons for the Slack note.
    """
    if summarize is None:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        summarize = lambda text: call_claude(text, key)  # noqa: E731

    site_url, personal, fail = pick_website(lead.get("email", ""))
    summary = None
    if site_url:
        try:
            text, fail = extract_page_text(fetch(site_url))
        except FetchError as e:
            text, fail = "", str(e)
        if text:
            try:
                raw = summarize(text)
            except (urllib.error.URLError, socket.timeout, TimeoutError, OSError, ValueError):
                raw, fail = "", "Claude call failed"
            if raw:
                summary, fail = parse_summary(raw)

    score, why = score_lead(lead, summary, personal)
    return {
        "email": lead.get("email", ""),
        "enrichment_status": "done" if summary else "failed",
        "lead_score": score,
        "score_reasons": ", ".join(why),
        "company_summary": (summary["summary"] + (" (%s)" % summary["location"] if summary["location"] else ""))
        if summary else "",
        "company_size_hint": summary["size_hint"] if summary else "unknown",
        "what_they_do": summary["what_they_do"] if summary else "",
        "services": summary["services"] if summary else [],
        "fail_reason": "" if summary else (fail or "enrichment unavailable"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Enrich and score one lead.")
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--company", default="")
    ap.add_argument("--phone", default="")
    ap.add_argument("--message", default="")
    args = ap.parse_args(argv)
    result = enrich_lead(vars(args))
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
