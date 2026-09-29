"""QuickBooks Online client for posting extracted invoices as Bills.

The n8n workflow does the same steps with HTTP Request nodes on n8n's
QuickBooks credential, which refreshes tokens on its own. This module is the
code version: it owns the OAuth refresh, retries once on a 401, checks for an
existing Bill before creating one, and attaches the original file.

    export QBO_CLIENT_ID=... QBO_CLIENT_SECRET=... QBO_REALM_ID=...
    export QBO_REFRESH_TOKEN=...          # first run only; later runs use qbo_tokens.json
    python3 client.py row.json invoice.pdf

row.json is one p2_documents row (the fields extract/validate.py produces).
"""
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

import bill as billmod

TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
API_HOSTS = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "production": "https://quickbooks.api.intuit.com",
}
MINOR_VERSION = "75"
TIMEOUT = 60
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qbo_tokens.json")


class QBOError(Exception):
    def __init__(self, status, message, body=None):
        super().__init__("QuickBooks " + str(status) + ": " + message)
        self.status = status
        self.body = body


def fault_message(body):
    """Readable message from a QuickBooks Fault response."""
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return (body or "")[:300] if isinstance(body, str) else "no response body"
    fault = data.get("Fault") or data.get("fault") or {}
    errors = fault.get("Error") or fault.get("error") or []
    parts = []
    for e in errors:
        msg = e.get("Message") or e.get("message") or ""
        detail = e.get("Detail") or e.get("detail") or ""
        parts.append((msg + (": " + detail if detail else "")).strip())
    if parts:
        return "; ".join(parts)
    if data.get("error"):
        return str(data.get("error")) + (" " + str(data.get("error_description")) if data.get("error_description") else "")
    return json.dumps(data)[:300]


def build_multipart(bill_id, filename, mime_type, data, boundary=None):
    """Body for POST /upload: Attachable metadata linked to the Bill, then the file.

    Returns (content_type, body_bytes).
    """
    boundary = boundary or "qbo-" + uuid.uuid4().hex
    meta = {
        "AttachableRef": [{"EntityRef": {"type": "Bill", "value": str(bill_id)}, "IncludeOnSend": False}],
        "FileName": filename,
        "ContentType": mime_type,
    }
    crlf = b"\r\n"
    parts = [
        b"--" + boundary.encode(),
        b'Content-Disposition: form-data; name="file_metadata_01"; filename="attachment.json"',
        b"Content-Type: application/json",
        b"",
        json.dumps(meta).encode(),
        b"--" + boundary.encode(),
        ('Content-Disposition: form-data; name="file_content_01"; filename="' + filename.replace('"', "") + '"').encode(),
        ("Content-Type: " + mime_type).encode(),
        b"",
        data,
        b"--" + boundary.encode() + b"--",
        b"",
    ]
    return "multipart/form-data; boundary=" + boundary, crlf.join(parts)


