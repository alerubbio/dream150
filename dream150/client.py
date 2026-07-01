"""Client for the ProPublica Nonprofit Explorer API (free, no key required).

API docs: https://projects.propublica.org/nonprofits/api

Two endpoints matter here:
  - /search.json           paginated org search (25 hits/page); returns light
                           records (ein, name, city, state, ntee_code) but NO
                           financials.
  - /organizations/{ein}.json   full org profile plus every filing, including
                           total revenue and total functional expenses.

Because search omits money, ranking on revenue means one detail fetch per
candidate. The client is therefore polite by default: a minimum interval
between requests plus exponential backoff on 429/5xx, so a few-thousand-EIN
run does not hammer (or get throttled by) ProPublica.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterator, List, Optional

API_BASE = "https://projects.propublica.org/nonprofits/api/v2"
USER_AGENT = "dream150/0.1 (+https://github.com/alerubbio/dream150)"

# ProPublica's ntee[id] filter uses coarse major groups, not letter codes.
NTEE_MAJOR_GROUPS = {
    1: "Arts, Culture & Humanities",
    2: "Education",
    3: "Environment and Animals",
    4: "Health",
    5: "Human Services",
    6: "International, Foreign Affairs",
    7: "Public, Societal Benefit",
    8: "Religion Related",
    9: "Mutual/Membership Benefit",
    10: "Unknown, Unclassified",
}


class ProPublicaError(RuntimeError):
    """Base error for any failed ProPublica interaction."""


class NotFound(ProPublicaError):
    """The requested organization (EIN) does not exist."""


class RateLimited(ProPublicaError):
    """Persisted 429s after exhausting retries."""


def _to_int(value: Any) -> Optional[int]:
    """Coerce API numerics (which arrive as int, float, str, or None) to int."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


@dataclass
class SearchHit:
    """A single light record from the search endpoint (no financials)."""

    ein: int
    name: str
    city: Optional[str]
    state: Optional[str]
    ntee_code: Optional[str]
    score: Optional[float]
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, d: dict) -> "SearchHit":
        return cls(
            ein=_to_int(d.get("ein")),
            name=(d.get("name") or "").strip(),
            city=d.get("city"),
            state=d.get("state"),
            ntee_code=d.get("ntee_code") or d.get("raw_ntee_code"),
            score=d.get("score"),
            raw=d,
        )


@dataclass
class Filing:
    """One year's return for an org, from filings_with_data."""

    tax_year: Optional[int]
    total_revenue: Optional[int]
    total_functional_expenses: Optional[int]
    form_type: Optional[int]
    pdf_url: Optional[str]
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, d: dict) -> "Filing":
        return cls(
            tax_year=_to_int(d.get("tax_prd_yr")),
            total_revenue=_to_int(d.get("totrevenue")),
            total_functional_expenses=_to_int(d.get("totfuncexpns")),
            form_type=_to_int(d.get("formtype")),
            pdf_url=d.get("pdf_url"),
            raw=d,
        )


@dataclass
class Organization:
    """Full org profile from the organization endpoint."""

    ein: int
    name: str
    city: Optional[str]
    state: Optional[str]
    ntee_code: Optional[str]
    subsection_code: Optional[int]
    revenue_amount: Optional[int]  # from the IRS Business Master File
    filings: List[Filing]
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, payload: dict) -> "Organization":
        org = payload.get("organization", {}) or {}
        filings = [Filing.from_api(f) for f in (payload.get("filings_with_data") or [])]
        # Newest filing first, so latest_filing is unambiguous.
        filings.sort(key=lambda f: (f.tax_year is not None, f.tax_year or 0), reverse=True)
        return cls(
            ein=_to_int(org.get("ein")),
            name=(org.get("name") or "").strip(),
            city=org.get("city"),
            state=org.get("state"),
            ntee_code=org.get("ntee_code"),
            subsection_code=_to_int(org.get("subsection_code")),
            revenue_amount=_to_int(org.get("revenue_amount")),
            filings=filings,
            raw=payload,
        )

    @property
    def latest_filing(self) -> Optional[Filing]:
        return self.filings[0] if self.filings else None

    @property
    def latest_revenue(self) -> Optional[int]:
        """Prefer the most recent filing's total revenue; fall back to BMF."""
        for f in self.filings:
            if f.total_revenue is not None:
                return f.total_revenue
        return self.revenue_amount

    @property
    def latest_expenses(self) -> Optional[int]:
        for f in self.filings:
            if f.total_functional_expenses is not None:
                return f.total_functional_expenses
        return None

    @property
    def latest_tax_year(self) -> Optional[int]:
        f = self.latest_filing
        return f.tax_year if f else None

    @property
    def profile_url(self) -> str:
        return f"https://projects.propublica.org/nonprofits/organizations/{self.ein}"


