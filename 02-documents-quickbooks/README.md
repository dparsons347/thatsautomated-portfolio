# 02 - Documents to QuickBooks Online

Two legs. **Bills in:** vendor bills arrive by email as PDFs or phone photos. Claude reads each one, a Python check decides whether the numbers can be trusted, and only clean bills go on to QuickBooks. Anything odd lands on a review sheet with the reason spelled out, and ticking Approve sends it on. **Agreements out:** a form produces a purchase agreement, DocuSign collects the signature, and the signed PDF, the CRM deal and Slack all update on their own. Built on n8n, Claude (Sonnet), Python, the QuickBooks Online sandbox, Google Sheets and Drive, DocuSign (developer sandbox) and HubSpot.

Status: both legs built and tested (Sep 29, 2026). Loom next.

## What this proves

- Scans, phone photos and handwritten bills are read by the same pipeline as clean PDFs.
- Nothing the model says is taken on faith: line math, subtotal, tax and total are rechecked in code, and a total that does not add up is caught even when the model reads it correctly.
- The same file is never processed twice, however many times it is forwarded.
- The same bill is never posted twice either, even when it arrives as a different file (a rescan, a photo of the printout). QuickBooks is checked for the vendor and invoice number before anything is created.
- A bill from a vendor that isn't in QuickBooks goes to review instead of being guessed onto the closest name.
- The Bill in QuickBooks matches the paper to the cent, carries the invoice number, dates and PO, and has the original file attached.
- Every document ends in a known state (`needs_review`, `duplicate`, `failed`, `posted`, `already_in_qbo` or `post_failed`) with the reason stored next to it.
- A person fixes a bad read in a spreadsheet, not in QuickBooks: correct the yellow cells, tick Approve, and the Bill posts with the corrected numbers. If the fix still doesn't add up, the sheet says why.
- A signed contract closes the loop without anyone touching it: signed PDF filed in Drive, HubSpot deal moved to Won, the team told in Slack. A declined one moves the deal to Lost.

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
6. **Post to QuickBooks** (separate workflow, `n8n/post-bill.json`, called with the row id). It can also be called by webhook, which is how an approved review row or a retry gets posted. The webhook (and the review sheet's `p2-queue-review`) needs an `X-Webhook-Key` header; without it n8n answers 403. The DocuSign webhook takes no key because it only reads the envelope ID and fetches everything else back from DocuSign.
   - Load the row and stop unless it is `ready` (or `approved`) and has no Bill ID yet, so calling it twice is harmless.
   - Pull the active vendors and expense accounts from QuickBooks.
   - `qbo/bill.py` (run as-is in a Python Code node) matches the vendor name after normalizing it ("Norton Lumber & Building Materials, Inc." finds "Norton Lumber and Building Materials"; a bare "Ellis" does not find "Ellis Equipment Rental"), picks the expense account for that vendor, and builds the Bill: one line per invoice line plus a sales tax line, which must add up to the invoice total to the cent. Anything it can't do safely sends the row to `needs_review` with the reason.
   - Query QuickBooks for a Bill with the same vendor and invoice number. If one exists, the row is marked `already_in_qbo` with that Bill's ID and `#automation-alerts` gets a note. The create call is not retried on failure for the same reason: a retry that half-succeeded would double-post.
   - Create the Bill, mark the row `posted` with the Bill ID right away, then pull the original attachment back out of Gmail and attach it to the Bill. If the attachment fails, the Bill stays and Slack says to attach the file by hand.
   - If QuickBooks rejects the Bill, the row is marked `post_failed` with QuickBooks' error and Slack says how to retry.

7. **Review sheet** (`n8n/send-to-review.json` and `n8n/review-approvals.json`). Every `needs_review` row, from intake or from posting, is written to a Google Sheet (upsert on the row ID) with the reasons, Claude's notes and a link to the email, and `#automation-alerts` gets a note with the sheet link. The reviewer edits the yellow cells (vendor, invoice number, dates, total, tax) and ticks **approve**. Once a minute a second workflow picks up one approved row, checks what was typed (a total that isn't a number or a date that can't be read goes back to the sheet as "Not approved yet: ..."), saves the corrections, marks the row `approved` and hands it to the posting workflow. The result is written back next to the checkbox: "Posted as QuickBooks Bill 149", "Still needs review: ...", and so on, and the checkbox is cleared.

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

## Agreements out (generation leg)

1. **Form** (n8n form, `n8n/agreement-out.json`): customer, signer, job site, scope, price, deposit percent, dates.
2. **Build the agreement** (`generate/build-agreement.js`, run as-is in a Code node). Checks the input (email format, price above zero, deposit 0 to 100 percent, completion not before start) and writes the agreement as HTML. DocuSign converts HTML to PDF when the envelope is created, so there is no PDF service to host. Sign-here and date tabs are placed on anchor text (`\s1\`, `\d1\`) printed in white.
3. **HubSpot deal** created in the Contacted stage.
4. **DocuSign envelope** sent, with the agreement number and HubSpot deal ID as hidden envelope fields and a per-envelope Connect webhook for completed, declined and voided.
5. Logged to the `p2_agreements` data table and posted to `#leads`.

When DocuSign calls back (`n8n/agreement-events.json`):

- Only the envelope ID is taken from the webhook. Status, custom fields and signer are read back from DocuSign with our own credential, so a forged POST can't mark a deal won.
- An envelope already handled is ignored, so DocuSign's retries are harmless.
- **Completed:** download the combined signed PDF, upload it to the Drive folder, move the HubSpot deal to Won with the close date and a link to the signed copy, log it, post to `#leads`.
- **Declined:** deal to Lost with the signer's reason. **Voided:** logged and posted.

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

## Review and agreement test run (Sep 29, 2026)

| Case | Result |
|---|---|
| Tim Philip handwritten invoice ($40 total gap) on the review sheet, total corrected to $1,252.50, approve ticked | Posted within a minute as Bill 149 to Decks and Patios, the handwritten photo attached, sheet says "Posted as QuickBooks Bill 149" |
| Bay Area Concrete Pumping approved without fixing the vendor | Sheet says "Still needs review: vendor "Bay Area Concrete Pumping" is not in QuickBooks", checkbox cleared |
| Purchase agreement form, Sunset Terrace HOA, $18,500 with 30% deposit | HubSpot deal in Contacted, DocuSign envelope sent to the test signer, row in `p2_agreements`, note in `#leads` |
| Sunset Terrace agreement signed in DocuSign | Connect called back about 20 seconds after signing: signed PDF filed in the Drive folder as "PA-20260929-103947 Sunset Terrace HOA (signed).pdf", HubSpot deal moved to Won with the close date and a link to the PDF, row marked `signed`, note in `#leads` |
| Second agreement voided through the DocuSign API | Connect called back about 20 seconds later, row marked `voided` with the reason, note in `#leads` |

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
  test_n8n_sync.py    fails if the exports and the code in this repo drift apart
review/
  read-corrections.js       the approvals workflow's Code node: reads what the reviewer typed
  test_read_corrections.py
generate/
  build-agreement.js        the agreement form's Code node: checks input, writes the HTML, builds the envelope
  run_code_node.js          runs an n8n Code node file under plain node for the tests
  test_build_agreement.py
n8n/
  document-intake.json
  post-bill.json
  send-to-review.json
  review-approvals.json
  agreement-out.json
  agreement-events.json
  reset-demo-data.json   manual only: deletes the demo Bills, rows, sheet entries, deals and signed PDFs
test-data/            the five sample bills, expected results, generator script
```

```bash
cd extract
python3 -m unittest -v          # 50 tests, no network
cd ../qbo
python3 -m unittest -v          # 46 tests, no network
cd ../review && python3 -m unittest -v     # needs node
cd ../generate && python3 -m unittest -v   # needs node
ANTHROPIC_API_KEY=... python3 extract.py ../test-data/04-tim-philip-masonry-117-handwritten.jpg
```

## Importing the workflow

Credential IDs are stripped from `n8n/document-intake.json`. After importing:

1. Attach your Gmail, Anthropic and Slack credentials.
2. Create a data table named `p2_documents` with the columns listed below and put its ID in the four data table nodes.
3. Put your Gmail label ID in the trigger and your error workflow ID in the workflow settings.
4. Import `n8n/post-bill.json` too. Attach your QuickBooks Online, Gmail and Slack credentials, put your QuickBooks company ID (realm ID) in the `QuickBooks config` node (both fields), and put the data table ID in its five data table nodes. Then put the posting workflow's ID in the intake's `Post Bill to QuickBooks` node.

5. Review sheet: make a Google Sheet with a `Review queue` tab and the header row `row_id, received, vendor, invoice_number, invoice_date, due_date, total, tax, why_review, warnings, claude_notes, email_link, approve, result, updated`. Put its ID in `send-to-review.json` and `review-approvals.json`, set the tab's gid in the "Checkbox and highlight" node (0 for the first tab) and your AP mailbox in the email link. Do not pre-fill checkboxes down the sheet (see the notes below).
6. Agreements: create a `p2_agreements` data table (`agreement_number, company, signer_name, signer_email, price (number), deposit (number), envelope_id, hubspot_deal_id, status, sent_at, signed_at, drive_file_id, drive_link, error`), a Drive folder for signed copies, and a DocuSign OAuth2 credential (generic OAuth2, `account-d.docusign.com`, scope `signature`). Fill in the DocuSign account ID, your n8n host, the folder ID and your HubSpot Contacted, Won and Lost stage IDs.
7. Optional: `n8n/reset-demo-data.json` puts everything back to empty between demo runs. It deletes every Bill that a `p2_documents` row points at, then all document rows, clears the review sheet below the header, deletes the HubSpot deal and Drive file for each agreement row, and then the agreement rows. Fill in the same realm ID, sheet ID, gid and table IDs. It only has a manual trigger, so leave it unpublished.

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
- Google Sheets checkboxes count as data. With checkbox validation pre-filled down 500 rows, the Sheets node's "append or update" put the first real row at row 501. The feeder now adds the checkbox and highlight only to rows that exist, after each upsert.
- The Sheets trigger node needs its own OAuth credential type. The approvals workflow polls the sheet every minute with the regular Sheets credential instead and handles one approved row per run, which also keeps a flood of approvals from racing each other.
- The Google Sheets credential's `drive.file` scope is enough to create the Drive folder and upload the signed PDFs, and a raw binary upload works on it (unlike the QuickBooks case above).
- DocuSign accepts an HTML document and converts it to PDF. Anchor tabs work on the converted text.
- Per-envelope Connect (`eventNotification`) works on the DocuSign developer account with no account-level Connect setup.
- The webhook trigger on the posting workflow has no auth. It only posts rows that are already `ready` and not yet posted, but add header auth before pointing it at real books.

## What's next

- Loom.
- Header auth on the three webhooks (posting, queue, DocuSign events) before this touches real books. DocuSign Connect can also sign its calls with HMAC once it is set up at the account level.
