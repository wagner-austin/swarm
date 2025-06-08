import pytest

from bot.core.validation import looks_like_web_url


# explicit types – appease mypy’s “no-untyped-def”
@pytest.mark.parametrize(
    "candidate,expect",
    [
        ("https://example.com", True),
        ("http://localhost", True),
        ("example.com", True),
        ("ftp://example.com", False),
        ("qwasd", False),
        ("", False),
    ],
)
def test_looks_like_web_url(candidate: str, expect: bool) -> None:
    assert looks_like_web_url(candidate) is expect
