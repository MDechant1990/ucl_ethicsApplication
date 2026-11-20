"""The no-submit guard: risky URLs/buttons are blocked, ordinary drafting is allowed."""
import pytest

from filler.browser import FORBIDDEN, SIGNATURE_PAGE, _field_names, _words


@pytest.mark.parametrize("url", [
    "https://ethics.ucl.ac.uk/Project/Submit/123",
    "https://ethics.ucl.ac.uk/Project/SubmitProject",
    "https://ethics.ucl.ac.uk/Signatures/Sign/5",
    "https://ethics.ucl.ac.uk/Project/RequestSignature",
    "https://ethics.ucl.ac.uk/Project/LockForm/1",
    "https://ethics.ucl.ac.uk/Project/DeleteProject/1",
])
def test_risky_urls_blocked(url):
    assert FORBIDDEN.search(_words(url))


@pytest.mark.parametrize("url", [
    "https://ethics.ucl.ac.uk/Project/Create",
    "https://ethics.ucl.ac.uk/Project/SavePage/1605/7000",
    "https://ethics.ucl.ac.uk/Project/Page/1605/7000",
])
def test_drafting_urls_allowed(url):
    assert not FORBIDDEN.search(_words(url)) and SIGNATURE_PAGE not in url


def test_user_text_never_triggers_but_field_names_do():
    body = "Title=TEST+delete+me&Answer=co-design+workshop+signage&__RequestVerificationToken=x"
    assert not FORBIDDEN.search(_words(_field_names(body)))
    assert FORBIDDEN.search(_words(_field_names("IsSigned=true&x=1")))


@pytest.mark.parametrize("label", ["Submit", "Sign", "Request signatures", "Lock form", "I accept the declaration"])
def test_risky_buttons_blocked(label):
    assert FORBIDDEN.search(_words(label))


@pytest.mark.parametrize("label", ["Next page", "Save", "Create", "Previous page"])
def test_normal_buttons_allowed(label):
    assert not FORBIDDEN.search(_words(label))