class QBOClient:
    def __init__(self, realm_id, client_id, client_secret, tokens, environment="sandbox",
                 opener=None, save_tokens=None):
        self.realm_id = str(realm_id)
        self.client_id = client_id
        self.client_secret = client_secret
        self.tokens = dict(tokens)
        self.base = API_HOSTS[environment] + "/v3/company/" + self.realm_id
        self.opener = opener or urllib.request.urlopen
        self.save_tokens = save_tokens
        self.refreshes = 0

    # ---- auth ----
    def refresh(self):
        refresh_token = self.tokens.get("refresh_token")
        if not refresh_token:
            raise QBOError(401, "no refresh token; run the OAuth flow once and set QBO_REFRESH_TOKEN")
        basic = base64.b64encode((self.client_id + ":" + self.client_secret).encode()).decode()
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        req = urllib.request.Request(TOKEN_URL, data=body, method="POST", headers={
            "Authorization": "Basic " + basic,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        try:
            with self.opener(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise QBOError(e.code, "token refresh failed: " + fault_message(e.read().decode(errors="replace")))
        # Intuit rotates refresh tokens, so the new one has to be kept.
        self.tokens["access_token"] = data["access_token"]
        self.tokens["refresh_token"] = data.get("refresh_token", refresh_token)
        self.refreshes += 1
        if self.save_tokens:
            self.save_tokens(self.tokens)

    # ---- transport ----
    def request(self, method, path, params=None, body=None, content_type="application/json"):
        """Call the API. Refreshes the access token and retries once on a 401."""
        if not self.tokens.get("access_token"):
            self.refresh()
        query = {"minorversion": MINOR_VERSION}
        query.update(params or {})
        url = self.base + path + "?" + urllib.parse.urlencode(query)
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        for attempt in (1, 2):
            headers = {"Authorization": "Bearer " + self.tokens["access_token"], "Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = content_type
            req = urllib.request.Request(url, data=body, method=method, headers=headers)
            try:
                with self.opener(req, timeout=TIMEOUT) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                text = e.read().decode(errors="replace")
                if e.code == 401 and attempt == 1:
                    self.refresh()
                    continue
                raise QBOError(e.code, fault_message(text), text)
        raise QBOError(401, "still unauthorized after refreshing the token")

    # ---- API ----
    def query(self, sql):
        return self.request("GET", "/query", params={"query": sql})

    def vendors(self):
        return billmod.query_rows(self.query(billmod.VENDOR_QUERY), "Vendor")

    def accounts(self):
        return billmod.query_rows(self.query(billmod.ACCOUNT_QUERY), "Account")

    def create_bill(self, payload):
        return self.request("POST", "/bill", body=payload)["Bill"]

    def attach(self, bill_id, filename, mime_type, data):
        ctype, body = build_multipart(bill_id, filename, mime_type, data)
        resp = self.request("POST", "/upload", body=body, content_type=ctype)
        items = resp.get("AttachableResponse") or []
        if items and items[0].get("Fault"):
            raise QBOError(400, fault_message(json.dumps(items[0])))
        return items[0].get("Attachable", {}) if items else {}


def post_document(client, doc, file_bytes=None):
    """Post one p2_documents row. Safe to run twice: the second run finds the Bill.

    Returns a dict with status posted / already_in_qbo / needs_review, the
    Bill ID when there is one, and review_reasons.
    """
    plan = billmod.plan_bill(doc, client.vendors(), client.accounts())
    if plan["action"] != "post":
        return {"status": "needs_review", "qbo_bill_id": "", "review_reasons": plan["review_reasons"]}
    existing = billmod.query_rows(client.query(plan["duplicate_query"]), "Bill")
    if existing:
        return {"status": "already_in_qbo", "qbo_bill_id": str(existing[0]["Id"]), "review_reasons": [],
                "note": "Bill " + str(existing[0]["Id"]) + " already has this vendor and invoice number"}
    created = client.create_bill(plan["bill"])
    result = {"status": "posted", "qbo_bill_id": str(created["Id"]), "review_reasons": [],
              "total": created.get("TotalAmt")}
    if file_bytes is not None:
        att = client.attach(created["Id"], doc.get("filename") or "invoice", doc.get("mime_type")
                            or "application/octet-stream", file_bytes)
        result["attachment_id"] = str(att.get("Id", ""))
    return result


def load_tokens():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"refresh_token": os.environ.get("QBO_REFRESH_TOKEN", "")}


def save_tokens(tokens):
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f)
    os.chmod(TOKEN_FILE, 0o600)


def main(argv):
    if len(argv) < 2:
        print("usage: python3 client.py row.json [invoice-file]", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as f:
        doc = json.load(f)
    data = None
    if len(argv) > 2:
        with open(argv[2], "rb") as f:
            data = f.read()
        doc.setdefault("filename", os.path.basename(argv[2]))
        doc.setdefault("mime_type", mimetypes.guess_type(argv[2])[0] or "application/octet-stream")
    client = QBOClient(os.environ["QBO_REALM_ID"], os.environ["QBO_CLIENT_ID"], os.environ["QBO_CLIENT_SECRET"],
                       load_tokens(), environment=os.environ.get("QBO_ENV", "sandbox"), save_tokens=save_tokens)
    try:
        result = post_document(client, doc, data)
    except QBOError as e:
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
