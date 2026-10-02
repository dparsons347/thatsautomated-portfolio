# That's Automated portfolio

Eight working automation builds by Daniel Parsons (thatsautomated.com). Each one is a real system running on real accounts with fake customers. Every workflow has an error path that posts to Slack, every external write is idempotent, and every demo breaks something on camera to show what catches it.

Site: https://thatsautomated.com

| # | Project | Stack | Status |
|---|---|---|---|
| 01 | [Lead intake to HubSpot](01-lead-intake/) | n8n, HubSpot, Gmail, Slack, Python, Claude API | Built, video recorded |
| 02 | [Documents to QuickBooks](02-documents-quickbooks/) | n8n, Python, Claude API, QuickBooks Online, DocuSign, Google Sheets | Built, video recorded |
| 03 | [Shopify orders](03-shopify-orders/) | Python (FastAPI), Postgres, Shopify, Stripe, n8n | Built, video recorded |
| 04 | [GoHighLevel HVAC build](04-gohighlevel-hvac/) | GoHighLevel, Voice AI | Built, video pending |
| 05 | [Google Workspace intake](05-google-workspace/) | Apps Script, Gmail, Drive, Sheets, Google Chat, Data Studio | Built, video recorded |
| 06 | [Support triage with a human gate](06-support-triage/) | n8n, Python (FastAPI, LangGraph), Claude API, HubSpot, Gmail, Slack, LangSmith | Built, video recorded |
| 07 | [Notion operations](07-notion-ops/) | n8n, Notion, GoHighLevel, Slack | Live |
| 08 | [Zapier knowledge-base responder](08-zapier-kb-responder/) | Zapier Tables, Interfaces, Paths, Claude API, GoHighLevel | Built, video recorded |

## Conventions

- **Error path.** Every n8n workflow points at a shared Error Handler that posts the workflow name, failing node, error, and execution link to `#automation-alerts`. Nothing fails silently.
- **Idempotent writes.** Lookup before create, keyed on email, external ID, or a hash. Running a trigger twice produces one record.
- **Bounded retries.** Retries have a count and a log line.
- **Fake data.** Company names, customers, and jobs are invented. Phone numbers and email addresses are ones I control.
- **No secrets.** Exported workflow JSON has credential IDs stripped. Each project has a `.env.example` naming every variable it needs.

## Layout

Each project folder has a README (what it does, how to run it, what breaks and what catches it), exported workflow definitions where the platform allows it, and screenshots of the execution logs used in the walkthrough videos.
