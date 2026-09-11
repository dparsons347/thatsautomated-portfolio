# 07 - Notion operations

The agency's own back office: four Notion databases and three n8n workflows that keep them in sync with the website, GoHighLevel, and Slack. Built Sep 11, 2026 and running since.

## What this proves

- A small business can run intake, project tracking, and pipeline reporting out of Notion without anyone typing leads in by hand.
- Two-way sync with a CRM (GoHighLevel) without loops: inbound creates records, outbound moves stages, and neither triggers the other.
- Duplicate intake is handled: the same person submitting twice, or arriving from two sources, produces one Client record.

## Notion databases

All four live under one page, "That's Automated Ops". Relations are two-way.

| Database | Key properties | Purpose |
|---|---|---|
| Clients | Name, Email, Phone, Company, Status (Prospect/Active/Past/Lost), Source, GHL Contact ID, rollup of project statuses | One record per person or company |
| Projects | Name, Client (relation), Status (Inquiry/Scoping/Proposal sent/Active/On hold/Done/Lost), Type (Client/Portfolio/Internal), Platform (multi-select), Start, Target, GHL Opportunity ID, Site Page, Loom, Repo, Summary, rollup of open tasks | Client work and portfolio builds |
| Proposals | Job Title, Client, Project, Channel, Job ID, Job URL, Bid, Bid Type, Connects, Status, Sent | Upwork and other bids |
| Tasks | Name, Project (relation), Status (Todo/Doing/Blocked/Done), Priority, Due | Work items |

## Workflows

Exports are in `n8n/`. Credential IDs are stripped; on import, attach your own Notion, Slack, Gmail, and GHL credentials.

### Intake to Notion

Two webhook triggers feed one path.

- `POST /webhook/contact-form`: the thatsautomated.com contact form.
- `POST /webhook/intake-ghl`: a Webhook action in the GoHighLevel workflow that runs on new leads. GHL posts its full contact and opportunity object.

Both are normalized to the same shape (name, email, phone, company, source, project name, summary, GHL contact and opportunity IDs). Email is lowercased and trimmed. Then:

1. Query Clients for an exact email match.
2. If none, create the Client (status Prospect, source from the trigger).
3. Create a Project in Inquiry linked to the Client, carrying the GHL opportunity ID if there is one.
4. Post to `#leads` with a link to the project.
5. Site-form leads also get an owner email.

Note on the GHL payload: the stage field arrives as `pipleline_stage` (GHL's spelling). Custom fields arrive by label, so `Service Type`, `Equipment`, and `Preferred Contact Channel` are read by those names.

### Status Sync (Notion to GHL)

Polls the Projects database every minute for edited pages. When a project has a GHL Opportunity ID and its status maps to a pipeline stage, it PUTs the opportunity in GHL and logs one line to `#automation-alerts`.

| Notion status | GHL stage |
|---|---|
| Inquiry | New lead |
| Scoping, Proposal sent | Contacted |
| Active | Booked |
| Done | Job done |
| Lost | New lead, opportunity status set to lost |
| On hold | no change |

Auth is a GoHighLevel Private Integration token (scopes `opportunities.readonly`, `opportunities.write`) stored as an n8n custom auth credential.

### Weekly Digest

Mondays at 8am Central. Reads Projects and Tasks and posts to `#leads`: pipeline counts by status, projects created this week, status changes this week, projects with no edits in 14 days, and open tasks due in the next 7 days with overdue ones flagged.

### Error Handler (shared)

An Error Trigger workflow that every other workflow points at. Posts workflow name, failing node, error message, and execution URL to `#automation-alerts`.

## What breaks and what catches it

- **Notion rejects a field.** First live run failed because an empty string was sent for a phone number; Notion wants null. The Error Handler posted the node and message to Slack within a second of the failure. Fixed by coalescing to null.
- **Duplicate submission.** Same email, different capitalization and trailing whitespace: normalized, matched, one Client, second Project attached to it.
- **Status change without a GHL opportunity.** Portfolio projects have no opportunity ID; the filter drops them before the HTTP call and nothing is logged.

## Test log

| Date | Test | Result |
|---|---|---|
| Sep 11 | Site form POST, new email | Client + Project created, Slack post, owner email |
| Sep 11 | Same email, mixed case | Matched existing Client, second Project |
| Sep 11 | Real GHL form submission | Client + Project with GHL IDs |
| Sep 11 | Project status Inquiry to Scoping in Notion | GHL opportunity moved New lead to Contacted in under 60 s |
| Sep 11 | Weekly Digest manual run | Posted to #leads |

## Still to do

- Screenshots of each canvas and of an Error Handler post
- Loom (scheduled week 8 per the plan)
- Intake from Upwork proposals into the Proposals database
