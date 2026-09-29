# 02 - Documents to QuickBooks Online

Vendor bills arrive by email as PDFs or phone photos. Claude reads each one, a Python check decides whether the numbers can be trusted, and only clean bills go on to QuickBooks. Anything odd waits for a person with the reason spelled out. Built on n8n, Claude (Sonnet), Python and the QuickBooks Online sandbox.

Status: intake, extraction and posting to QuickBooks are built and tested (Sep 29, 2026). The review sheet and the document generation leg (form to PDF to DocuSign) are next.

## What this proves

- Scans, phone photos and handwritten bills are read by the same pipeline as clean PDFs.
- Nothing the model says is taken on faith: line math, subtotal, tax and total are rechecked in code, and a total that does not add up is caught even when the model reads it correctly.
- The same file is never processed twice, however many times it is forwarded.
- The same bill is never posted twice either, even when it arrives as a different file (a rescan, a photo of the printout). QuickBooks is checked for the vendor and invoice number before anything is created.
- A bill from a vendor that isn't in QuickBooks goes to review instead of being guessed onto the closest name.
- The Bill in QuickBooks matches the paper to the cent, carries the invoice number, dates and PO, and has the original file attached.
- Every document ends in a known state (`needs_review`, `duplicate`, `failed`, `posted`, `already_in_qbo` or `post_failed`) with the reason stored next to it.

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
6. **Post to QuickBooks** (separate workflow, `n8n/post-bill.json`, called with the row id). It can also be called by webhook, which is how an approved review row or a retry gets posted.
   - Load the row and stop unless it is `ready` (or `approved`) and has no Bill ID yet, so calling it twice is harmless.
   - Pull the active vendors and expense accounts from QuickBooks.
   - `qbo/bill.py` (run as-is in a Python Code node) matches the vendor name after normalizing it ("Norton Lumber & Building Materials, Inc." finds "Norton Lumber and Building Materials"; a bare "Ellis" does not find "Ellis Equipment Rental"), picks the expense account for that vendor, and builds the Bill: one line per invoice line plus a sales tax line, which must add up to the invoice total to the cent. Anything it can't do safely sends the row to `needs_review` with the reason.
   - Query QuickBooks for a Bill with the same vendor and invoice number. If one exists, the row is marked `already_in_qbo` with that Bill's ID and `#automation-alerts` gets a note. The create call is not retried on failure for the same reason: a retry that half-succeeded would double-post.
   - Create the Bill, mark the row `posted` with the Bill ID right away, then pull the original attachment back out of Gmail and attach it to the Bill. If the attachment fails, the Bill stays and Slack says to attach the file by hand.
   - If QuickBooks rejects the Bill, the row is marked `post_failed` with QuickBooks' error and Slack says how to retry.

   Token refresh is handled by n8n's QuickBooks credential. `qbo/client.py` is the code version of this leg for use outside n8n, and it owns the OAuth refresh itself (refresh and retry once on a 401, keep the rotated refresh token).

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

## Posting test run (Sep 29, 2026)

Against the QuickBooks Online sandbox:

| Document | Result |
|---|---|
| 01 Norton Lumber | Bill 145, $1,765.99, 3 lines + tax to Job Expenses:Job Materials |
| 02 Hicks Hardware | Bill 146, $516.27 |
| 03 Ellis Equipment Rental (phone photo) | Bill 147, $1,058.41 to Equipment Rental, photo attached |
| Rescan of 01 (different file, same invoice number, vendor written "Norton Lumber & Building Materials, Inc.") | `already_in_qbo`, points at Bill 145, Slack note, nothing created |
| Bay Area Concrete Pumping (vendor not in QuickBooks) | `needs_review`: vendor "Bay Area Concrete Pumping" is not in QuickBooks |
| Norton posted again by webhook | skipped, the row already has a Bill ID |
| New Hicks invoice HH-8871 emailed to the AP inbox | end to end in about 20 seconds: read, checked, Bill 148 created, PDF attached |

Bills 145 and 146 were posted while the attachment step was still being fixed, so they have no file on them.

## Files

