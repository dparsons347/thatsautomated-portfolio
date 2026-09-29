import json
import unittest
from datetime import date

from validate import check_extraction, parse_date, parse_model_output, to_money

TODAY = date(2026, 9, 28)
HIGH = {"vendor": 0.98, "invoice_number": 0.97, "invoice_date": 0.96, "line_items": 0.95, "total": 0.97}


def norton(**over):
    """What a good read of test-data/01-norton-lumber-NL-20417.pdf looks like."""
    d = {
        "document_type": "invoice",
        "vendor": {"name": "Norton Lumber and Building Materials", "address": "4410 Industrial Pkwy, Richmond, CA 94804",
                   "email": "ar@nortonlumber.example", "phone": "(510) 555-0142"},
        "invoice_number": "NL-20417", "invoice_date": "2026-09-15", "due_date": "2026-10-15",
        "terms": "Net 30", "po_number": "CDL-1182", "currency": "USD",
        "line_items": [
            {"description": "2x4x8 SPF stud", "quantity": 120, "unit_price": 4.18, "amount": 501.60},
            {"description": '1/2" CDX plywood 4x8 sheet', "quantity": 24, "unit_price": 38.95, "amount": 934.80},
            {"description": "Galvanized deck screws, 5 lb box", "quantity": 6, "unit_price": 32.50, "amount": 195.00},
        ],
        "subtotal": 1631.40, "tax": 134.59, "total": 1765.99,
        "handwritten": False, "confidence": dict(HIGH), "notes": "",
    }
    d.update(over)
    return d


def masonry(**over):
    """test-data/04: handwritten, lines add to 1,252.50, written total 1,292.50."""
    d = {
        "document_type": "invoice", "vendor": {"name": "Tim Philip Masonry"},
        "invoice_number": "117", "invoice_date": "2026-09-22", "due_date": None, "terms": "Due on receipt",
        "po_number": None, "currency": "USD",
        "line_items": [
            {"description": "Flagstone patio - labor", "quantity": 16, "unit_price": 65.00, "amount": 1040.00},
            {"description": "Mortar, sand, gravel", "quantity": 1, "unit_price": 212.50, "amount": 212.50},
        ],
        "subtotal": None, "tax": None, "total": 1292.50, "handwritten": True,
        "confidence": {"vendor": 0.97, "invoice_number": 0.9, "invoice_date": 0.9, "line_items": 0.88, "total": 0.9},
        "notes": "labor - no tax",
    }
    d.update(over)
    return d


def run(d, **kw):
    return check_extraction(json.dumps(d), today=TODAY, **kw)


class ParseOutput(unittest.TestCase):
    def test_plain_json(self):
        data, err = parse_model_output('{"a": 1}')
        self.assertEqual(data, {"a": 1})
        self.assertEqual(err, "")

    def test_code_fence(self):
        data, err = parse_model_output('```json\n{"a": 1}\n```')
        self.assertEqual(data, {"a": 1})

    def test_prose_around(self):
        data, err = parse_model_output('Here is the bill:\n{"a": {"b": 2}}\nLet me know!')
        self.assertEqual(data, {"a": {"b": 2}})

    def test_truncated(self):
        data, err = parse_model_output('{"vendor": {"name": "Hicks Hardw')
        self.assertIsNone(data)
        self.assertIn("could not parse", err)

    def test_empty_and_none(self):
        self.assertEqual(parse_model_output("")[1], "empty model output")
        self.assertEqual(parse_model_output(None)[1], "empty model output")

    def test_object_wrapped_in_array_is_unwrapped(self):
        self.assertEqual(parse_model_output('[{"a": 1}]')[0], {"a": 1})

    def test_two_objects_is_invalid(self):
        self.assertIn("invalid JSON", parse_model_output('{"a": 1} and {"b": 2}')[1])


