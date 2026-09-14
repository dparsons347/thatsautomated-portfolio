# Zap A: Inbound question responder

The main Zap. Takes an inbound customer message from GoHighLevel, bypasses the model entirely on emergencies, and otherwise answers from the knowledge base or hands off to a person.

Zapier has no workflow export, so this file is the build record. Screenshots of each step go in `zaps/`.

## Before you start

Two corrections to the original spec, both verified against the live Zapier app catalog on Sep 14:

1. **The LeadConnector app cannot send messages.** Its only actions are Add/Update Contact, Add/Update Opportunity, Campaign, Campaign Stop All, and Task. Every reply to the customer therefore goes out as a raw Webhooks by Zapier POST to the GHL API, using the Private Integration token from Project 7. Details in "The reply step" below.
2. **Zapier Tables text fields cap at 255 characters.** Before building this Zap, convert `message`, `answer`, `model_raw` and `human_answer` on `conversations`, and `answer` on `kb_rules`, to a long-text field type in the Tables UI. `model_raw` holds the model's full JSON and will blow past 255 on the first run.

Also have ready: the Anthropic (Claude) app connected in Zapier with the portfolio API key, and the three table IDs.

| Table | ID |
|---|---|
| kb_rules | `01M2GQ74007J03PQ6BJ8JSATY4` |
| customers | `01M2GQ7JHEX1FJK5JZE377N28D` |
| conversations | `01M2GQ7V6S75JZH212QC5Y46QP` |

## The reply step

Used three times in this Zap (emergency acknowledgement, answer, holding message) and twice in Zap B and C. Build it once and copy it.

**Webhooks by Zapier, Custom Request**

| Field | Value |
|---|---|
| Method | POST |
| URL | `https://services.leadconnectorhq.com/conversations/messages` |
| Headers | `Authorization: Bearer <GHL Private Integration token>`, `Version: 2021-04-15`, `Content-Type: application/json` |
| Data | `{"type": "Email", "contactId": "<contact_id from the trigger>", "message": "<the reply text>"}` |

Switch `type` to `SMS` when A2P clears. The SMS shape is the simple one above. The Email shape usually wants a subject and an HTML body as well, so send one by hand from the Zap editor and read the response before wiring it into four places. The token needs the Conversations scope.

## Steps

### 1. Trigger: Webhooks by Zapier, Catch Hook

Copy the URL it gives you into the GHL workflow (see `ghl-workflow.md`). Send one real test message before continuing, so every later step has real sample data to map against. Do not skip this: Zapier's field mapper is only as good as the sample.

Expected payload keys: `contact_id`, `phone`, `first_name`, `message_body`, `timestamp`.

### 2. Formatter by Zapier, Text, Lowercase

Input: `message_body`. Output referred to below as `msg_lc`. The keyword check has to be case-insensitive, and Paths compares literally.

### 3. Zapier Tables, Create Record in `conversations`

| Column | Value |
|---|---|
| received_at | `timestamp` |
| phone | `phone` |
| first_name | `first_name` |
| ghl_contact_id | `contact_id` |
| message | `message_body` |
| status | `PENDING_HUMAN` |

This is the guardrail, and it is the thing to say out loud in the Loom. The row is created as PENDING_HUMAN **before** any work happens, so if every step after this dies, what remains is a row saying a person owes this customer a reply. The system fails toward a human, not toward silence.

Capture the returned record ID. Every later step updates this row.

### 4. Paths

Two paths at this level.

#### Path A: Emergency

**Rule:** `msg_lc` contains any of `no heat`, `no cool`, `no ac`, `not cooling`, `not heating`, `gas`, `smell`, `smoke`, `burning`, `sparks`, `carbon monoxide`, `alarm`, `flood`, `leaking`, `water everywhere`, `emergency`.

Zapier Paths rules are OR'd within a path, so add one "contains" condition per keyword. Hardcode the list in v1 and say so in the README. Moving it to a table is a nice-to-have, not a demo requirement.