```
extract/
  prompt.txt          the extraction prompt (the n8n node embeds the same text)
  validate.py         parsing and checks; pasted verbatim into the n8n Python node
  extract.py          same pipeline as a CLI: python3 extract.py <file>...
  test_validate.py    parsing, money and date handling, every review reason
  test_extract.py     request building, retries (429/5xx/529 retried, 4xx not)
  test_n8n_sync.py    fails if the n8n export and this folder drift apart
qbo/
  bill.py             vendor match, expense account, Bill payload, duplicate query; pasted verbatim into the n8n Python node
  client.py           same posting leg as a CLI with its own OAuth refresh: python3 client.py row.json invoice.pdf
  test_bill.py        vendor matching, account choice, Bill math, review reasons
  test_client.py      refresh and retry once on 401, no double post, attachment upload
  test_n8n_sync.py    fails if the posting export and bill.py drift apart
n8n/
  document-intake.json
  post-bill.json
test-data/            the five sample bills, expected results, generator script
```

```bash
cd extract
python3 -m unittest -v          # 50 tests, no network
cd ../qbo
python3 -m unittest -v          # 41 tests, no network
ANTHROPIC_API_KEY=... python3 extract.py ../test-data/04-tim-philip-masonry-117-handwritten.jpg
```

## Importing the workflow

Credential IDs are stripped from `n8n/document-intake.json`. After importing:

1. Attach your Gmail, Anthropic and Slack credentials.
2. Create a data table named `p2_documents` with the columns listed below and put its ID in the four data table nodes.
3. Put your Gmail label ID in the trigger and your error workflow ID in the workflow settings.
4. Import `n8n/post-bill.json` too. Attach your QuickBooks Online, Gmail and Slack credentials, put your QuickBooks company ID (realm ID) in the `QuickBooks config` node (both fields), and put the data table ID in its five data table nodes. Then put the posting workflow's ID in the intake's `Post Bill to QuickBooks` node.

Posting uses HTTP Request nodes on the QuickBooks credential rather than the QuickBooks node, because the node can't set the invoice number (DocNumber), takes a fixed number of lines, and can't attach files.

`p2_documents` columns: `sha256`, `filename`, `mime_type`, `size_bytes` (number), `gmail_message_id`, `attachment_index` (number), `sender`, `subject`, `received_at`, `status`, `review_reasons`, `warnings`, `vendor_name`, `invoice_number`, `invoice_date`, `due_date`, `po_number`, `subtotal` (number), `tax` (number), `total` (number), `line_items_json`, `min_confidence` (number), `notes`, `model`, `raw_extraction`, `error`, `qbo_bill_id`. Everything not marked is text.

## Notes from the build

- The n8n Python runner allows `json`, `re`, `datetime` and `decimal`, and blocks dynamic imports and dunder names, so `validate.py` sticks to those.
- `claude-sonnet-5-5` rejects the `temperature` parameter, so the request leaves it out.
- The data table "row exists" operation ignored a second condition (`status != failed`), which is why failed rows store the hash with a `failed:` prefix instead of relying on the status column.
- Two copies of the same file inside one email are both processed, since neither is in the table yet when the check runs. The QuickBooks client's vendor + invoice number check is the backstop for that.
- Re-publishing the workflow can make the Gmail trigger re-deliver recent emails. The hash check turns those into `duplicate` rows instead of double work.
- Attaching a file in n8n with the QuickBooks OAuth2 credential: a raw binary body fails with `source.on is not a function`, and a multipart text field for the metadata goes out as `text/plain`, which QuickBooks rejects ("Unable to find a MessageBodyReader for media type text/plain"). What works is multipart with both parts as binary, the metadata written to a small `application/json` file first.
- QuickBooks can answer the upload with HTTP 200 and a Fault in the body, so the workflow checks for an Attachable ID instead of trusting the status code.
- The webhook trigger on the posting workflow has no auth. It only posts rows that are already `ready` and not yet posted, but add header auth before pointing it at real books.

## What's next

- Review sheet: `needs_review` rows go to a Google Sheet with the reasons and a link to the email; ticking Approve sends the row on to posting.
- Generation leg: form to PDF to DocuSign, with the signed copy archived.
