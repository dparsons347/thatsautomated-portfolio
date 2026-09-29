"""The n8n workflow runs this module's code and prompt. Fail if they drift apart."""
import json
import os
import unittest

import extract

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT = os.path.join(HERE, "..", "n8n", "document-intake.json")


def node(workflow, name):
    return next(n for n in workflow["nodes"] if n["name"] == name)


@unittest.skipUnless(os.path.exists(EXPORT), "n8n export not present")
class WorkflowMatchesModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(EXPORT, encoding="utf-8") as f:
            cls.wf = json.load(f)

    def test_python_node_is_validate_py_verbatim(self):
        with open(os.path.join(HERE, "validate.py"), encoding="utf-8") as f:
            source = f.read()
        code = node(self.wf, "Validate extraction")["parameters"]["pythonCode"]
        self.assertTrue(code.startswith(source), "Validate extraction node differs from extract/validate.py")
        self.assertIn('check_extraction(src.get("claude_text"), stop_reason=src.get("stop_reason"))', code)

    def test_prompt_and_model_match(self):
        js = node(self.wf, "Build Claude request")["parameters"]["jsCode"]
        self.assertIn("const PROMPT = " + json.dumps(extract.load_prompt()) + ";", js)
        self.assertIn("model: '" + extract.MODEL + "'", js)
        self.assertIn("max_tokens: " + str(extract.MAX_TOKENS), js)

    def test_no_credential_ids_in_export(self):
        for n in self.wf["nodes"]:
            for cred in (n.get("credentials") or {}).values():
                self.assertNotIn("id", cred, n["name"])


if __name__ == "__main__":
    unittest.main()
