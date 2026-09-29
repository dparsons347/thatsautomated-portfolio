import pytest

from app.graph import decide, tidy
from tests.fakes import cls


@pytest.mark.parametrize("category,route", [
    ("sales", "draft"), ("support", "draft"), ("vendor", "archive"), ("spam", "archive"),
    ("existing_client", "person"), ("unclear", "person"),
])
def test_confident_new_message_routes_by_category(category, route):
    r, needs_human, _ = decide(cls(category, 0.95), is_reply=False, prior_category=None, threshold=0.75)
    assert r == route
    assert needs_human == (route == "person")


def test_threshold_is_inclusive():
    assert decide(cls("sales", 0.75), is_reply=False, prior_category=None, threshold=0.75)[0] == "draft"
    assert decide(cls("sales", 0.74), is_reply=False, prior_category=None, threshold=0.75)[0] == "person"


def test_low_confidence_spam_is_not_silently_archived():
    r, needs_human, reasons = decide(cls("spam", 0.5), is_reply=False, prior_category=None, threshold=0.75)
    assert (r, needs_human) == ("person", True)
    assert "below" in reasons[0]


def test_negative_reply_goes_to_person_even_when_confident():
    r, _, reasons = decide(cls("sales", 0.99, sentiment="negative"), is_reply=True,
                           prior_category="sales", threshold=0.75)
    assert r == "person"
    assert reasons == ["Negative reply on an open thread"]


def test_negative_first_message_is_not_gated_on_tone_alone():
    assert decide(cls("support", 0.9, sentiment="negative"), is_reply=False,
                  prior_category=None, threshold=0.75)[0] == "draft"


def test_all_reasons_are_listed():
    _, _, reasons = decide(cls("unclear", 0.3, sentiment="negative"), is_reply=True,
                           prior_category="sales", threshold=0.75)
    assert len(reasons) == 4


def test_tidy_removes_dashes():
    assert tidy("Thanks — we can help – soon") == "Thanks, we can help, soon"
