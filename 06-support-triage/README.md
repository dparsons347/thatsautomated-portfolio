# 06 - Support requests sorted by AI, approved by a person

Everything comes into one inbox: sales questions, support, existing clients, vendors, spam. Someone reads each one and decides what to do with it. Here every new email is classified by Claude, the sender is looked up in HubSpot, a reply is drafted for the two categories that have standard answers, and the whole thing lands in Slack as a card with Approve, Edit, Reassign and Archive. Nothing goes out without a click.

Built with n8n (Gmail, Slack, the queue and everything a client would change) around a small Python service (FastAPI + LangGraph) that does the one narrow AI job, traced in LangSmith so every decision can be inspected.

Status: built, deployed and tested end to end on live accounts (Sep 29, 2026). Loom next.

## What this proves

- The AI does one job inside a workflow a person controls. It classifies and drafts; plain code decides what happens next (`decide()` in `app/graph.py`), and a person clicks before anything is sent.
- Anything the model isn't sure about goes to a person: category `unclear`, confidence below the threshold, a negative reply on an open thread, a thread that changes category, or a draft that would need facts the standard answers don't contain.
- A reply on an existing thread is treated as a reply. The earlier messages and their categories go to the model, and a sales thread that turns into a complaint is routed to a person with the history attached.
- The classification is testable without a model. Ten canned emails run through the real graph with Claude and HubSpot scripted (46 tests), and the same ten run against the real model with `evals/live_eval.py`.
- Every decision is traceable. Each card links to its LangSmith trace: the prompt, the CRM context, the model's answer and the gate.
- When Claude is down, nothing is lost and nothing is guessed. The message is queued, `#automation-alerts` is told once, n8n retries every 10 minutes for an hour, and a "recovered" note posts when it goes through.
- Slack button clicks are verified. The request signature is checked against Slack's signing secret before any action runs, and a second click on a handled card sends nothing.

## How it works

```
Gmail label "Support Triage"
   │  (n8n: P6 Support intake, polls every minute, stores each message once)
   ▼
p6_messages (n8n data table) ──> P6 Triage message ──HTTP──> triage-api (FastAPI + LangGraph)
                                    │                         lookup (HubSpot) -> classify (Claude)
                                    │                         -> gate (code) -> draft (Claude, sales/support only)
                                    │                         traced to LangSmith
                                    ├─ 2xx: Block Kit card in #support-triage
                                    └─ error: status queued, alert #automation-alerts,
                                              P6 Retry queued messages every 10 min for an hour
Slack buttons ──> P6 Slack actions (verify signature) ──> Gmail reply on the same thread / label / card update
```

**The service** (`app/`). `POST /triage` takes the message, the thread history and the prior category, and returns category, confidence, a one-line reason, sentiment, the route (`draft`, `person`, `archive`), the gate reasons, the HubSpot record with deals, the draft, and the LangSmith trace URL. It runs on the VPS next to n8n with no public route: n8n reaches it over the Docker network at `http://triage-api:8000` with an `X-Webhook-Key` header. A Claude outage returns 503 and bad model output returns 502, so n8n queues instead of guessing. A HubSpot outage doesn't stop triage; the card says the lookup failed.

**The graph** (`app/graph.py`). `lookup` (HubSpot contact by email, then its deals) -> `classify` (Claude, structured output) -> `gate` (plain code) -> `draft` (Claude, only when the gate allows it). Prompts are in `app/prompts.py` and the standard answers the drafts may use are in `app/faq.md`.

**n8n** (`n8n/`, credential IDs stripped):

| Workflow | What it does |
|---|---|
| `support-intake.json` | Gmail trigger on the Support Triage label. Strips quoted text, skips mail from ourselves, stores each message once (keyed on Gmail message ID), calls the triage sub-workflow |
| `triage-message.json` | Loads the message and its thread from the data table, calls the service, posts the card. On error: queue, alert once, give up after 7 attempts. Threshold lives in its Settings node |
| `slack-actions.json` | Slack interactivity endpoint. Acks within 3 seconds, verifies the signature, then Approve (sends the draft as a reply on the same Gmail thread with Reply-To the support address), Edit (modal, then send), Reassign (thread mention and Routed label), Archive (label, out of the inbox). Updates the card either way |
| `retry-queued.json` | Every 10 minutes (or on demand) re-runs queued messages |
| `seed-test-emails.json` | Drops the canned emails into Gmail under the label, from plus addresses I control. The angry reply is threaded onto Maya's original by its headers |
| `reset-demo-data.json` | Clears the table, trashes the test threads, deletes the bot's cards |

