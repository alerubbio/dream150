"""Fit scoring for candidate organizations.

This is a SAMPLE default model, deliberately generic. It scores only on fields
the free ProPublica API exposes:

  - revenue_fit       how well the org's revenue sits inside your target band,
                      with full credit inside an optional "sweet spot".
  - recency           how fresh the latest available filing is (a proxy for the
                      org being active and reachable).
  - financial_health  whether the org reports both revenue and expenses and runs
                      roughly in balance (a light, defensible sanity signal).

The weights live in your ICP config, so you can retune or zero-out any
component without touching this code. Deeper signals (e.g. the Part IX
program/management/fundraising expense split) are NOT in ProPublica; they live
in the raw IRS 990 e-file XML and are the subject of a planned follow-up that
plugs into this same interface.

Every component returns a value in [0, 1]; the total is the weighted average,
also in [0, 1], scaled to 0-100 for readability.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .client import Organization
from .config import ICP


@dataclass
class ScoredOrg:
    org: Organization
    total: float                 # 0-100
    components: Dict[str, float]  # each 0-1, pre-weighting

    def as_row(self) -> dict:
        f = self.org.latest_filing
        return {
            "ein": self.org.ein,
            "name": self.org.name,
            "city": self.org.city or "",
            "state": self.org.state or "",
            "ntee_code": self.org.ntee_code or "",
            "latest_revenue": self.org.latest_revenue if self.org.latest_revenue is not None else "",
            "latest_expenses": self.org.latest_expenses if self.org.latest_expenses is not None else "",
            "latest_tax_year": self.org.latest_tax_year if self.org.latest_tax_year is not None else "",
            "score": round(self.total, 2),
            "revenue_fit": round(self.components.get("revenue_fit", 0.0), 3),
            "recency": round(self.components.get("recency", 0.0), 3),
            "financial_health": round(self.components.get("financial_health", 0.0), 3),
            "profile_url": self.org.profile_url,
            "pdf_url": (f.pdf_url if f else "") or "",
        }


def _revenue_fit(revenue: Optional[int], icp: ICP) -> float:
    """1.0 inside the sweet spot, tapering to 0 at the min/max bounds."""
    if revenue is None:
        return 0.0
    lo = icp.min_revenue
    hi = icp.max_revenue
    # Hard bounds: outside the allowed band scores 0 (though the pipeline
    # usually filters these out before scoring).
    if lo is not None and revenue < lo:
        return 0.0
    if hi is not None and revenue > hi:
        return 0.0

    sweet = icp.revenue_sweet_spot
    if not sweet:
        return 1.0  # no sweet spot defined: any in-band revenue is full credit
    s_lo, s_hi = sweet
    if s_lo <= revenue <= s_hi:
        return 1.0
    # Below the sweet spot: taper from the lower bound up to s_lo.
    if revenue < s_lo:
        floor = lo if lo is not None else 0
        span = s_lo - floor
        return _clamp((revenue - floor) / span) if span > 0 else 1.0
    # Above the sweet spot: taper from s_hi down to the upper bound.
    ceil = hi if hi is not None else s_hi * 4  # generous default taper width
    span = ceil - s_hi
    return _clamp((ceil - revenue) / span) if span > 0 else 1.0


def _recency(tax_year: Optional[int], icp: ICP) -> float:
    """Full credit within `recency_full_credit_years` of the reference year,
    then a linear decay to 0 over a further span of equal width."""
    if tax_year is None:
        return 0.0
    age = icp.reference_year - tax_year
    if age <= icp.recency_full_credit_years:
        return 1.0
    decay_span = max(icp.recency_full_credit_years, 1)
    overshoot = age - icp.recency_full_credit_years
    return _clamp(1.0 - overshoot / (decay_span * 2))


def _financial_health(org: Organization) -> float:
    """Reward orgs that report both revenue and expenses and run near balance.

    ratio = expenses / revenue. Healthy operating range ~0.7-1.1 gets full
    credit; far outside that (barely spending, or spending far beyond revenue)
    tapers down. Missing either figure scores 0.
    """
    rev = org.latest_revenue
    exp = org.latest_expenses
    if not rev or rev <= 0 or exp is None or exp < 0:
        return 0.0
    ratio = exp / rev
    if 0.7 <= ratio <= 1.1:
        return 1.0
    if ratio < 0.7:
        return _clamp(ratio / 0.7)          # 0 spend -> 0; 0.7 -> 1.0
    return _clamp(1.0 - (ratio - 1.1) / 0.9)  # 1.1 -> 1.0; 2.0 -> 0


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def score_org(org: Organization, icp: ICP) -> ScoredOrg:
    components = {
        "revenue_fit": _revenue_fit(org.latest_revenue, icp),
        "recency": _recency(org.latest_tax_year, icp),
        "financial_health": _financial_health(org),
    }
    weight_sum = sum(icp.weights.values()) or 1.0
    weighted = sum(components[k] * icp.weights.get(k, 0.0) for k in components)
    total = 100.0 * weighted / weight_sum
    return ScoredOrg(org=org, total=total, components=components)
