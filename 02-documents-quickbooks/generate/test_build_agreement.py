"""Runs generate/build-agreement.js (the n8n Code node) under node with a small harness."""
import base64
import json
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FORM = {
    "company": "Sunset Terrace HOA", "signer_name": "Pat Rivera", "signer_email": "pat@example.com",
    "site": "400 Sunset Terrace", "scope": "Flagstone patio\nDrainage <north edge>", "price": 18500,
    "deposit_pct": 30, "start_date": "2026-10-12", "finish_date": "2026-10-30",
}


def run(form):
    out = subprocess.run(["node", os.path.join(HERE, "run_code_node.js"), os.path.join(HERE, "build-agreement.js"),
                          json.dumps(form)], capture_output=True, text=True, timeout=30)
    data = json.loads(out.stdout)
    return data if isinstance(data, dict) else data[0]["json"]


@unittest.skipUnless(shutil.which("node"), "node not installed")
class BuildAgreement(unittest.TestCase):
    def test_money_and_number(self):
        r = run(FORM)
        self.assertEqual(r["agreement_number"], "PA-20260929-103000")
        self.assertEqual((r["deposit"], r["balance"]), (5550, 12950))
        self.assertEqual(r["price_text"], "18,500.00")

    def test_zero_deposit_is_kept(self):
        self.assertEqual(run(dict(FORM, deposit_pct=0))["deposit"], 0)

    def test_blank_deposit_defaults_to_30(self):
        self.assertEqual(run(dict(FORM, deposit_pct=""))["deposit_pct"], 30)

    def test_labels_work_when_field_names_are_missing(self):
        form = {"Customer company": "A", "Signer name": "B", "Signer email": "b@x.co", "Scope of work": "s",
                "Contract price (USD)": "$1,200", "Deposit (%)": "10%"}
        r = run(form)
        self.assertEqual((r["price"], r["deposit"]), (1200, 120))

    def test_envelope(self):
        env = run(FORM)["envelope"]
        doc = env["documents"][0]
        self.assertEqual(doc["fileExtension"], "html")
        html = base64.b64decode(doc["documentBase64"]).decode()
        self.assertIn("\\s1\\", html)
        self.assertIn("\\d1\\", html)
        self.assertIn("Drainage &lt;north edge&gt;", html)  # escaped, newline kept
        self.assertIn("$18,500.00", html)
        tabs = env["recipients"]["signers"][0]["tabs"]
        self.assertEqual(tabs["signHereTabs"][0]["anchorString"], "\\s1\\")
        self.assertEqual(env["status"], "sent")
        self.assertEqual({e["envelopeEventStatusCode"] for e in env["eventNotification"]["envelopeEvents"]},
                         {"completed", "declined", "voided"})

    def test_bad_input_is_refused(self):
        r = run(dict(FORM, company="", signer_email="nope", price=0, deposit_pct=120, finish_date="2026-10-01"))
        for part in ["customer company is empty", "signer email", "price must be more than zero",
                     "deposit must be between", "completion date is before"]:
            self.assertIn(part, r["error"])


if __name__ == "__main__":
    unittest.main()