## The ten canned emails

`test-data/emails.py`. Three senders exist in HubSpot (see `test-data/hubspot-seed.md`).

| Key | What it is | Expected |
|---|---|---|
| sales_new | Landscaper wants lead entry automated, asks price | sales, draft |
| support_login | Known client, Google connection expired | support, draft |
| existing_client | Known client questions an invoice and wants more scope | existing client, person |
| vendor_pitch | Guest post seller | vendor, archive |
| ambiguous | "Circling back on what we talked about" | unclear, person |
| angry_reply | Maya again on the sales thread: nobody showed up for the call | person (negative reply on an open thread) |
| spam | Mailbox-full phishing | spam, archive |
| lead_seller | Lead seller dressed as a buyer | person at 0.75; gets a sales draft if the threshold is set to 0.55 |
| support_not_covered | Asks for an export the standard answers don't cover | person (draft needs facts) |
| support_hours | Asks about Saturday coverage | support, draft |

I also tried five vendor pitches dressed up as support requests, RFPs and demo requests to find one that fooled the model at high confidence. It called all of them vendor (0.72 to 0.93) with a reason that named the pitch, so the borderline case in the demo is the lead seller, where the model itself hedges and the threshold decides.

## Test run (Sep 29, 2026)

| Step | What happened |
|---|---|
| Seeded sales_new and support_login | Both classified within a minute. Sales 0.96, support 0.82 with a draft using the reconnect steps from the standard answers |
| Approve on the support card (signed request) | Reply sent on the same Gmail thread with Reply-To daniel+support@, thread labeled Replied, row marked sent, outbound message logged for thread history, card replaced with "Sent as drafted by Daniel" |
| Same Approve again | Ephemeral "Already handled", nothing sent |
| Forged signature | Service answered `valid: false`, workflow stopped before any action |
| angry_reply | Threaded onto Maya's original by In-Reply-To. Classified with the thread history, gated "Negative reply on an open thread" |
| existing_client, vendor_pitch, ambiguous, spam | Person, archive, person, archive as expected |
| Reassign on the Marcus card | Thread mention in Slack, Gmail label Routed, card updated |
| Archive on the spam card | Labeled Archived, out of the inbox, card updated |
| ANTHROPIC_BASE_URL pointed at a dead host, support_hours seeded | 503 model_unavailable, row queued, one alert in #automation-alerts, no card |
| URL restored, retry run | Classified on the next attempt, card posted, "Support triage is back" in #automation-alerts |

## Run the tests

```
pip install -r requirements-dev.txt
pytest
```

Against the real model (on the server):

```
docker compose exec triage-api python evals/live_eval.py
docker compose exec triage-api python evals/live_eval.py --only lead_seller --threshold 0.55
```

## Deploy

```
cd 06-support-triage/deploy
cp ../.env.example .env      # fill in the secrets
docker compose up -d --build
docker exec root-n8n-1 wget -qO- http://triage-api:8000/health
```

## When it breaks

| What goes wrong | What happens |
|---|---|
| Claude is down or slow | 503 from the service, message queued, one Slack alert, retried every 10 minutes for an hour, then marked failed with a second alert. Nothing is sent |
| The model returns something that doesn't fit the schema | 502, same queue path |
| HubSpot is down or the token expired | Triage continues, the card says the lookup failed and the sender is treated as unknown |
| A reply lands on a thread that was classified sales | Classified again with the thread history. Negative tone or a category change sends it to a person |
| The model is confident and wrong | The card shows its reason and the trace. Raise the threshold in the Settings node of P6 Triage message |
| Someone posts a fake Slack button click | Signature check fails, nothing runs |
| Two people click Approve | The second gets "Already handled", one email goes out |
| The same email is polled twice | Stored once, keyed on the Gmail message ID |

## Why this stack

The AI does one narrow job inside a workflow a person controls. It is not an agent running the inbox; in the postings I reviewed, almost nobody was buying autonomous agents. They were buying "sort this and draft the easy ones." LangGraph makes that one job testable and traceable. n8n owns everything around it because that is what the client's team will change.
