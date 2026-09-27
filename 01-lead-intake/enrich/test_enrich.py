"""Tests for enrich.py. No network: fetch and Claude calls are stubbed.

    python -m unittest -v test_enrich.py
"""

import socket
import unittest
import urllib.error
from email.message import Message

import enrich

PAGE = (
    "<html><head><title>Carter Heating &amp; Air</title>"
    '<meta name="description" content="HVAC repair in Auburn, AL"></head>'
    "<body><script>var x = 1;</script><style>p{}</style>"
    "<h1>We&#x27;re a family HVAC shop</h1><p>"
    + "Twelve technicians and eight trucks serving Lee County since 1998. " * 5
    + "</p></body></html>"
)

GOOD_REPLY = (
    '{"what_they_do": "residential HVAC repair", "size_hint": "11_50", '
    '"location": "Auburn, AL", "services": ["AC repair", "heating", "duct cleaning"], '
    '"summary": "Family HVAC shop with twelve technicians. Serves Lee County."}'
)

TOM = {
    "email": "tom@reevesfamilydental.com", "name": "Tom Reeves", "company": "Reeves Family Dental",
    "phone": "(334) 555-0187",
    "message": "AC unit stopped cooling at their 2,400 sq ft dental office in Opelika. "
               "They need emergency repair by tomorrow morning before patients arrive at 8am.",
}
PAT = {"email": "pat@nguyen-roofing-p1test.com", "name": "Pat Nguyen", "company": "Nguyen Roofing",
       "phone": "", "message": "Need a quote"}


def http_error(code):
    return urllib.error.HTTPError("https://x.test", code, "err", Message(), None)


