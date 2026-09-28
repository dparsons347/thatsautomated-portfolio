# Project 2 test documents

Five sample vendor bills for the Documents to QuickBooks demo, billed to the QuickBooks sandbox sample company (Craig's Design and Landscaping Services). Vendor names match vendors in the sandbox sample data so the Bills post without creating new vendors. Every document says it is a demonstration document in the footer.

Send them to `daniel+ap@thatsautomated.com` (lands in the **AP Intake** label).

| # | File | Vendor | Invoice # | Total | What it tests | Expected result |
|---|---|---|---|---|---|---|
| 1 | `01-norton-lumber-NL-20417.pdf` | Norton Lumber and Building Materials | NL-20417 | $1,765.99 | Clean digital PDF with PO | Auto-posts as a Bill |
| 2 | `02-hicks-hardware-HH-8832.pdf` | Hicks Hardware | HH-8832 | $516.27 | Clean digital PDF, no PO | Auto-posts as a Bill |
| 3 | `03-ellis-rental-ER-5510-phone-photo.jpg` | Ellis Equipment Rental | ER-5510 | $1,058.41 | Skewed phone photo: perspective, shadow, uneven light | Auto-posts if extraction confidence clears the gate, otherwise Review |
| 4 | `04-tim-philip-masonry-117-handwritten.jpg` | Tim Philip Masonry | 117 | written $1,292.50 | Handwritten pad invoice. Lines add to **$1,252.50**, the written total is $40 high on purpose | Fails the totals check, goes to Review with the mismatch flagged |
| 5 | `05-norton-lumber-NL-20417-resent.pdf` | Norton Lumber and Building Materials | NL-20417 | $1,765.99 | Byte-identical copy of #1 under a new filename | Caught by the SHA-256 check before extraction, logged as duplicate |

## Line detail

**1. Norton Lumber** (tax 8.25%)
- 2x4x8 SPF stud, 120 @ $4.18 = $501.60
- 1/2" CDX plywood 4x8 sheet, 24 @ $38.95 = $934.80
- Galvanized deck screws, 5 lb box, 6 @ $32.50 = $195.00
- Subtotal $1,631.40, tax $134.59, total $1,765.99

**2. Hicks Hardware** (tax 8.25%)
- Irrigation valve 1", 8 @ $24.99 = $199.92
- PVC pipe Sch 40, 1" x 10 ft, 20 @ $7.45 = $149.00
- Drip tubing 1/2", 500 ft roll, 2 @ $64.00 = $128.00
- Subtotal $476.92, tax $39.35, total $516.27

**3. Ellis Equipment Rental** (tax 8.25%)
- Mini excavator, daily rate, 2 @ $385.00 = $770.00
- Delivery and pickup, 1 @ $150.00
- Damage waiver, 1 @ $57.75
- Subtotal $977.75, tax $80.66, total $1,058.41

**4. Tim Philip Masonry** (no tax, labor)
- Flagstone patio labor, 16 @ $65.00 = $1,040.00
- Mortar, sand, gravel, 1 @ $212.50
- Correct sum $1,252.50. Written total $1,292.50.

## Other checks worth running

- **Idempotency past the hash.** Re-export #1 (open it and print to PDF) so the bytes change but the vendor and invoice number don't. The hash check misses it, and the vendor + invoice number lookup in the `qbo/` client should skip it.
- **Real handwriting.** `blank-handwritten-invoice-form.pdf` is the same pad, left blank. Print it, fill it in by hand and photograph it if you want a handwritten sample that isn't a font.

## Regenerating

`make_invoices.py` builds everything. It needs reportlab, Pillow, numpy, pdftoppm (poppler) and two handwriting fonts from Google Fonts (Caveat and Homemade Apple, both OFL) saved as `caveat.ttf` and `homemade-apple.ttf` next to the script.
