import urllib.error

import pytest

from dream150 import client as client_mod
from dream150.client import NotFound, Organization, ProPublicaClient, _to_int


def test_to_int_coercion():
    assert _to_int(5) == 5
    assert _to_int("23338085") == 23338085
    assert _to_int(4916912461.0) == 4916912461
    assert _to_int(None) is None
    assert _to_int("") is None
    assert _to_int("not a number") is None


def test_search_parsing(fixture_client):
    page = fixture_client.search(query="food bank", state="CA")
    assert page.total_results == 65
    assert len(page.hits) == 25
    first = page.hits[0]
    assert first.ein == 237111782
    assert first.name == "Yolo Food Bank"
    assert first.state == "CA"
    assert first.ntee_code == "K31Z"


def test_search_all_paginates_and_respects_max(fixture_client):
    hits = list(fixture_client.search_all(query="food bank", state="CA", max_hits=3))
    assert len(hits) == 3
    assert hits[0].ein == 237111782


def test_organization_parsing_and_latest(fixture_client):
    org = fixture_client.organization(237111782)
    assert isinstance(org, Organization)
    assert org.ein == 237111782
    assert org.name == "Yolo Food Bank"
    assert org.ntee_code == "K31Z"
    # Latest filing is TY2023 with these financials.
    assert org.latest_tax_year == 2023
    assert org.latest_revenue == 23338085
    assert org.latest_expenses == 23350748
    assert org.profile_url.endswith("/237111782")


def test_filings_sorted_newest_first(fixture_client):
    org = fixture_client.organization(363673599)
    years = [f.tax_year for f in org.filings if f.tax_year is not None]
    assert years == sorted(years, reverse=True)
    assert org.latest_revenue == 4916912461


def test_invalid_ein_raises(fixture_client):
    with pytest.raises(ValueError):
        fixture_client.organization("not-an-ein")


def test_ntee_major_validation(fixture_client):
    with pytest.raises(ValueError):
        fixture_client.search(ntee_major=99)


def test_missing_org_raises_notfound(fixture_client):
    with pytest.raises(NotFound):
        fixture_client.organization(999999999)


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def test_retry_then_success(monkeypatch):
    """429 twice, then a 200 — the client should retry and return JSON."""
    monkeypatch.setattr(client_mod.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
        return _FakeResp(b'{"total_results": 1, "num_pages": 1, "organizations": []}')

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", fake_urlopen)
    c = ProPublicaClient(min_interval=0.0, backoff_base=1.0)
    page = c.search(query="x")
    assert calls["n"] == 3
    assert page.total_results == 1


def test_retry_exhausted_raises_ratelimited(monkeypatch):
    monkeypatch.setattr(client_mod.time, "sleep", lambda *_: None)

    def always_429(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", always_429)
    c = ProPublicaClient(min_interval=0.0, max_retries=2, backoff_base=1.0)
    with pytest.raises(client_mod.RateLimited):
        c.search(query="x")
