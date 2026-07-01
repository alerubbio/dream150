"""Shared test helpers: an offline ProPublica client backed by recorded fixtures.

No test touches the network. `FixtureClient` overrides `_get_json` to serve the
JSON captured under tests/fixtures/, so the client, pipeline, and scoring all
run deterministically in CI.
"""
import json
import os
from urllib.parse import parse_qs, urlparse

import pytest

from dream150.client import ProPublicaClient

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return json.load(f)


class FixtureClient(ProPublicaClient):
    """ProPublicaClient with the network stubbed out by recorded fixtures."""

    def __init__(self, **kw):
        # No throttling in tests.
        super().__init__(min_interval=0.0, **kw)
        self.calls = []
        # EIN -> fixture file
        self._orgs = {
            237111782: "org_yolo_foodbank.json",
            363673599: "org_feeding_america.json",
        }

    def _get_json(self, url):
        self.calls.append(url)
        parsed = urlparse(url)
        if "/search.json" in parsed.path:
            qs = parse_qs(parsed.query)
            page = int(qs.get("page", ["0"])[0])
            data = _load("search_foodbank_ca.json")
            # The fixture is a single page; emulate a one-page result set.
            if page == 0:
                data = dict(data)
                data["num_pages"] = 1
                return data
            return {"organizations": [], "num_pages": 1, "cur_page": page, "total_results": data.get("total_results", 0)}
        if "/organizations/" in parsed.path:
            ein = int(parsed.path.split("/")[-1].replace(".json", ""))
            fixture = self._orgs.get(ein)
            if not fixture:
                from dream150.client import NotFound
                raise NotFound(f"no fixture for EIN {ein}")
            return _load(fixture)
        raise AssertionError(f"unexpected URL in test: {url}")


@pytest.fixture
def fixture_client():
    return FixtureClient()
