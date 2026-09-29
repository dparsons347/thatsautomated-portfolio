import json
import unittest

import bill

VENDORS = [
    {"Id": "46", "DisplayName": "Norton Lumber and Building Materials", "CompanyName": "Norton Lumber and Building Materials"},
    {"Id": "41", "DisplayName": "Hicks Hardware", "CompanyName": "Hicks Hardware"},
    {"Id": "38", "DisplayName": "Ellis Equipment Rental", "CompanyName": "Ellis Equipment Rental"},
    {"Id": "51", "DisplayName": "Tim Philip Masonry", "CompanyName": "Tim Philip Masonry"},
    {"Id": "30", "DisplayName": "Bob's Burger Joint"},
    {"Id": "60", "DisplayName": "Pacific Supply"},
    {"Id": "61", "DisplayName": "Pacific Supply West"},
]
ACCOUNTS = [
    {"Id": "57", "Name": "Job Materials", "FullyQualifiedName": "Job Expenses:Job Materials"},
    {"Id": "36", "Name": "Decks and Patios", "FullyQualifiedName": "Job Expenses:Job Materials:Decks and Patios"},
    {"Id": "29", "Name": "Equipment Rental", "FullyQualifiedName": "Equipment Rental"},
]

NORTON = {
    "id": 4, "sha256": "f54e0015606207faa333", "filename": "01-norton-lumber-NL-20417.pdf",
    "vendor_name": "Norton Lumber and Building Materials", "invoice_number": "NL-20417",
    "invoice_date": "2026-09-15", "due_date": "2026-10-15", "po_number": "CDL-1182",
    "subtotal": 1631.4, "tax": 134.59, "total": 1765.99,
    "line_items_json": json.dumps([
        {"description": "2x4x8 SPF stud", "quantity": 120, "unit_price": 4.18, "amount": 501.6},
        {"description": "1/2\" CDX plywood 4x8 sheet", "quantity": 24, "unit_price": 38.95, "amount": 934.8},
        {"description": "Galvanized deck screws, 5 lb box", "quantity": 6, "unit_price": 32.5, "amount": 195},
    ]),
}


class VendorMatch(unittest.TestCase):
    def test_exact(self):
        v, why = bill.match_vendor("Hicks Hardware", VENDORS)
        self.assertEqual(v["Id"], "41")
        self.assertEqual(why, "")

    def test_ampersand_and_suffix(self):
        v, _ = bill.match_vendor("Norton Lumber & Building Materials, Inc.", VENDORS)
        self.assertEqual(v["Id"], "46")

    def test_apostrophe_and_case(self):
        v, _ = bill.match_vendor("BOBS BURGER JOINT", VENDORS)
        self.assertEqual(v["Id"], "30")
        v, _ = bill.match_vendor("Bob\u2019s Burger Joint", VENDORS)
        self.assertEqual(v["Id"], "30")

    def test_partial_single(self):
        v, _ = bill.match_vendor("Ellis Equipment Rental Co", VENDORS)
        self.assertEqual(v["Id"], "38")
        v, _ = bill.match_vendor("Ellis Equipment", VENDORS)  # 14 of 22 chars
        self.assertEqual(v["Id"], "38")

    def test_partial_too_short(self):
        v, why = bill.match_vendor("Ellis", VENDORS)
        self.assertIsNone(v)
        self.assertIn("not in QuickBooks", why)

    def test_exact_beats_partial(self):
        v, _ = bill.match_vendor("Pacific Supply", VENDORS)
        self.assertEqual(v["Id"], "60")

    def test_ambiguous_partial(self):
        vendors = [{"Id": "1", "DisplayName": "Acme Supply North"}, {"Id": "2", "DisplayName": "Acme Supply South"}]
        v, why = bill.match_vendor("Acme Supply", vendors)
        self.assertIsNone(v)
        self.assertIn("could be any of", why)

    def test_unknown(self):
        v, why = bill.match_vendor("Bay Area Concrete Pumping", VENDORS)
        self.assertIsNone(v)
        self.assertEqual(why, 'vendor "Bay Area Concrete Pumping" is not in QuickBooks')

    def test_empty(self):
        self.assertEqual(bill.match_vendor("", VENDORS)[1], "no vendor name to match")


class Accounts(unittest.TestCase):
    def test_default(self):
        a, _ = bill.account_for_vendor(VENDORS[0], ACCOUNTS)
        self.assertEqual(a["Id"], "57")

    def test_mapped(self):
        self.assertEqual(bill.account_for_vendor(VENDORS[2], ACCOUNTS)[0]["Id"], "29")
        self.assertEqual(bill.account_for_vendor(VENDORS[3], ACCOUNTS)[0]["Id"], "36")

    def test_mapped_missing_falls_back(self):
        a, _ = bill.account_for_vendor(VENDORS[2], [ACCOUNTS[0]])
        self.assertEqual(a["Id"], "57")

    def test_nothing(self):
        a, why = bill.account_for_vendor(VENDORS[0], [])
        self.assertIsNone(a)
        self.assertIn("not found", why)


