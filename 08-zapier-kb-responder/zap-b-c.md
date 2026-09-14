# Zap B and Zap C

Zap B closes the loop: a person's answer reaches the customer and, if it generalizes, becomes a rule. Zap C is the safety net under Zap A.

Both reuse the GHL reply step from `zap-a.md`. Build it once, copy it.

## Zap B: Human answer to customer and knowledge base

### 1. Trigger: Zapier Tables, Updated Record in `conversations`

Watch the `human_answer` column. Table ID `01M2GQ7V6S75JZH212QC5Y46QP`.

**Know the timing before you record.** Tables triggers poll. On the Professional trial that is a couple of minutes, not instant, so there is a visible gap between typing the answer on the queue page and the customer's phone lighting up. Two ways to handle it:

- **Cut the Loom around it.** Honest, and nobody watching expects a live wire.
- **Use a button field instead.** Zapier Tables has a button field type that fires a Zap on click, which is effectively instant. Add a "Send" button column to `conversations`, put it on the Interfaces page next to the answer box, and trigger Zap B on the button instead of on the update. Verify the button trigger exists in your account before rebuilding around it.

The button is the better demo and the better product. A person typing an answer expects it to send when they say send, not on a two-minute timer.

### 2. Filter by Zapier

Continue only if:

- `human_answer` is not empty
- `status` exactly matches `PENDING_HUMAN`

The status condition is what stops this Zap from re-firing every time someone edits a row that has already been answered.

### 3. Reply to the customer

The GHL webhook step, with `human_answer` as the message and `ghl_contact_id` from the row.

### 4. Zapier Tables, Update Record

status = `ANSWERED_BY_HUMAN`.

From the customer's point of view the job is now done. Everything below this line is the system teaching itself, and it is the half that makes this piece worth showing.

### 5. Filter by Zapier

Continue only if `reusable` is true. Most answers stop here, which is correct. One customer's appointment time is not a rule.

### 6. Anthropic (Claude), Create Message

Prompt 3 from `prompts/03-sanitize-*.txt`. Returns JSON.

### 7. Code by Zapier, Run JavaScript

```js
// inputs: raw  (the model's output from step 6)
let out = { keep: false, category: 'other', question_pattern: '', rule_text: '', reason: 'parse failed' };
try {
  const text = inputData.raw.trim().replace(/^```(?:json)?/, '').replace(/```$/, '');
  const p = JSON.parse(text);
  out = {
    keep: p.keep === true,
    category: p.category || 'other',
    question_pattern: p.question_pattern || '',
    rule_text: p.rule_text || '',
    reason: p.reason || ''
  };
  if (out.keep && (!out.rule_text || !out.question_pattern)) { out.keep = false; out.reason = 'incomplete rule'; }
} catch (e) {
  out.reason = 'parse failed: ' + e.message;
}
output = [out];
```

Same principle as Zap A's parser, pointed the other way. Every failure resolves to `keep: false`. A parse error means no rule is written, not a garbage rule written.

### 8. Filter by Zapier

Continue only if `keep` is true.

### 9. Zapier Tables, Create Record in `kb_rules`

Table ID `01M2GQ74007J03PQ6BJ8JSATY4`.

| Column | Value |
|---|---|
| category | from step 7 |
| question_pattern | from step 7 |
| answer | `rule_text` from step 7 |
| active | TRUE |
| source | human |
| reviewed | FALSE |
| created_at | today |
| times_used | 0 |

`source = human` and `reviewed = FALSE` are what make the knowledge-base page in Interfaces useful: sort by reviewed ascending and every machine-written rule floats to the top for the owner to confirm or switch off.

### 10. Slack, Send Channel Message

To `#automation-alerts`: "New rule added from a human answer, unreviewed: [rule_text]. Review at [Interfaces KB page]."

### The design choice to state on camera

The new rule goes live immediately but unreviewed, and one click deactivates it. The alternative, inactive until a human reviews it, is safer for a business answering legal or medical questions and is a single checkbox change. Say which you chose and why, because a client watching will have an opinion, and having the answer ready is the difference between a demo and a sales conversation.

## Zap C: Responder failed, default to human

The point of this Zap: when the responder dies mid-run, the customer still hears from someone. Without it, a dead Anthropic step means a customer sitting in silence while Autoreplay quietly retries in the background.

### 1. Trigger: Zapier Manager, Zap Error

Zapier Manager is a built-in app. Filter to Zap A only, or this Zap will fire on its own errors and on every other Zap in the account.

**The honest limitation:** this trigger polls, so the holding message is not instantaneous. Name that in the Loom rather than hoping nobody notices, and use it to make the comparison the portfolio is built around: this is where a dedicated workflow tool earns its price. In n8n (Project 6) an error workflow fires synchronously, in the same execution, the moment a node throws. Zapier's error handling is a separate polled Zap. Same problem, different tool, real trade-off. That contrast is the most valuable thirty seconds in this whole build, because it shows you choosing tools on their merits rather than selling the one you happen to know.

### 2. Zapier Tables, Find Records in `conversations`

The error payload may not carry the original message, so find the row that died: status equals `PENDING_HUMAN` and `model_raw` is empty, sorted by `received_at` descending, first result.

This is a heuristic, not an identity match. Under real volume two messages could be in flight at once and this could pick the wrong one. For a demo at one message at a time it is exact, and the honest version of this step in production is to pass the Zapier run ID into the row when it is created and look it up by that. Worth one sentence in the README as a known limitation, because the kind of client who asks about it is the kind worth having.

### 3. Reply to the customer

The GHL webhook step, same holding message as Zap A's B6b: "Thanks, I've passed this to the team and someone will reply shortly."

### 4. Zapier Tables, Update Record

status = `FAILED`, model_raw = the error text from the trigger.

`FAILED` rather than `PENDING_HUMAN` so the two are distinguishable on the queue page. A question nobody answered and a question the machine broke on need different handling by the owner.

### 5. Slack, Send Channel Message

To `#automation-alerts`: "Responder Zap errored, customer told a person will reply, row [conv_id]." Include the link to the Zap run so it is one click to the stack trace.

## Testing these two

Zap B is test case 6 followed by 12: let the solar question escalate, answer it on the queue page with the deliberately PII-laden text from `test-cases.md`, watch the sanitized rule land in `kb_rules`, then ask the same question from the second phone and get it answered instantly.

Zap C is the killed API key: break the Anthropic connection, send test case 1, and watch the error fire Zap C while Autoreplay retries the original run. Restore the key and show the retry succeed. Two things catch the same failure, one protecting the customer's experience and one protecting the data.
