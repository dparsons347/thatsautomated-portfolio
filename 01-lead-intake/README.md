# 01 - Lead intake to HubSpot

Leads come in from two places, get cleaned and checked, land in HubSpot once (no duplicates), and the rep gets a Slack alert within seconds. Enrichment and scoring happen after the alert so nobody waits on them. Built Sep 26, 2026 on n8n, HubSpot (free CRM), Slack, Google Sheets and Claude.

## What this proves

- Two intake sources feeding one pipeline without two copies of the logic.
- Dedupe by email: the same person submitting twice updates one contact and does not open a second deal.
- Junk never reaches the CRM: missing fields, bad emails, spam keywords, and disposable domains are rejected and logged with a reason.
- Rate limits and outages are handled: HubSpot writes back off and retry, and a lead that still cannot be written is posted to a human instead of vanishing.
- Enrichment fails soft: a dead site or bad model output still produces a score and says why.

## Sources

| Source | How it arrives | Parsing |
|---|---|---|
| Website form | `POST /webhook/lead-intake` with name, email, phone, company, message | Direct field mapping |
| Email | Anything sent to `daniel+leads@thatsautomated.com` gets the `leads/inbound` Gmail label; n8n polls the label every minute | Claude (Haiku 4.5) extracts the customer from the email, including Angi/Thumbtack-style notifications where the customer is inside the forwarded body, and flags non-leads |

## Workflows

Exports are in `n8n/`. Credential IDs are stripped; on import, attach your own HubSpot (service key), Slack, Google Sheets, Gmail and Anthropic credentials, then re-point the data table, sheet, Slack channel and sub-workflow IDs to your own.

### Project 1: Lead intake

1. Normalize both sources to one shape.
2. Basic checks: email present and valid, name present, no spam keywords, no more than 3 links. Failures go to the Lead log as `rejected` with the reason.
3. Disposable domain check against an n8n data table (about 9,000 domains).
4. HubSpot contact upsert by email. Sets `lead_source_detail` and `enrichment_status = pending`.
5. New contact: create a deal in New, post to `#leads`, log `new`, start enrichment without waiting. Existing contact: post an "updated lead" note and log `updated`.

**Backoff on HubSpot writes.** Any error on the upsert (429, 5xx, timeout) goes to a retry loop that waits 2, 4, then 8 seconds. After the 4th failed attempt the full lead is posted to `#automation-alerts` and logged as `failed`. A test hook in front of the upsert fails the first N attempts with a fake 429 when the form payload includes `"_simulate_429": N`. That is how the Loom shows both outcomes:

```bash
# recovers on attempt 3
curl -X POST https://<n8n-host>/webhook/lead-intake -H 'Content-Type: application/json' \
  -d '{"name":"Rita Backoff","email":"rita@example.com","message":"test","_simulate_429":2}'
# gives up after 4 attempts and alerts
curl ... -d '{"name":"Gil GivesUp","email":"gil@example.com","message":"test","_simulate_429":5}'
```

### Project 1: Enrich lead

Called by intake. Picks the company site from the email domain (skips Gmail, Yahoo and other personal domains), fetches it with a 10 s timeout and 3 tries, strips it to text, has Claude return a JSON description (what they do, size, location, services, two-sentence summary), then scores the lead. Writes `enrichment_status`, `lead_score`, `company_summary`, `company_size_hint` to HubSpot and replies in the lead's Slack thread.

Scoring is plain rules so a rep can see why a lead got its number:

| Signal | Points |
|---|---|
| Base | 20 |
| Company site read | +20 |
| Size 1-10 / 11-50 / 51-200 / 200+ | +10 / +25 / +30 / +20 |
| Phone given | +10 |
| Company named | +5 |
| Message over 60 characters | +10 |
| Urgency words (today, tomorrow, asap, urgent, emergency, this week, right away) | +10 |
| Personal email domain | -10 |

Clamped to 0-100.

### Project 1: Retry enrichment

Hourly at :17. Searches HubSpot for contacts still `pending` or `failed`, created between 15 minutes and 3 days ago, and runs enrichment again. At most 3 retries per contact, counted in workflow static data. Each retry posts its result to `#leads` labeled "(Retry 1 of 3)" and so on.

### Project 1: Refresh disposable domains

Sundays at 3am Central. Pulls the public disposable-email-domains blocklist from GitHub and replaces the data table, but only if the new list has at least 1,000 entries, so a bad download never empties the filter.

All four point at the shared Error Handler workflow.

## Python version of enrichment

`enrich/` has the same enrichment logic as a standalone Python module (standard library only) with tests for the parts most likely to go wrong: fetch timeouts and retries, and parsing whatever the model sends back.

In n8n the fetch is an HTTP Request node and scoring is a JavaScript Code node. The Python module is the same rules in a form you can unit test, or run as a service if a client's n8n instance has no Python runner (mine doesn't: the stock Docker image ships without Python 3, so a `pythonNative` Code node fails with "Python runner unavailable").

```bash
cd enrich
python3 -m unittest -v test_enrich.py     # 28 tests, no network
ANTHROPIC_API_KEY=... python3 enrich.py --email sam@example.com --name "Sam" --phone 334-555-0100 --message "Need a quote this week"
```

What the tests pin down:

- Every fetch attempt gets the timeout. Three timeouts means three tries, two waits, then a clear "timed out after 10s" reason.
- 5xx and network errors are retried. A 404 is not, since asking again will not change the answer.
- Claude replies with code fences, prose around the JSON, truncated JSON, wrong types, or a made-up size hint are all handled. The worst case is "could not parse Claude output" and a form-only score, never a crash.
- Scores match what the n8n workflow produced for the same test leads.

## HubSpot setup

Custom contact properties: `enrichment_status` (pending/done/failed), `company_summary`, `company_size_hint` (1_10/11_50/51_200/200_plus/unknown), `lead_score` (number), `lead_source_detail` (website_form/Email). Deals go in the default pipeline's New stage.

## What breaks and what catches it

| Failure | What happens |
|---|---|
| Spam or incomplete submission | Rejected before HubSpot, logged with the reason |
| Disposable email | Rejected, logged as `disposable email domain (x.com)` |
| Same person submits twice | One contact, one deal, second submission posts as "updated lead" |
| HubSpot 429 or outage | 2/4/8 s backoff, then `#automation-alerts` with the full lead and a `failed` log row |
| Company site down or slow | 10 s timeout, 3 tries, then scored from form fields with the reason in Slack; hourly retry picks it up later |
| Claude returns junk | Parsed defensively, falls back to form-only score |
| Any unhandled node error | Error Handler posts workflow, node, error and execution link to `#automation-alerts` |
