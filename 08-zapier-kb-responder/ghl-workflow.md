# GoHighLevel workflow: "Customer Replied to Zapier"

Built by hand in the HVAC sub-account (`dF6GpnV3NGdeZSjrnIRl`). This is the only GHL-side piece Project 8 needs. It does one thing: every inbound customer message leaves GHL and lands on Zap A's catch hook.

The GHL workflow builder runs in an iframe that browser automation can't click, so this is a manual build. Everything below is exact.

## Settings

| Setting | Value | Why |
|---|---|---|
| Name | Customer Replied to Zapier | |
| Folder | leave default | |
| Allow re-entry | **Yes** | A customer asks more than one question. Without this, only their first message ever reaches the responder. |
| Stop on response | No | |
| Timezone | America/Chicago | |
| Status | Draft until Zap A's catch hook URL exists, then Publish | |

## Trigger

**Customer Replied**

| Filter | Value | Notes |
|---|---|---|
| Channel | Email | Pre-A2P. Switch to SMS once the A2P campaign clears. |

Leave every other filter empty. Filtering by tag or pipeline here would silently drop the messages you most want the responder to see.

## Action: Webhook

| Field | Value |
|---|---|
| Action name | POST to Zap A |
| Method | POST |
| URL | the catch hook URL from Zap A step 1 |
| Headers | none |

**Custom data** (these five keys are what Zap A reads, spelled exactly):

| Key | Value |
|---|---|
| `contact_id` | `{{contact.id}}` |
| `phone` | `{{contact.phone}}` |
| `first_name` | `{{contact.first_name}}` |
| `message_body` | `{{message.body}}` |
| `timestamp` | `{{right_now.utc}}` |

Verify each merge tag in the builder's own picker rather than pasting blind. `{{message.body}}` in particular is only offered inside a Customer Replied workflow, and GHL has shipped more than one spelling of the right-now tags.

Nothing else goes in this workflow. No tags, no notifications, no wait steps. Everything the responder does happens on the Zapier side, which is the point of the piece: the CRM hands the message off and gets out of the way.

## Interaction with the Project 4 workflows

Three workflows now trigger on Customer Replied in this sub-account:

| Workflow | What it does | Conflict? |
|---|---|---|
| Tag Stop Requests | Tags `stop-requested` on STOP keywords | No. Tag only. |
| Flag Unhappy Replies | Tags `replied-unhappy` on negative keywords | No. Tag only. |
| Customer Replied to Zapier | POSTs to Zap A | No. Outbound only. |

All three fire on the same inbound message and none writes what another reads. Worth saying out loud in the Loom: the CRM keeps doing its own job while the responder runs beside it.

One real overlap to watch. A customer who texts "STOP" gets tagged by the first workflow **and** is classified by the responder. Two options, decide before recording:

- Add a filter on the webhook action: only continue if the message does not contain STOP, UNSUBSCRIBE, END, QUIT, CANCEL. Cleanest, and it keeps opt-outs out of the AI path entirely.
- Or leave it. The model has an opt-out rule in `kb_rules` and will answer from it.

The first is the better demo, because "an opt-out never reaches the model" is the same argument as the emergency bypass.

## Test before building Zap A

Point the webhook at a temporary catch hook (Zapier gives you the URL the moment you add the trigger step), publish the workflow, and send yourself an email reply from a test contact. Check the catch hook received all five keys with real values. `{{contact.phone}}` is the one that most often comes back empty, on a contact created from an email-only form. If it does, fix the test contact rather than the workflow: the responder is keyed on phone.