class Recorder:
    """Opener stub: raises or returns the queued results in order and counts calls."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        r = self.results.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


class FetchTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []

    def fetch(self, opener, **kw):
        return enrich.fetch_site("https://x.test", opener=opener, sleep=self.sleeps.append, **kw)

    def test_timeout_is_passed_to_every_attempt(self):
        rec = Recorder(socket.timeout(), "<html>ok</html>")
        self.assertEqual(self.fetch(rec, timeout=7), "<html>ok</html>")
        self.assertEqual([t for _, t in rec.calls], [7, 7])

    def test_gives_up_after_three_timeouts(self):
        rec = Recorder(socket.timeout(), socket.timeout(), socket.timeout(), "never reached")
        with self.assertRaises(enrich.FetchError) as ctx:
            self.fetch(rec, timeout=10)
        self.assertEqual(len(rec.calls), 3)
        self.assertEqual(self.sleeps, [2, 2])  # waits between tries, not after the last
        self.assertEqual(str(ctx.exception), "site unreachable: timed out after 10s")

    def test_timeout_wrapped_in_urlerror(self):
        rec = Recorder(*[urllib.error.URLError(socket.timeout("timed out"))] * 3)
        with self.assertRaises(enrich.FetchError) as ctx:
            self.fetch(rec, timeout=10)
        self.assertIn("timed out after 10s", str(ctx.exception))

    def test_builtin_timeouterror(self):
        rec = Recorder(TimeoutError(), TimeoutError(), TimeoutError())
        with self.assertRaises(enrich.FetchError):
            self.fetch(rec)
        self.assertEqual(len(rec.calls), 3)

    def test_dns_failure_reason_is_kept(self):
        err = urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided"))
        with self.assertRaises(enrich.FetchError) as ctx:
            self.fetch(Recorder(err, err, err))
        self.assertIn("nodename nor servname", str(ctx.exception))

    def test_5xx_is_retried(self):
        rec = Recorder(http_error(503), "<html>ok</html>")
        self.assertEqual(self.fetch(rec), "<html>ok</html>")
        self.assertEqual(len(rec.calls), 2)

    def test_4xx_is_not_retried(self):
        rec = Recorder(http_error(404), "never reached")
        with self.assertRaises(enrich.FetchError) as ctx:
            self.fetch(rec)
        self.assertEqual(len(rec.calls), 1)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(str(ctx.exception), "site unreachable: HTTP 404")


class ParseSummaryTests(unittest.TestCase):
    def test_clean_json(self):
        s, fail = enrich.parse_summary(GOOD_REPLY)
        self.assertEqual(fail, "")
        self.assertEqual(s["size_hint"], "11_50")
        self.assertEqual(s["services"], ["AC repair", "heating", "duct cleaning"])

    def test_code_fence_and_prose_around_json(self):
        s, fail = enrich.parse_summary("Sure, here you go:\n```json\n" + GOOD_REPLY + "\n```\nLet me know!")
        self.assertEqual(fail, "")
        self.assertEqual(s["location"], "Auburn, AL")

    def test_not_json(self):
        self.assertEqual(enrich.parse_summary("I could not read that page."),
                         (None, "could not parse Claude output"))

    def test_truncated_json(self):
        self.assertEqual(enrich.parse_summary('{"what_they_do": "plumbing", "size_hint": "1_1'),
                         (None, "could not parse Claude output"))

    def test_empty_reply(self):
        self.assertEqual(enrich.parse_summary(""), (None, "could not parse Claude output"))

    def test_bad_size_hint_becomes_unknown(self):
        s, _ = enrich.parse_summary('{"size_hint": "about 20 people", "summary": "x"}')
        self.assertEqual(s["size_hint"], "unknown")

    def test_missing_and_wrong_type_fields(self):
        s, _ = enrich.parse_summary('{"what_they_do": null, "services": "AC repair", "summary": 5}')
        self.assertEqual(s["what_they_do"], "")
        self.assertEqual(s["services"], [])
        self.assertEqual(s["summary"], "5")

    def test_caps_services_and_summary_length(self):
        s, _ = enrich.parse_summary('{"services": ["a","b","c","d","e","f","g","h"], "summary": "%s"}' % ("x" * 900))
        self.assertEqual(len(s["services"]), 6)
        self.assertEqual(len(s["summary"]), 400)


class PageTextTests(unittest.TestCase):
    def test_strips_tags_scripts_and_decodes_entities(self):
        text, fail = enrich.extract_page_text(PAGE)
        self.assertEqual(fail, "")
        self.assertTrue(text.startswith("Carter Heating & Air\nHVAC repair in Auburn, AL\n"))
        self.assertIn("We're a family HVAC shop", text)
        self.assertNotIn("var x", text)

    def test_thin_page_fails(self):
        self.assertEqual(enrich.extract_page_text("<html><body>Coming soon</body></html>"),
                         ("", "site has too little readable text"))


class PickWebsiteTests(unittest.TestCase):
    def test_company_domain(self):
        self.assertEqual(enrich.pick_website("sam@CarterHVAC.com"), ("https://carterhvac.com", False, ""))

    def test_personal_domain(self):
        url, personal, fail = enrich.pick_website("sam@gmail.com")
        self.assertEqual((url, personal), ("", True))
        self.assertIn("personal email", fail)


class ScoringTests(unittest.TestCase):
    """Scores match what the n8n workflow produced for the same test leads."""

    def test_tom_site_unreachable_scores_55(self):
        score, _ = enrich.score_lead(TOM, None, False)
        self.assertEqual(score, 55)

    def test_pat_site_unreachable_scores_25(self):
        score, _ = enrich.score_lead(PAT, None, False)
        self.assertEqual(score, 25)

    def test_enriched_mid_size_company(self):
        summary, _ = enrich.parse_summary(GOOD_REPLY)
        score, why = enrich.score_lead(TOM, summary, False)
        self.assertEqual(score, 100)  # 20+20+25+10+5+10+10 = 100, clamped
        self.assertIn("+25 size 11-50", why)

    def test_personal_email_penalty_and_floor(self):
        score, why = enrich.score_lead({"message": ""}, None, True)
        self.assertEqual(score, 10)
        self.assertIn("-10 personal email", why)


class EnrichLeadTests(unittest.TestCase):
    def test_happy_path(self):
        r = enrich.enrich_lead(PAT, fetch=lambda url: PAGE, summarize=lambda text: GOOD_REPLY)
        self.assertEqual(r["enrichment_status"], "done")
        self.assertEqual(r["company_size_hint"], "11_50")
        self.assertTrue(r["company_summary"].endswith("(Auburn, AL)"))
        self.assertEqual(r["lead_score"], 70)  # 20+20+25+5

    def test_fetch_timeout_still_scores(self):
        def dead(url):
            raise enrich.FetchError("site unreachable: timed out after 10s")
        r = enrich.enrich_lead(PAT, fetch=dead, summarize=lambda t: self.fail("should not call Claude"))
        self.assertEqual(r["enrichment_status"], "failed")
        self.assertEqual(r["fail_reason"], "site unreachable: timed out after 10s")
        self.assertEqual(r["lead_score"], 25)

    def test_claude_timeout_still_scores(self):
        def slow(text):
            raise socket.timeout("timed out")
        r = enrich.enrich_lead(PAT, fetch=lambda url: PAGE, summarize=slow)
        self.assertEqual((r["enrichment_status"], r["fail_reason"]), ("failed", "Claude call failed"))

    def test_claude_garbage_still_scores(self):
        r = enrich.enrich_lead(PAT, fetch=lambda url: PAGE, summarize=lambda t: "no idea")
        self.assertEqual(r["fail_reason"], "could not parse Claude output")
        self.assertEqual(r["lead_score"], 25)

    def test_personal_email_skips_fetch(self):
        lead = dict(PAT, email="pat@gmail.com")
        r = enrich.enrich_lead(lead, fetch=lambda url: self.fail("should not fetch"))
        self.assertEqual(r["lead_score"], 15)
        self.assertIn("personal email", r["fail_reason"])


if __name__ == "__main__":
    unittest.main()
