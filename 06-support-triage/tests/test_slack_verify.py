from app.slack_verify import sign, verify

SECRET = "8f742231b10e8888abcd99yyyzzz85a5"
# Worked example from Slack's docs.
TS = "1531420618"
BODY = ("token=xyzz0WbapA4vBCDEFasx0q6G&team_id=T1DC2JH3J&team_domain=testteamnow&channel_id=G8PSS9T3V"
        "&channel_name=foobar&user_id=U2CERLKJA&user_name=roadrunner&command=%2Fwebhook-collect&text="
        "&response_url=https%3A%2F%2Fhooks.slack.com%2Fcommands%2FT1DC2JH3J%2F397700885554%2F96rGlfmibIGlgcZRskXaIFfN"
        "&trigger_id=398738663015.47445629121.803a0bc887a14d10d2c447fce8b6703c")
EXPECTED = "v0=a2114d57b48eac39b9ad189dd8316235a7b4a8d21a10bd27519666489c69b503"


def test_matches_slack_docs_example():
    assert sign(SECRET, TS, BODY) == EXPECTED
    assert verify(SECRET, TS, EXPECTED, BODY, now=float(TS) + 10) == (True, "ok")


def test_rejects_replay_and_tamper_and_missing_secret():
    assert verify(SECRET, TS, EXPECTED, BODY, now=float(TS) + 301)[0] is False
    assert verify(SECRET, TS, EXPECTED, BODY + "&x=1", now=float(TS))[1] == "signature mismatch"
    assert verify("", TS, EXPECTED, BODY, now=float(TS))[1] == "signing secret not configured"
    assert verify(SECRET, "abc", EXPECTED, BODY)[1] == "bad timestamp"
