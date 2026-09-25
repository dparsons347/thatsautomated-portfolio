# Zap B and Zap C

Zap B closes the loop: a person's answer reaches the customer and, if it generalizes, becomes a rule. Zap C is the safety net under Zap A.

Both reuse the GHL reply step from `zap-a.md`. Build it once, copy it.

## Zap B: Human answer to customer and knowledge base

### 1. Trigger: Zapier Tables, Button Clicked in `conversations`

Table ID `01M2GQ7V6S75JZH212QC5Y46QP`, button column `send`.

Built on the button, not on Updated Record. Tables update triggers poll, so a person typing an answer would wait a couple of minutes for it to go out. The button fires on click, which is what someone expects when they press send. Button columns show in row data but are not writable through Create Record.

### 2. Filter by Zapier

Continue only if:

- `answer` is not empty
- `status` exactly matches `PENDING_HUMAN`

The status condition is what stops this Zap from re-firing every time someone edits a row that has already been answered.

### 3. Reply to the customer

The GHL webhook step, with the row's `answer` as the message and `ghl_contact_id` from the row.

### 4. Zapier Tables, Update Record

status = `ANSWERED_BY_HUMAN`.

From the customer's point of view the job is now done. Everything below this line is the system teaching itself, and it is the half that makes this piece worth showing.

### 5. Filter by Zapier

Continue only if `reusable` is true. Most answers stop here, which is correct. One customer's appointment time is not a rule.

### 6. Anthropic (Claude), Create Message

Prompt 3 from `prompts/03-sanitize-*.txt`. `<question>` is the row's `message`, `<answer>` is the row's `answer` (the text the person typed on the queue page). Returns JSON.

### 7. Code by Zapier, Run JavaScript

Input Data: `claude_response` = the response text from step 6. Map it explicitly; with no input mapped the code parses an empty string and returns blanks without erroring.

```js
const raw = (inputData.claude_response || '').replace(/```json|```/g, '').trim();
let out;
try { out = JSON.parse(raw); }
catch (e) { return { keep: 'false', question_pattern: '', answer: '', category: '', parse_error: raw.slice(0, 200) }; }
return {
  keep: String(out.keep === true),
  question_pattern: out.question_pattern || '',
  answer: out.rule_text || '',
  category: out.category || 'other'
};
```

Every failure resolves to `keep: false`. A parse error means no rule is written, not a garbage rule written.

### 8. Filter by Zapier

Continue only if `keep` (text) exactly matches `true`.

### 9. Zapier Tables, Create Record in `kb_rules`

Table ID `01M2GQ74007J03PQ6BJ8JSATY4`.

| Column | Value |
|---|---|
| category | the conversation row's `category` from the step 1 trigger |
| question_pattern | from step 7 |
| answer | `answer` from step 7 (the model's `rule_text`) |
| active | TRUE |
| source | human |
| reviewed | FALSE |
| created_at | today |
| times_used | 0 |

**Category comes from the row, not from step 7.** Zap A finds rules by the category its classifier assigns, so a learned rule has to be filed under the category the classifier gave that question. Taking it from the model's generalize output left the first learned rule with a blank category, and Zap A never found it.

`source = human` and `reviewed = FALSE` are what make the `kb_rules` table useful to the owner: sort by reviewed ascending and every machine-written rule floats to the top for the owner to confirm or switch off.

### 10. Slack, Send Channel Message (optional, not in the built version)

To `#automation-alerts`: "New rule added from a human answer, unreviewed: [rule_text]."

### The design choice to state on camera

The new rule goes live immediately but unreviewed, and one click deactivates it. The alternative, inactive until a human reviews it, is safer for a business answering legal or medical questions and is a single checkbox change. Say which you chose and why, because a client watching will have an opinion, and having the answer ready is the difference between a demo and a sales conversation.

## Zap C: Responder failed, default to human

The point of this Zap: when the responder dies mid-run, the customer still hears from someone. Without it, a dead Anthropic step means a customer sitting in silence while Autoreplay quietly retries in the background.

### 1. Trigger: Zapier Manager, Zap Error

Zapier Manager is a built-in app. Filter to Zap A only, or this Zap will fire on its own errors and on every other Zap in the account.

**Timing, measured:** this trigger turned out to be instant, not polled. Zap A errored at 10:50:18 and Zap C finished at 10:50:31. The real contrast with n8n is structural: in n8n the error workflow is part of the platform's execution model, while in Zapier it is a separate Zap watching the account.

The editor test for this trigger only returns a static placeholder error, so real sample data has to come from a live run: publish Zap C, then force an error in Zap A.

### 2. Zapier Tables, Find Records in `conversations`

The error payload may not carry the original message, so find the row that died: status equals `PENDING_HUMAN` and `model_raw` is empty, sorted by `received_at` descending, first result.

This is a heuristic, not an identity match. Under real volume two messages could be in flight at once and this could pick the wrong one. For a demo at one message at a time it is exact, and the honest version of this step in production is to pass the Zapier run ID into the row when it is created and look it up by that. Worth one sentence in the README as a known limitation, because the kind of client who asks about it is the kind worth having.

### 3. Reply to the customer

The GHL webhook step, same holding message as Zap A's B6b: "Thanks, I've passed this to the team and someone will reply shortly."

### 4. Zapier Tables, Update Record

status = `FAILED`, model_raw = `ZAP ERROR: ` + the trigger's node title + message (inside the 255 character cap). Find Records returns row data under `old.data`; map from the fresh pills, not stale ones left from an earlier sample.

`FAILED` rather than `PENDING_HUMAN` so the two are distinguishable on the queue page. A question nobody answered and a question the machine broke on need different handling by the owner.

### 5. Slack, Send Channel Message

To `#automation-alerts`: "Responder Zap errored, customer told a person will reply, row [conv_id]." Include the failed step, the error text, the row ID, and the Escalation queue link.

## Testing these two

Zap B is test case 6 followed by 12: let the solar question escalate, answer it on the queue page with the deliberately PII-laden text from `test-cases.md`, watch the sanitized rule land in `kb_rules`, then ask the same question from the second phone and get it answered from the new rule.

Zap C is the killed API key: set the model name in Zap A's Claude step to `x` (Anthropic returns 404), send test case 1, and watch the error fire Zap C while Autoreplay retries the original run. Restore the key and show the retry succeed. Two things catch the same failure, one protecting the customer's experience and one protecting the data.
