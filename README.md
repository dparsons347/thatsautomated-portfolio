# That's Automated portfolio

Eight working automation builds by Daniel Parsons (thatsautomated.com). Each one is a real system running on real accounts with fake customers. Every workflow has an error path that posts to Slack, every external write is idempotent, and every demo breaks something on camera to show what catches it.

Site: https://thatsautomated.com

| # | Project | Stack | Status |
|---|---|---|---|
| 01 | [Lead intake to HubSpot](01-lead-intake/) | n8n, HubSpot, Facebook Lead Ads, Python, Claude API | Queued |
| 02 | [Documents to QuickBooks](02-documents-quickbooks/) | n8n, DocuSign, QuickBooks Online, Claude API | Queued |
| 03 | [Shopify orders](03-shopify-orders/) | n8n, Shopify, Stripe, Postgres | Queued |
| 04 | [GoHighLevel HVAC build](04-gohighlevel-hvac/) | GoHighLevel, A2P 10DLC, Voice AI | In progress |
| 05 | [Microsoft 365](05-microsoft-365/) | Power Automate, Power Query, Power BI | Queued |
| 06 | [Support triage with a human gate](06-support-triage/) | n8n, LangGraph, Claude API, Slack, LangSmith | Queued |
| 07 | [Notion operations](07-notion-ops/) | n8n, Notion, GoHighLevel, Slack | Live |
| 08 | [Zapier knowledge-base responder](08-zapier-kb-responder/) | Zapier Tables, Interfaces, Paths, Claude API, GoHighLevel | In progress |

## Conventions

- **Error path.** Every n8n workflow points at a shared Error Handler that posts the workflow name, failing node, error, and execution link to `#automation-alerts`. Nothing fails silently.
- **Idempotent writes.** Lookup before create, keyed on email, external ID, or a hash. Running a trigger twice produces one record.
- **Bounded retries.** Retries have a count and a log line.
- **Fake data.** Company names, customers, and jobs are invented. Phone numbers and email addresses are ones I control.
- **No secrets.** Exported workflow JSON has credential IDs stripped. Each project has a `.env.example` naming every variable it needs.

## Layout

Each project folder has a README (what it does, how to run it, what breaks and what catches it), exported workflow definitions where the platform allows it, and screenshots of the execution logs used in the Loom.