- **A1. Reply** (the step above): "Got it. This looks urgent, so I've flagged it for the owner and someone will call you within 15 minutes. If you smell gas, leave the building and call the gas company first."
- **A2. LeadConnector, Add/Update Contact:** add tag `emergency`. This is the one thing the LeadConnector app is genuinely good for.
- **A3. Slack, Send Channel Message** to `#automation-alerts`: first_name, phone, the message, and the line "EMERGENCY, no AI involved."
- **A4. Zapier Tables, Update Record:** status = `ESCALATED_EMERGENCY`.

No AI step appears anywhere on this path. That is the entire argument for putting the keyword check before the model, and on camera the greyed-out AI steps in the Zap run history make it for you.

#### Path B: Everything else

**Rule:** `msg_lc` does not contain each of the same keywords. Zapier has no true "otherwise" branch, so this is one "does not contain" condition per keyword, all AND'd. Tedious, and there is no way around it.

- **B1. Anthropic (Claude), Create Message** — prompt 1 from `prompts/01-classify-*.txt`. Returns one word.
- **B2. Zapier Tables, Find Records** in `kb_rules`: category equals B1's output, active equals TRUE. If the account only offers a single-record find, add a second lookup on category `other` so there is always a general rule in context.
- **B3. Zapier Tables, Find Record** in `customers`: phone equals the trigger `phone`. **Turn off "create record if it doesn't exist."** When nothing is found, the customer block in the next prompt is the literal string `NO RECORD ON FILE`. This is test case 5 and it has to fail closed.
- **B4. Anthropic (Claude), Create Message** — prompt 2 from `prompts/02-answer-*.txt`. Returns JSON.
- **B5. Code by Zapier, Run JavaScript** — parse it:

```js
// inputs: raw  (the model's output from B4)
let out = { decision: 'ESCALATE', answer: null, rule_ids: '', confidence: 'low', reason: 'parse failed' };
try {
  const text = inputData.raw.trim().replace(/^```(?:json)?/, '').replace(/```$/, '');
  const p = JSON.parse(text);
  out = {
    decision: p.decision === 'ANSWER' ? 'ANSWER' : 'ESCALATE',
    answer: p.answer || null,
    rule_ids: Array.isArray(p.rule_ids) ? p.rule_ids.join(',') : '',
    confidence: p.confidence || 'low',
    reason: p.reason || ''
  };
  if (out.decision === 'ANSWER' && !out.answer) { out.decision = 'ESCALATE'; out.reason = 'answer empty'; }
} catch (e) {
  out.reason = 'parse failed: ' + e.message;
}
output = [out];
```

Every failure mode in that function lands on ESCALATE. A malformed response, a fenced code block, an empty answer with an ANSWER decision: all of them hand the message to a person instead of texting the customer something broken. Worth pausing on in the Loom.

- **B6. Paths** (nested, second level):

**B6a. Answered.** Rule: `decision` exactly matches `ANSWER`.
  - Reply to the customer with `answer`.
  - Tables, Update Record on `conversations`: status = `ANSWERED`, category, answer, rule_ids, model_raw = the raw B4 output.
  - Tables, Update Record on `kb_rules`: increment `times_used` for the first rule id. Zapier updates one record per step, so if the model cited three rules only the first is counted. Say so rather than pretending the counter is exact.

**B6b. Escalate.** Rule: `decision` exactly matches `ESCALATE`.
  - Reply: "Thanks, I've passed this to the team and someone will reply shortly."
  - Tables, Update Record: status stays `PENDING_HUMAN`, write category and model_raw.
  - Slack to `#automation-alerts`: first_name, the message, the model's `reason`, and the link to the Interfaces queue page.

Put B6b's rule on `ESCALATE` rather than leaving it as a catch-all, then add a third nested path or a fallback that also escalates on anything else. The parser above already forces one of the two values, so this is belt and braces.

## Settings

Turn **Autoreplay** on for this Zap. Zapier retries a failed run automatically, and Zap C covers the customer while that retry is pending. In the Loom, name both: Autoreplay is the retry, Zap C is what the customer sees in the meantime.

## Task budget

A normal Path B run bills about 6 tasks. Paths, Filters, Formatter and Tables steps are free; Anthropic, the webhook POST and Slack are billed. Twelve test cases, a dozen re-runs and the recording fit inside the 1,000-task Professional trial, which is showing 22 used so far.