@dataclass
class SearchPage:
    total_results: int
    num_pages: int
    cur_page: int
    hits: List[SearchHit]


class ProPublicaClient:
    """Thin, polite HTTP client over the Nonprofit Explorer API.

    Network access is isolated in `_get_json`, which tests monkeypatch to serve
    recorded fixtures, so the rest of the package runs fully offline in CI.
    """

    def __init__(
        self,
        base_url: str = API_BASE,
        min_interval: float = 0.2,
        max_retries: int = 4,
        timeout: float = 30.0,
        backoff_base: float = 1.5,
    ):
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.backoff_base = backoff_base
        self._last_request = 0.0

    # -- HTTP layer (the only thing that touches the network) --------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        wait = self.min_interval - elapsed
        if wait > 0:
            time.sleep(wait)

    def _get_json(self, url: str) -> dict:
        """GET a URL and return parsed JSON, with retry/backoff. Overridable."""
        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self._last_request = time.monotonic()
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                self._last_request = time.monotonic()
                if e.code == 404:
                    raise NotFound(f"Not found: {url}") from e
                if e.code == 429 or 500 <= e.code < 600:
                    last_err = e
                    if attempt < self.max_retries:
                        time.sleep(self.backoff_base ** attempt)
                        continue
                    if e.code == 429:
                        raise RateLimited(f"Rate limited after {attempt + 1} tries: {url}") from e
                raise ProPublicaError(f"HTTP {e.code} for {url}") from e
            except urllib.error.URLError as e:
                self._last_request = time.monotonic()
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base ** attempt)
                    continue
                raise ProPublicaError(f"Network error for {url}: {e}") from e
        raise ProPublicaError(f"Exhausted retries for {url}: {last_err}")

    # -- Endpoints ---------------------------------------------------------

    def search(
        self,
        query: Optional[str] = None,
        state: Optional[str] = None,
        ntee_major: Optional[int] = None,
        subsection_code: Optional[int] = None,
        page: int = 0,
    ) -> SearchPage:
        """One page (25 hits) of the search endpoint."""
        params = {}
        if query:
            params["q"] = query
        if state:
            params["state[id]"] = state
        if ntee_major is not None:
            if ntee_major not in NTEE_MAJOR_GROUPS:
                raise ValueError(f"ntee_major must be 1-10, got {ntee_major}")
            params["ntee[id]"] = ntee_major
        if subsection_code is not None:
            params["c_code[id]"] = subsection_code
        params["page"] = page
        url = f"{self.base_url}/search.json?" + urllib.parse.urlencode(params)
        data = self._get_json(url)
        return SearchPage(
            total_results=_to_int(data.get("total_results")) or 0,
            num_pages=_to_int(data.get("num_pages")) or 0,
            cur_page=_to_int(data.get("cur_page")) or page,
            hits=[SearchHit.from_api(o) for o in data.get("organizations", [])],
        )

    def search_all(
        self,
        query: Optional[str] = None,
        state: Optional[str] = None,
        ntee_major: Optional[int] = None,
        subsection_code: Optional[int] = None,
        max_hits: Optional[int] = None,
    ) -> Iterator[SearchHit]:
        """Yield every hit across all pages, stopping at max_hits if given.

        ProPublica caps total_results at 10,000; narrow with state/ntee/query
        if you hit that ceiling.
        """
        first = self.search(query, state, ntee_major, subsection_code, page=0)
        yielded = 0
        for hit in first.hits:
            yield hit
            yielded += 1
            if max_hits and yielded >= max_hits:
                return
        for page in range(1, first.num_pages):
            for hit in self.search(query, state, ntee_major, subsection_code, page=page).hits:
                yield hit
                yielded += 1
                if max_hits and yielded >= max_hits:
                    return

    def organization(self, ein: int) -> Organization:
        """Full profile + filings for one EIN."""
        ein_int = _to_int(ein)
        if ein_int is None:
            raise ValueError(f"Invalid EIN: {ein!r}")
        url = f"{self.base_url}/organizations/{ein_int}.json"
        return Organization.from_api(self._get_json(url))