class Money(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(str(to_money("1,765.99")), "1765.99")
        self.assertEqual(str(to_money("$516.27")), "516.27")
        self.assertEqual(str(to_money(4.18)), "4.18")
        self.assertEqual(str(to_money(120)), "120.00")
        self.assertEqual(str(to_money("(40.00)")), "-40.00")

    def test_not_money(self):
        self.assertIsNone(to_money(None))
        self.assertIsNone(to_money("n/a"))
        self.assertIsNone(to_money(True))

    def test_float_noise_does_not_leak(self):
        self.assertEqual(str(to_money(0.1 + 0.2)), "0.30")


class Dates(unittest.TestCase):
    def test_iso_and_us(self):
        self.assertEqual(parse_date("2026-09-15"), date(2026, 9, 15))
        self.assertEqual(parse_date("09/15/2026"), date(2026, 9, 15))
        self.assertEqual(parse_date("9/22/26"), date(2026, 9, 22))

    def test_garbage(self):
        self.assertIsNone(parse_date("Sept 2026"))
        self.assertIsNone(parse_date("2026-02-30"))
        self.assertIsNone(parse_date(None))


class CleanInvoices(unittest.TestCase):
    def test_norton_is_ready(self):
        r = run(norton())
        self.assertEqual(r["status"], "ready", r["review_reasons"])
        self.assertEqual(r["vendor_name"], "Norton Lumber and Building Materials")
        self.assertEqual(r["total"], 1765.99)
        self.assertEqual(r["line_sum"], 1631.40)
        self.assertEqual(r["po_number"], "CDL-1182")
        self.assertEqual(r["min_confidence"], 0.95)

    def test_hicks_is_ready(self):
        r = run(norton(
            vendor={"name": "Hicks Hardware"}, invoice_number="HH-8832", invoice_date="2026-09-18",
            due_date="2026-10-03", po_number=None,
            line_items=[
                {"description": 'Irrigation valve, 1"', "quantity": 8, "unit_price": 24.99, "amount": 199.92},
                {"description": "PVC pipe", "quantity": 20, "unit_price": 7.45, "amount": 149.00},
                {"description": "Drip tubing", "quantity": 2, "unit_price": 64.00, "amount": 128.00},
            ],
            subtotal=476.92, tax=39.35, total=516.27))
        self.assertEqual(r["status"], "ready", r["review_reasons"])

    def test_amounts_as_strings_still_check(self):
        r = run(norton(subtotal="1,631.40", tax="$134.59", total="$1,765.99"))
        self.assertEqual(r["status"], "ready", r["review_reasons"])

    def test_one_cent_rounding_is_fine(self):
        r = run(norton(tax=134.60, total=1766.00))
        self.assertEqual(r["status"], "ready", r["review_reasons"])


class HandwrittenTotal(unittest.TestCase):
    def test_masonry_goes_to_review_with_the_gap(self):
        r = run(masonry())
        self.assertEqual(r["status"], "needs_review")
        self.assertEqual(len(r["review_reasons"]), 1, r["review_reasons"])
        self.assertIn("lines $1,252.50", r["review_reasons"][0])
        self.assertIn("total says $1,292.50", r["review_reasons"][0])
        self.assertIn("$40.00 off", r["review_reasons"][0])
        self.assertIn("handwritten values", r["warnings"])

    def test_model_copies_total_into_subtotal(self):
        r = run(masonry(subtotal=1292.50))
        self.assertEqual(r["status"], "needs_review")
        self.assertTrue(any("lines add to $1,252.50 but the subtotal says $1,292.50" in x for x in r["review_reasons"]))


class ReviewReasons(unittest.TestCase):
    def test_low_confidence_total(self):
        conf = dict(HIGH, total=0.6)
        r = run(norton(confidence=conf))
        self.assertEqual(r["status"], "needs_review")
        self.assertIn("low confidence on total (0.6)", r["review_reasons"])

    def test_threshold_is_configurable(self):
        conf = dict(HIGH, total=0.8)
        self.assertEqual(run(norton(confidence=conf))["status"], "needs_review")
        self.assertEqual(run(norton(confidence=conf), threshold=0.75)["status"], "ready")

    def test_missing_confidence(self):
        r = run(norton(confidence=None))
        self.assertIn("no confidence reported for total", r["review_reasons"])

    def test_missing_vendor_number_date_total(self):
        r = run(norton(vendor={"name": None}, invoice_number="", invoice_date=None, total=None))
        for msg in ["vendor name missing", "invoice number missing", "invoice date missing", "total missing"]:
            self.assertIn(msg, r["review_reasons"])

    def test_vendor_as_plain_string(self):
        self.assertEqual(run(norton(vendor="Hicks Hardware"))["vendor_name"], "Hicks Hardware")

    def test_unreadable_date(self):
        r = run(norton(invoice_date="Sept 15"))
        self.assertIn("invoice date not readable: Sept 15", r["review_reasons"])

    def test_future_date(self):
        r = run(norton(invoice_date="2027-03-01"))
        self.assertTrue(any("in the future" in x for x in r["review_reasons"]))

    def test_old_date_is_only_a_warning(self):
        r = run(norton(invoice_date="2023-01-10", due_date="2023-02-09"))
        self.assertEqual(r["status"], "ready")
        self.assertTrue(any("over two years old" in x for x in r["warnings"]))

    def test_line_math_wrong(self):
        items = norton()["line_items"]
        items[0] = dict(items[0], amount=510.60)
        r = run(norton(line_items=items))
        self.assertTrue(any(x.startswith("line 1: 120 x $4.18 = $501.60 but the amount says $510.60") for x in r["review_reasons"]))

    def test_tax_does_not_add_up(self):
        r = run(norton(total=1865.99))
        self.assertTrue(any("$100.00 off" in x for x in r["review_reasons"]))

    def test_statement_not_invoice(self):
        r = run(norton(document_type="statement"))
        self.assertIn("document looks like a statement, not an invoice", r["review_reasons"])

    def test_foreign_currency(self):
        self.assertIn("currency is CAD, books are in USD", run(norton(currency="cad"))["review_reasons"])

    def test_total_only_no_lines(self):
        r = run(norton(line_items=[], subtotal=None))
        self.assertIn("no line items or subtotal to check the total against", r["review_reasons"])

    def test_negative_total(self):
        r = run(norton(total=-20))
        self.assertTrue(any("expected a positive amount" in x for x in r["review_reasons"]))


class Robustness(unittest.TestCase):
    def test_garbage_never_raises(self):
        for raw in ["", "no json here", "{", '{"line_items": "lots"}', '{"line_items": [1, "x", null]}',
                    '{"confidence": [1,2]}', '{"total": {"amount": 5}}', '{"vendor": 42}']:
            r = check_extraction(raw, today=TODAY)
            self.assertEqual(r["status"], "needs_review", raw)

    def test_amount_filled_from_qty_times_price(self):
        items = norton()["line_items"]
        items[2] = dict(items[2], amount=None)
        r = run(norton(line_items=items))
        self.assertEqual(r["status"], "ready", r["review_reasons"])
        self.assertIn("line 3: amount missing, used quantity x price", r["warnings"])

    def test_fractional_quantity(self):
        r = run(norton(line_items=[{"description": "Labor", "quantity": 2.5, "unit_price": 80, "amount": 200}],
                       subtotal=200, tax=0, total=200))
        self.assertEqual(r["status"], "ready", r["review_reasons"])

    def test_cut_off_output(self):
        r = check_extraction('{"vendor": {"name": "Hicks', today=TODAY, stop_reason="max_tokens")
        self.assertEqual(r["review_reasons"][0], "model output was cut off (max_tokens)")
        r = check_extraction(json.dumps(norton()), today=TODAY, stop_reason="max_tokens")
        self.assertEqual(r["status"], "needs_review")

    def test_output_is_json_serializable(self):
        json.dumps(run(norton()))
        json.dumps(run(masonry()))


if __name__ == "__main__":
    unittest.main()
