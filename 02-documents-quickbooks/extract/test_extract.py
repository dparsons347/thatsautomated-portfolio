import base64
import io
import json
import unittest
import urllib.error

import extract


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code):
    return urllib.error.HTTPError(extract.API_URL, code, "err", {}, io.BytesIO(b'{"error": "x"}'))


class Opener:
    """Plays back a list of outcomes: an exception to raise or a dict to return."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, req, timeout):
        self.calls.append((req, timeout))
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return FakeResponse(json.dumps(out).encode())


OK = {"model": "claude-sonnet-5-5", "content": [{"type": "text", "text": '{"a": 1}'}]}


class Request(unittest.TestCase):
    def test_pdf_is_a_document_block(self):
        req = extract.build_request(b"%PDF-1.4", "application/pdf", prompt="P")
        block = req["messages"][0]["content"][0]
        self.assertEqual(block["type"], "document")
        self.assertEqual(block["source"]["media_type"], "application/pdf")
        self.assertEqual(base64.b64decode(block["source"]["data"]), b"%PDF-1.4")
        self.assertEqual(req["system"], "P")
        self.assertNotIn("temperature", req)  # rejected by claude-sonnet-5-5

    def test_jpg_is_an_image_block(self):
        req = extract.build_request(b"\xff\xd8", "image/jpeg", prompt="P")
        self.assertEqual(req["messages"][0]["content"][0]["type"], "image")

    def test_media_types(self):
        self.assertEqual(extract.media_type_for("x/INVOICE.PDF"), "application/pdf")
        self.assertEqual(extract.media_type_for("a.jpeg"), "image/jpeg")
        with self.assertRaises(ValueError):
            extract.media_type_for("a.docx")

    def test_prompt_file_loads(self):
        self.assertIn("Return ONLY this JSON object", extract.load_prompt())

    def test_response_text_joins_text_blocks(self):
        body = {"content": [{"type": "text", "text": "{\"a\""}, {"type": "tool_use"}, {"type": "text", "text": ": 1}"}]}
        self.assertEqual(extract.response_text(body), '{"a": 1}')
        self.assertEqual(extract.response_text({}), "")


class Retries(unittest.TestCase):
    def call(self, outcomes, tries=3):
        opener = Opener(outcomes)
        waits = []
        try:
            return extract.call_claude({"x": 1}, "k", tries=tries, sleep=waits.append, opener=opener), opener, waits
        except RuntimeError as e:
            return e, opener, waits

    def test_success_first_try(self):
        body, opener, waits = self.call([OK])
        self.assertEqual(body, OK)
        self.assertEqual(len(opener.calls), 1)
        req = opener.calls[0][0]
        self.assertEqual(req.get_header("X-api-key"), "k")
        self.assertEqual(req.get_header("Anthropic-version"), "2023-06-01")
        self.assertEqual(opener.calls[0][1], 120)

    def test_overloaded_then_ok(self):
        body, opener, waits = self.call([http_error(529), http_error(429), OK])
        self.assertEqual(body, OK)
        self.assertEqual(waits, [5, 10])

    def test_network_error_retried(self):
        body, opener, waits = self.call([urllib.error.URLError("reset"), OK])
        self.assertEqual(body, OK)

    def test_gives_up_after_tries(self):
        err, opener, waits = self.call([http_error(500)] * 3)
        self.assertIsInstance(err, RuntimeError)
        self.assertIn("failed after 3 tries (HTTP 500)", str(err))
        self.assertEqual(len(opener.calls), 3)
        self.assertEqual(waits, [5, 10])

    def test_400_not_retried(self):
        err, opener, waits = self.call([http_error(400), OK])
        self.assertIsInstance(err, RuntimeError)
        self.assertIn("HTTP 400", str(err))
        self.assertEqual(len(opener.calls), 1)


if __name__ == "__main__":
    unittest.main()
