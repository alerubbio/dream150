"""Load and validate an ICP (ideal customer profile) config.

The whole point of dream150 is that targeting lives in *your* config, not in
the code. This module turns a YAML file into a validated `ICP` object with
sensible generic defaults, so a missing field never crashes a run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import yaml

from .client import NTEE_MAJOR_GROUPS


class ConfigError(ValueError):
    """The ICP config is malformed or self-contradictory."""


# Generic, neutral defaults. These are a starting point, not anyone's real ICP.
DEFAULT_WEIGHTS = {"revenue_fit": 0.5, "recency": 0.25, "financial_health": 0.25}


@dataclass
class ICP:
    name: str = "Unnamed ICP"

    # search (server-side narrowing)
    query: Optional[str] = None
    state: Optional[str] = None
    ntee_major: Optional[int] = None
    subsection_code: Optional[int] = 3  # 501(c)(3)

    # filters (client-side)
    ntee_prefixes: List[str] = field(default_factory=list)
    min_revenue: Optional[int] = None
    max_revenue: Optional[int] = None

    # scoring
    reference_year: int = 2024
    revenue_sweet_spot: Optional[Tuple[int, int]] = None
    recency_full_credit_years: int = 2
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    # output
    top_n: int = 150

    # suppression
    suppression_file: Optional[str] = None

    def describe(self) -> str:
        parts = [f'ICP "{self.name}"']
        if self.query:
            parts.append(f'query="{self.query}"')
        if self.state:
            parts.append(f"state={self.state}")
        if self.ntee_major:
            parts.append(f"ntee_major={self.ntee_major} ({NTEE_MAJOR_GROUPS.get(self.ntee_major)})")
        if self.ntee_prefixes:
            parts.append(f"ntee_prefixes={self.ntee_prefixes}")
        rev = []
        if self.min_revenue is not None:
            rev.append(f">=${self.min_revenue:,}")
        if self.max_revenue is not None:
            rev.append(f"<=${self.max_revenue:,}")
        if rev:
            parts.append("revenue " + " ".join(rev))
        return "  ".join(parts)


def _as_int(value, field_name: str) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{field_name} must be an integer, got {value!r}")


def load_icp(path: str) -> ICP:
    """Read and validate an ICP YAML file into an `ICP`."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must be a YAML mapping at the top level")
    return icp_from_dict(data)


def icp_from_dict(data: dict) -> ICP:
    search = data.get("search") or {}
    filters = data.get("filters") or {}
    scoring = data.get("scoring") or {}
    output = data.get("output") or {}
    suppression = data.get("suppression") or {}

    ntee_major = _as_int(search.get("ntee_major"), "search.ntee_major")
    if ntee_major is not None and ntee_major not in NTEE_MAJOR_GROUPS:
        raise ConfigError(f"search.ntee_major must be 1-10, got {ntee_major}")

    # Omitted subsection_code defaults to 501(c)(3); an explicit null skips it.
    subsection_code = _as_int(search.get("subsection_code", 3), "search.subsection_code")

    prefixes = filters.get("ntee_prefixes") or []
    if isinstance(prefixes, str):
        prefixes = [prefixes]
    prefixes = [str(p).upper() for p in prefixes]

    min_rev = _as_int(filters.get("min_revenue"), "filters.min_revenue")
    max_rev = _as_int(filters.get("max_revenue"), "filters.max_revenue")
    if min_rev is not None and max_rev is not None and min_rev > max_rev:
        raise ConfigError(f"min_revenue ({min_rev}) exceeds max_revenue ({max_rev})")

    sweet = scoring.get("revenue_sweet_spot")
    sweet_tuple: Optional[Tuple[int, int]] = None
    if sweet is not None:
        if not isinstance(sweet, (list, tuple)) or len(sweet) != 2:
            raise ConfigError("scoring.revenue_sweet_spot must be a [low, high] pair")
        lo, hi = int(sweet[0]), int(sweet[1])
        if lo > hi:
            raise ConfigError(f"revenue_sweet_spot low ({lo}) exceeds high ({hi})")
        sweet_tuple = (lo, hi)

    weights = dict(DEFAULT_WEIGHTS)
    for k, v in (scoring.get("weights") or {}).items():
        if k not in DEFAULT_WEIGHTS:
            raise ConfigError(
                f"unknown scoring weight {k!r}; valid keys: {sorted(DEFAULT_WEIGHTS)}"
            )
        weights[k] = float(v)
    if sum(weights.values()) <= 0:
        raise ConfigError("scoring weights must sum to a positive number")

    top_n = _as_int(output.get("top_n"), "output.top_n") or 150
    if top_n <= 0:
        raise ConfigError(f"output.top_n must be positive, got {top_n}")

    return ICP(
        name=str(data.get("name") or "Unnamed ICP"),
        query=search.get("query") or None,
        state=(search.get("state") or None),
        ntee_major=ntee_major,
        subsection_code=subsection_code,
        ntee_prefixes=prefixes,
        min_revenue=min_rev,
        max_revenue=max_rev,
        reference_year=_as_int(scoring.get("reference_year"), "scoring.reference_year") or 2024,
        revenue_sweet_spot=sweet_tuple,
        recency_full_credit_years=_as_int(
            scoring.get("recency_full_credit_years"), "scoring.recency_full_credit_years"
        )
        or 2,
        weights=weights,
        top_n=top_n,
        suppression_file=suppression.get("file") or None,
    )