class BuildBill(unittest.TestCase):
    def test_norton(self):
        plan = bill.plan_bill(NORTON, VENDORS, ACCOUNTS)
        self.assertEqual(plan["action"], "post")
        b = plan["bill"]
        self.assertEqual(b["VendorRef"]["value"], "46")
        self.assertEqual(b["DocNumber"], "NL-20417")
        self.assertEqual(b["TxnDate"], "2026-09-15")
        self.assertEqual(b["DueDate"], "2026-10-15")
        self.assertEqual(len(b["Line"]), 4)
        self.assertEqual(b["Line"][-1]["Description"], "Sales tax")
        self.assertAlmostEqual(sum(l["Amount"] for l in b["Line"]), 1765.99, places=2)
        self.assertEqual(b["Line"][0]["Description"], "2x4x8 SPF stud (120 @ 4.18)")
        self.assertEqual(b["Line"][0]["AccountBasedExpenseLineDetail"]["AccountRef"]["value"], "57")
        self.assertIn("PO CDL-1182", b["PrivateNote"])
        self.assertIn("01-norton-lumber-NL-20417.pdf", b["PrivateNote"])
        self.assertEqual(plan["duplicate_query"],
                         "select Id, DocNumber, TotalAmt, TxnDate from Bill where VendorRef = '46' and DocNumber = 'NL-20417'")

    def test_quantity_one_keeps_plain_description(self):
        doc = dict(NORTON, line_items_json=json.dumps([{"description": "Delivery", "quantity": 1, "unit_price": 150, "amount": 150}]),
                   subtotal=150, tax=0, total=150)
        b = bill.plan_bill(doc, VENDORS, ACCOUNTS)["bill"]
        self.assertEqual([l["Description"] for l in b["Line"]], ["Delivery"])  # zero tax adds no line

    def test_total_mismatch_goes_to_review(self):
        doc = dict(NORTON, total=1805.99)
        plan = bill.plan_bill(doc, VENDORS, ACCOUNTS)
        self.assertEqual(plan["action"], "review")
        self.assertIn("Bill lines add to $1,765.99 but the invoice total is $1,805.99", plan["review_reasons"])

    def test_unknown_vendor_goes_to_review(self):
        plan = bill.plan_bill(dict(NORTON, vendor_name="Bay Area Concrete Pumping"), VENDORS, ACCOUNTS)
        self.assertEqual(plan["action"], "review")
        self.assertEqual(plan["bill"], None)
        self.assertEqual(plan["review_reasons"], ['vendor "Bay Area Concrete Pumping" is not in QuickBooks'])

    def test_long_doc_number(self):
        plan = bill.plan_bill(dict(NORTON, invoice_number="X" * 22), VENDORS, ACCOUNTS)
        self.assertIn("longer than QuickBooks allows", plan["review_reasons"][0])

    def test_missing_fields(self):
        doc = dict(NORTON, invoice_number="", invoice_date="", total=None, line_items_json="[]")
        reasons = bill.plan_bill(doc, VENDORS, ACCOUNTS)["review_reasons"]
        self.assertIn("invoice number missing", reasons)
        self.assertIn("invoice date missing", reasons)
        self.assertIn("total missing or not positive", reasons)
        self.assertIn("no line items to post", reasons)

    def test_bad_line_json(self):
        reasons = bill.plan_bill(dict(NORTON, line_items_json="{not json"), VENDORS, ACCOUNTS)["review_reasons"]
        self.assertIn("no line items to post", reasons)

    def test_line_items_list_accepted(self):
        doc = dict(NORTON)
        doc["line_items"] = json.loads(doc.pop("line_items_json"))
        self.assertEqual(bill.plan_bill(doc, VENDORS, ACCOUNTS)["action"], "post")

    def test_no_due_date(self):
        b = bill.plan_bill(dict(NORTON, due_date=""), VENDORS, ACCOUNTS)["bill"]
        self.assertNotIn("DueDate", b)


class Queries(unittest.TestCase):
    def test_quote_escapes(self):
        self.assertEqual(bill.quote("O'Brien\\"), "'O\\'Brien\\\\'")
        self.assertIn("DocNumber = 'A\\'1'", bill.duplicate_query("5", "A'1"))

    def test_query_rows(self):
        self.assertEqual(bill.query_rows({"QueryResponse": {"Bill": [{"Id": "1"}]}}, "Bill"), [{"Id": "1"}])
        self.assertEqual(bill.query_rows({"QueryResponse": {}}, "Bill"), [])
        self.assertEqual(bill.query_rows(None, "Bill"), [])


class SandboxRules(unittest.TestCase):
    """bill.py runs in n8n's Python sandbox, which blocks most imports and dunder names."""

    def test_only_allowed_imports(self):
        with open(bill.__file__, encoding="utf-8") as f:
            src = f.read()
        imports = {l.split()[1] for l in src.splitlines() if l.startswith(("import ", "from "))}
        self.assertLessEqual(imports, {"json", "re", "decimal"})
        self.assertNotRegex(src.replace("__file__", ""), r"__\w+__")


if __name__ == "__main__":
    unittest.main()
