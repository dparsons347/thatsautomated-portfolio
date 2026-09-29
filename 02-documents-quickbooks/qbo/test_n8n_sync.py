"""The n8n posting workflow runs bill.py as-is. Fail if the export and this folder drift apart."""
import json
import os
import unittest

import bill

HERE = os.path.dirname(os.path.abspath(__file__))
POST = os.path.join(HERE, "..", "n8n", "post-bill.json")
INTAKE = os.path.join(HERE, "..", "n8n", "document-intake.json")


def node(workflow, name):
    return next(n for n in workflow["nodes"] if n["name"] == name)


@unittest.skipUnless(os.path.exists(POST), "n8n export not present")
class PostingWorkflowMatchesModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(POST, encoding="utf-8") as f:
            cls.wf = json.load(f)

    def test_python_node_is_bill_py_verbatim(self):
        with open(os.path.join(HERE, "bill.py"), encoding="utf-8") as f:
            source = f.read()
        code = node(self.wf, "Plan the Bill")["parameters"]["pythonCode"]
        self.assertTrue(code.startswith(source), "Plan the Bill node differs from qbo/bill.py")
        self.assertIn('plan_bill(src.get("doc") or {}, src.get("vendors") or [], src.get("accounts") or [])', code)

    def test_queries_match(self):
        def query(name):
            params = node(self.wf, name)["parameters"]["queryParameters"]["parameters"]
            return next(p["value"] for p in params if p["name"] == "query")
        self.assertEqual(query("QBO: list vendors"), bill.VENDOR_QUERY)
        self.assertEqual(query("QBO: list accounts"), bill.ACCOUNT_QUERY)

    def test_create_is_not_retried(self):
        # A retried POST /bill could create the Bill twice; the duplicate check runs before it instead.
        self.assertFalse(node(self.wf, "QBO: create Bill").get("retryOnFail", False))

    def test_no_credential_ids_or_realm_in_export(self):
        for n in self.wf["nodes"]:
            for cred in (n.get("credentials") or {}).values():
                self.assertNotIn("id", cred, n["name"])
        config = node(self.wf, "QuickBooks config")["parameters"]["assignments"]["assignments"]
        self.assertEqual(next(a["value"] for a in config if a["name"] == "realm_id"), "REPLACE_WITH_REALM_ID")

    @unittest.skipUnless(os.path.exists(INTAKE), "intake export not present")
    def test_intake_hands_ready_rows_to_posting(self):
        with open(INTAKE, encoding="utf-8") as f:
            intake = json.load(f)
        call = node(intake, "Post Bill to QuickBooks")
        self.assertEqual(call["type"], "n8n-nodes-base.executeWorkflow")
        targets = [c["node"] for c in intake["connections"]["Ready to post?"]["main"][0]]
        self.assertEqual(targets, ["Post Bill to QuickBooks"])


if __name__ == "__main__":
    unittest.main()
