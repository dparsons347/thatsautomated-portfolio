# 02 - Documents to QuickBooks Online

Vendor bills arrive by email as PDFs or phone photos. Claude reads each one, a Python check decides whether the numbers can be trusted, and only clean bills go on to QuickBooks. Anything odd waits for a person with the reason spelled out. Built on n8n, Claude (Sonnet), Python and the QuickBooks Online sandbox.

Status: the intake and extraction leg is built and tested (Sep 28, 2026). Posting Bills to QuickBooks, the review sheet and the document generation leg (form to PDF to DocuSign) are next.

## What this proves

- Scans, phone photos and handwritten bills are read by the same pipeline as clean PDFs.
- Nothing the model says is taken on faith: line math, subtotal, tax and total are rechecked in code, and a total that does not add up is caught even when the model reads it correctly.
- The same file is never processed twice, however many times it is forwarded.
- Every document ends in a known state (`ready`, `needs_review`, `duplicate` or `failed`) with the reason stored next to it.

## How it works

Anything sent to `daniel+ap@thatsautomated.com` gets the Gmail label **AP Intake**. n8n polls that label every minute.

1. **Split attachments.** One item per PDF, JPG, PNG, GIF or WEBP. Images under 20 KB are skipped as email signature logos. An email with no usable attachment posts a note to `#automation-alerts` so someone can ask the vendor to resend.
2. **SHA-256 of each file**, checked against the `p2_documents` data table. A match is logged as `duplicate` and stops there.
3. **Claude reads the bill.** PDFs go to the Messages API as a document block and images as an image block, with the prompt in `extract/prompt.txt`. Claude is told to transcribe exactly what is on the page, never fix arithmetic, and give a confidence score for vendor, invoice number, date, line items and total. Three tries with a 5 second wait.
4. **Python validation** (`extract/validate.py`, run as-is in an n8n Python Code node). The document goes to `needs_review` if any of these fail:
   - vendor, invoice number, date and total are all present, and the date parses and is not in the future
   - quantity x price = amount on every line
   - the lines add up to the subtotal
   - subtotal + tax = total (5 cent tolerance)
   - confidence is 0.85 or higher on every key field
   - it is an invoice (not a statement or credit memo) and it is in USD

   Handwriting, an old date or a due date before the invoice date are recorded as warnings and do not block posting.
5. **Save** to `p2_documents` with the status, reasons, warnings, the extracted fields, the line items and Claude's raw output, then branch: `ready` goes on to posting and `needs_review` goes to review.

If Claude fails three times, the file is logged as `failed` (its hash is stored as `failed:<sha256>` so it does not count as seen), `#automation-alerts` gets the error, and sending the file again will retry it. Any other node failure goes to the shared Error Handler workflow.

## Test run (Sep 28, 2026)

The five documents in `test-data/`, sent to the AP inbox one email each:

| File | Result | Why |
|---|---|---|
| 01 Norton Lumber, clean PDF | `ready`, $1,765.99 | All checks pass, lowest confidence 0.98 |
| 02 Hicks Hardware, clean PDF | `ready`, $516.27 | All checks pass, lowest confidence 0.98 |
| 03 Ellis Equipment Rental, skewed phone photo | `ready`, $1,058.41 | Read correctly despite angle, shadow and uneven light, lowest confidence 0.95 |
| 04 Tim Philip Masonry, handwritten | `needs_review` | "lines $1,252.50 + tax $0.00 = $1,252.50 but the total says $1,292.50 ($40.00 off)". Claude read the written total correctly and flagged the gap in its notes too; the code check is what stops it |
| 05 copy of 01, resent | `duplicate` | Same SHA-256 as 01, never sent to Claude |

Plus an email with no attachment (Slack note in `#automation-alerts`) and a real API failure during the build (a request parameter the model rejected), which went down the failure path: three tries, a `failed` row with the error, and a Slack alert.

## Files

```
extract/
  prompt.txt          the extraction prompt (the n8n node embeds the same text)
  validate.py         parsing and checks; pasted verbatim into the n8n Python node
  extract.py          same pipeline as a CLI: python3 extract.py <file>...
  test_validate.py    parsing, money and date handling, every review reason
  test_extract.py     request building, retries (429/5xx/529 retried, 4xx not)
  test_n8n_sync.py    fails if the n8n export and this folder drift apart
n8n/
  document-intake.json
test-data/            the five sample bills, expected results, generator script
```

```bash
cd extract
python3 -m unittest -v          # 50 tests, no network
ANTHROPIC_API_KEY=... python3 extract.py ../test-data/04-tim-philip-masonry-117-handwritten.jpg
```

## Importing the workflow

Credential IDs are stripped from `n8n/document-intake.json`. After importing:

1. Attach your Gmail, Anthropic and Slack credentials.
2. Create a data table named `p2_documents` with the columns listed below and put its ID in the four data table nodes.
3. Put your Gmail label ID in the trigger and your error workflow ID in the workflow settings.

`p2_documents` columns: `sha256`, `filename`, `mime_type`, `size_bytes` (number), `gmail_message_id`, `attachment_index` (number), `sender`, `subject`, `received_at`, `status`, `review_reasons`, `warnings`, `vendor_name`, `invoice_number`, `invoice_date`, `due_date`, `po_number`, `subtotal` (number), `tax` (number), `total` (number), `line_items_json`, `min_confidence` (number), `notes`, `model`, `raw_extraction`, `error`, `qbo_bill_id`. Everything not marked is text.

## Notes from the build

- The n8n Python runner allows `json`, `re`, `datetime` and `decimal`, and blocks dynamic imports and dunder names, so `validate.py` sticks to those.
- `claude-sonnet-5-5` rejects the `temperature` parameter, so the request leaves it out.
- The data table "row exists" operation ignored a second condition (`status != failed`), which is why failed rows store the hash with a `failed:` prefix instead of relying on the status column.
- Two copies of the same file inside one email are both processed, since neither is in the table yet when the check runs. The QuickBooks client's vendor + invoice number check is the backstop for that.
- Re-publishing the workflow can make the Gmail trigger re-deliver recent emails. The hash check turns those into `duplicate` rows instead of double work.

## What's next

- `qbo/` client: create the Bill in the sandbox, attach the original file, skip if the vendor and invoice number already exist, refresh the token and retry once on a 401.
- Review sheet: `needs_review` rows go to a Google Sheet with the reasons and a link to the email; ticking Approve sends the row on to posting.
- Generation leg: form to PDF to DocuSign, with the signed copy archived.
