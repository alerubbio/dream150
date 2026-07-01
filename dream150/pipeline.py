"""Orchestrate the run: search -> filter -> enrich -> score -> rank.

The expensive step is enrichment: search omits financials, so every surviving
candidate costs one organization-detail fetch. The pipeline narrows as early
and cheaply as it can (server-side search filters, then a client-side NTEE
prefix filter on the free search fields) before spending any detail fetches.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .client import Organization, ProPublicaClient, SearchHit
from .config import ICP
from .scoring import ScoredOrg, score_org
from .suppression import SuppressionList

# Callback signature for progress reporting: (stage, current, total, message).
ProgressFn = Callable[[str, int, Optional[int], str], None]


def _noop(stage: str, current: int, total: Optional[int], message: str) -> None:
    pass


@dataclass
class RunStats:
    search_hits: int = 0
    after_prefix_filter: int = 0
    enriched: int = 0
    after_revenue_filter: int = 0
    suppressed: int = 0
    scored: int = 0
    errors: int = 0
    notes: List[str] = field(default_factory=list)


def _matches_prefix(ntee_code: Optional[str], prefixes: List[str]) -> bool:
    if not prefixes:
        return True
    if not ntee_code:
        return False
    code = ntee_code.upper()
    return any(code.startswith(p) for p in prefixes)


def _passes_revenue(org: Organization, icp: ICP) -> bool:
    rev = org.latest_revenue
    if rev is None:
        return False  # can't rank an org with no revenue figure
    if icp.min_revenue is not None and rev < icp.min_revenue:
        return False
    if icp.max_revenue is not None and rev > icp.max_revenue:
        return False
    return True


def run(
    icp: ICP,
    client: Optional[ProPublicaClient] = None,
    suppression: Optional[SuppressionList] = None,
    max_candidates: Optional[int] = None,
    progress: ProgressFn = _noop,
) -> tuple[List[ScoredOrg], RunStats]:
    """Execute the pipeline and return (ranked ScoredOrgs, stats).

    `max_candidates` caps how many search hits (post prefix-filter) get an
    enrichment fetch, so a huge match set can't silently balloon into thousands
    of requests. When the cap bites, it is recorded in stats.notes.
    """
    client = client or ProPublicaClient()
    suppression = suppression or SuppressionList.empty()
    stats = RunStats()

    # --- search + cheap client-side prefix filter -------------------------
    candidates: List[SearchHit] = []
    for hit in client.search_all(
        query=icp.query,
        state=icp.state,
        ntee_major=icp.ntee_major,
        subsection_code=icp.subsection_code,
    ):
        stats.search_hits += 1
        if _matches_prefix(hit.ntee_code, icp.ntee_prefixes):
            candidates.append(hit)
    stats.after_prefix_filter = len(candidates)
    progress("search", stats.after_prefix_filter, stats.search_hits,
             f"{stats.after_prefix_filter} candidates after NTEE filter "
             f"(of {stats.search_hits} hits)")

    if max_candidates is not None and len(candidates) > max_candidates:
        stats.notes.append(
            f"capped enrichment at {max_candidates} of {len(candidates)} candidates "
            f"(raise --limit to cover the rest)"
        )
        candidates = candidates[:max_candidates]

    # --- enrich (one detail fetch each) + filter + suppress + score -------
    scored: List[ScoredOrg] = []
    total = len(candidates)
    for i, hit in enumerate(candidates, start=1):
        progress("enrich", i, total, hit.name)
        if suppression.contains_ein(hit.ein):
            stats.suppressed += 1
            continue
        try:
            org = client.organization(hit.ein)
        except Exception as e:  # a single bad EIN must not sink the whole run
            stats.errors += 1
            stats.notes.append(f"skip EIN {hit.ein} ({hit.name}): {e}")
            continue
        stats.enriched += 1
        if not _passes_revenue(org, icp):
            continue
        stats.after_revenue_filter += 1
        scored.append(score_org(org, icp))

    scored.sort(key=lambda s: s.total, reverse=True)
    stats.scored = len(scored)
    ranked = scored[: icp.top_n]
    progress("done", len(ranked), stats.scored,
             f"ranked {stats.scored}, returning top {len(ranked)}")
    return ranked, stats
