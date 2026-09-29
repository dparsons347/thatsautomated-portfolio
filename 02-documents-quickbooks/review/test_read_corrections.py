"""Runs review/read-corrections.js (the n8n Code node) under node with the shared harness."""
import json
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "..", "generate", "run_code_node.js")
ROW = {"row_id": 1, "vendor": "Tim Philip Masonry", "invoice_number": 117, "invoice_date": "2026-09-22",
       "due_date": "", "total": "1,252.50", "tax": "", "approve": True}


def run(row):
    out = subprocess.run(["node", HARNESS, os.path.join(HERE, "read-corrections.js"), json.dumps(row)],
                         capture_output=True, text=True, timeout=30)
    return json.loads(out.stdout)[0]["json"]


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ReadCorrections(unittest.TestCase):
    def test_clean_row(self):
        r = run(ROW)
        self.assertEqual(r["problems"], [])
        self.assertEqual(r["document_id"], 1)
        self.assertEqual(r["fields"], {"vendor_name": "Tim Philip Masonry", "invoice_number": "117",
                                       "invoice_date": "2026-09-22", "due_date": "", "total": 1252.5, "tax": None})

    def test_us_dates_and_sheet_serials(self):
        self.assertEqual(run(dict(ROW, invoice_date="9/22/26"))["fields"]["invoice_date"], "2026-09-22")
        self.assertEqual(run(dict(ROW, invoice_date=46287))["fields"]["invoice_date"], "2026-09-22")

    def test_typos_come_back_to_the_reviewer(self):
        r = run(dict(ROW, vendor=" ", total="12o0", tax="abc", invoice_date="Sept 22", due_date="soon"))
        self.assertEqual(r["problems"], ["vendor is empty", "total must be a positive number", "tax must be a number or blank",
                                         "invoice_date should look like 2026-09-22", "due_date should look like 2026-10-22 or be blank"])


if __name__ == "__main__":
    unittest.main()
