import io
import json
import unittest
import urllib.error
import urllib.parse

import client
from test_bill import ACCOUNTS, NORTON, VENDORS


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, body):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(json.dumps(body).encode()))


AUTH_FAULT = {"fault": {"error": [{"message": "message=AuthenticationFailed; errorCode=003200", "detail": "Token expired"}]}}


class FakeQBO:
    """Stands in for urlopen. Routes by URL, records every request."""

    def __init__(self, bills=None, expire_first=0, token_error=False):
        self.bills = list(bills or [])
        self.expire_first = expire_first  # how many API calls fail with 401 before the token works
        self.token_error = token_error
        self.calls = []
        self.issued = 0

    def __call__(self, req, timeout):
        url = req.full_url
        self.calls.append(req)
        if url == client.TOKEN_URL:
            if self.token_error:
                raise http_error(400, {"error": "invalid_grant"})
            self.issued += 1
            return FakeResponse(json.dumps({"access_token": "at" + str(self.issued),
                                            "refresh_token": "rt" + str(self.issued)}).encode())
        if self.expire_first:
            self.expire_first -= 1
            raise http_error(401, AUTH_FAULT)
        path = urllib.parse.urlparse(url).path
        if path.endswith("/query"):
            sql = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["query"][0]
            if "from Vendor" in sql:
                return self.ok({"QueryResponse": {"Vendor": VENDORS}})
            if "from Account" in sql:
                return self.ok({"QueryResponse": {"Account": ACCOUNTS}})
            if "from Bill" in sql:
                hits = [b for b in self.bills if "'" + b["DocNumber"] + "'" in sql]
                return self.ok({"QueryResponse": {"Bill": hits} if hits else {}})
        if path.endswith("/bill"):
            payload = json.loads(req.data)
            if payload["DocNumber"] == "BOOM":
                raise http_error(400, {"Fault": {"Error": [{"Message": "Business Validation Error",
                                                            "Detail": "Account is inactive"}]}})
            created = dict(payload, Id=str(100 + len(self.bills)), TotalAmt=sum(l["Amount"] for l in payload["Line"]))
            self.bills.append(created)
            return self.ok({"Bill": created})
        if path.endswith("/upload"):
            return self.ok({"AttachableResponse": [{"Attachable": {"Id": "900"}}]})
        raise AssertionError("unexpected call " + url)

    @staticmethod
    def ok(data):
        return FakeResponse(json.dumps(data).encode())

    def api_calls(self):
        return [c for c in self.calls if c.full_url != client.TOKEN_URL]


def make(fake, tokens=None, saved=None):
    return client.QBOClient("9341", "cid", "secret",
                            tokens if tokens is not None else {"access_token": "old", "refresh_token": "rt0"},
                            opener=fake, save_tokens=(saved.append if saved is not None else None))


class Posting(unittest.TestCase):
    def test_posts_and_attaches(self):
        fake = FakeQBO()
        result = client.post_document(make(fake), NORTON, b"%PDF-1.4 fake")
        self.assertEqual(result["status"], "posted")
        self.assertEqual(result["qbo_bill_id"], "100")
        self.assertEqual(result["attachment_id"], "900")
        self.assertAlmostEqual(result["total"], 1765.99, places=2)
        upload = [c for c in fake.calls if c.full_url.split("?")[0].endswith("/upload")][0]
        self.assertIn(b'"value": "100"', upload.data)
        self.assertIn(b"%PDF-1.4 fake", upload.data)
        self.assertTrue(upload.headers["Content-type"].startswith("multipart/form-data; boundary="))

    def test_second_run_does_not_double_post(self):
        fake = FakeQBO()
        qbo = make(fake)
        first = client.post_document(qbo, NORTON)
        second = client.post_document(qbo, NORTON)
        self.assertEqual(second["status"], "already_in_qbo")
        self.assertEqual(second["qbo_bill_id"], first["qbo_bill_id"])
        self.assertEqual(len(fake.bills), 1)

    def test_unknown_vendor_never_calls_create(self):
        fake = FakeQBO()
        result = client.post_document(make(fake), dict(NORTON, vendor_name="Bay Area Concrete Pumping"))
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(any("/bill" in c.full_url for c in fake.calls))

    def test_api_error_is_readable(self):
        with self.assertRaises(client.QBOError) as ctx:
            client.post_document(make(FakeQBO()), dict(NORTON, invoice_number="BOOM"))
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("Business Validation Error: Account is inactive", str(ctx.exception))


class TokenRefresh(unittest.TestCase):
    def test_expired_token_refreshes_and_retries_once(self):
        fake = FakeQBO(expire_first=1)
        saved = []
        qbo = make(fake, saved=saved)
        result = client.post_document(qbo, NORTON)
        self.assertEqual(result["status"], "posted")
        self.assertEqual(qbo.refreshes, 1)
        self.assertEqual(saved[-1], {"access_token": "at1", "refresh_token": "rt1"})  # rotated token kept
        self.assertEqual(fake.api_calls()[1].headers["Authorization"], "Bearer at1")

    def test_second_401_gives_up(self):
        fake = FakeQBO(expire_first=5)
        with self.assertRaises(client.QBOError) as ctx:
            make(fake).vendors()
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("Token expired", str(ctx.exception))
        self.assertEqual(len(fake.api_calls()), 2)

    def test_no_access_token_refreshes_first(self):
        fake = FakeQBO()
        qbo = make(fake, tokens={"refresh_token": "rt0"})
        qbo.vendors()
        self.assertEqual(fake.calls[0].full_url, client.TOKEN_URL)
        self.assertIn(b"refresh_token=rt0", fake.calls[0].data)
        self.assertTrue(fake.calls[0].headers["Authorization"].startswith("Basic "))

    def test_bad_refresh_token(self):
        fake = FakeQBO(token_error=True)
        with self.assertRaises(client.QBOError) as ctx:
            make(fake, tokens={"refresh_token": "revoked"}).vendors()
        self.assertIn("token refresh failed: invalid_grant", str(ctx.exception))

    def test_missing_refresh_token(self):
        with self.assertRaises(client.QBOError):
            make(FakeQBO(), tokens={}).vendors()


class Multipart(unittest.TestCase):
    def test_layout(self):
        ctype, body = client.build_multipart("77", 'a"b.pdf', "application/pdf", b"DATA", boundary="XYZ")
        self.assertEqual(ctype, "multipart/form-data; boundary=XYZ")
        text = body.decode()
        self.assertTrue(text.startswith("--XYZ\r\n"))
        self.assertTrue(text.endswith("--XYZ--\r\n"))
        self.assertIn('name="file_metadata_01"', text)
        self.assertIn('name="file_content_01"; filename="ab.pdf"', text)
        meta = json.loads(text.split("Content-Type: application/json\r\n\r\n")[1].split("\r\n")[0])
        self.assertEqual(meta["AttachableRef"][0]["EntityRef"], {"type": "Bill", "value": "77"})


class Faults(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(client.fault_message(json.dumps(AUTH_FAULT)),
                         "message=AuthenticationFailed; errorCode=003200: Token expired")
        self.assertEqual(client.fault_message('{"error": "invalid_grant"}'), "invalid_grant")
        self.assertEqual(client.fault_message("<html>bad gateway</html>"), "<html>bad gateway</html>")


if __name__ == "__main__":
    unittest.main()
