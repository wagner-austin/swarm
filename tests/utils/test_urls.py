# tests/utils/test_urls.py
import pytest
from pytest import MonkeyPatch
from bot.utils.urls import validate_and_normalise_web_url


@pytest.mark.parametrize(
    "raw,expect",
    [
        ("example.com", "https://example.com"),
        ("http://localhost:8080", "http://localhost:8080"),
        ("file:///C:/tmp/index.html", "file:///C:/tmp/index.html"),
    ],
)
def test_good_urls(raw: str, expect: str) -> None:
    assert validate_and_normalise_web_url(raw) == expect


# ensure allow‑list blocks disallowed hosts
def test_disallowed_host(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("bot.core.settings.settings.allowed_hosts", ["example.com"])
    with pytest.raises(ValueError):
        validate_and_normalise_web_url("https://not‑allowed.org")


@pytest.mark.parametrize("raw", ["", "notaurl", "ftp://foo", "http://no_dot_host"])
def test_bad_urls(raw: str) -> None:
    with pytest.raises(ValueError):
        validate_and_normalise_web_url(raw)
