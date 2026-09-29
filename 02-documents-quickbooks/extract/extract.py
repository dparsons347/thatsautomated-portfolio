"""Read one invoice (PDF or image) with Claude and check what came back.

Standard library only. The n8n workflow does the same thing with an HTTP
Request node plus a Python Code node running validate.py, so this module is
the version you can unit test or run by hand:

    ANTHROPIC_API_KEY=... python3 extract.py ../test-data/01-norton-lumber-NL-20417.pdf
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

from validate import check_extraction

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 2000
PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.txt")

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def load_prompt():
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def media_type_for(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in MEDIA_TYPES:
        raise ValueError("unsupported file type " + ext + " (PDF, JPG, PNG, GIF or WEBP)")
    return MEDIA_TYPES[ext]


def content_block(data, media_type):
    """PDFs go in as a document block, images as an image block."""
    kind = "document" if media_type == "application/pdf" else "image"
    return {
        "type": kind,
        "source": {"type": "base64", "media_type": media_type,
                   "data": base64.b64encode(data).decode("ascii")},
    }


def build_request(data, media_type, prompt=None, model=MODEL):
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": prompt if prompt is not None else load_prompt(),
        "messages": [{
            "role": "user",
            "content": [content_block(data, media_type),
                        {"type": "text", "text": "Transcribe this bill."}],
        }],
    }


def response_text(body):
    """Join the text blocks of a Messages API response."""
    parts = body.get("content") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")


def call_claude(request, api_key, tries=3, timeout=120, sleep=time.sleep, opener=urllib.request.urlopen):
    """POST to the Messages API. Retries 429, 5xx, 529 and network errors, not 4xx."""
    payload = json.dumps(request).encode("utf-8")
    last = ""
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(API_URL, data=payload, method="POST", headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })
        try:
            with opener(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = "HTTP " + str(e.code)
            if e.code != 429 and e.code < 500:
                raise RuntimeError("Claude API returned " + last + ": " + e.read().decode("utf-8", "replace")[:300])
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = "network error: " + str(e)
        if attempt < tries:
            sleep(5 * attempt)
    raise RuntimeError("Claude API failed after " + str(tries) + " tries (" + last + ")")


def extract_file(path, api_key, model=MODEL):
    with open(path, "rb") as f:
        data = f.read()
    body = call_claude(build_request(data, media_type_for(path), model=model), api_key)
    result = check_extraction(response_text(body), stop_reason=body.get("stop_reason"))
    result["model"] = body.get("model", model)
    result["filename"] = os.path.basename(path)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+")
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args(argv)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("set ANTHROPIC_API_KEY", file=sys.stderr)
        return 2
    for path in args.files:
        print(json.dumps(extract_file(path, api_key, args.model), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
