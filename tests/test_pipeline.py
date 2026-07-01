from dream150.client import SearchHit
from dream150.config import icp_from_dict
from dream150.pipeline import run
from dream150.suppression import SuppressionList

from conftest import FixtureClient


class TwoOrgClient(FixtureClient):
    """Search returns the two EINs we have org fixtures for."""

    def search_all(self, **kw):
        yield SearchHit(ein=237111782, name="Yolo Food Bank", city="Woodland",
                        state="CA", ntee_code="K31Z", score=1.0)
        yield SearchHit(ein=363673599, name="Feeding America", city="Chicago",
                        state="IL", ntee_code="K310", score=1.0)


def _icp(**over):
    base = {
        "filters": {"min_revenue": 5_000_000, "max_revenue": None},
        "scoring": {"reference_year": 2024, "revenue_sweet_spot": [10_000_000, 100_000_000]},
        "output": {"top_n": 10},
    }
    base.update(over)
    return icp_from_dict(base)


def test_pipeline_ranks_in_band_org_first():
    ranked, stats = run(_icp(), client=TwoOrgClient())
    assert stats.enriched == 2
    # Both pass the >=$5M floor (no max), so both are scored.
    assert stats.after_revenue_filter == 2
    assert len(ranked) == 2
    # Yolo sits in the sweet spot; Feeding America is far above it, so Yolo wins.
    assert ranked[0].org.ein == 237111782
    assert ranked[0].total > ranked[1].total


def test_pipeline_revenue_filter_excludes_giant():
    icp = _icp(filters={"min_revenue": 5_000_000, "max_revenue": 250_000_000})
    ranked, stats = run(icp, client=TwoOrgClient())
    # Feeding America ($4.9B) is filtered out; only Yolo remains.
    assert stats.after_revenue_filter == 1
    assert [s.org.ein for s in ranked] == [237111782]


def test_pipeline_prefix_filter():
    icp = _icp(filters={"min_revenue": 5_000_000, "ntee_prefixes": ["P"]})
    ranked, stats = run(icp, client=TwoOrgClient())
    # Both orgs are K-coded, none match prefix P.
    assert stats.after_prefix_filter == 0
    assert ranked == []


def test_pipeline_suppression():
    supp = SuppressionList(eins={"237111782"})
    ranked, stats = run(_icp(), client=TwoOrgClient(), suppression=supp)
    assert stats.suppressed == 1
    assert all(s.org.ein != 237111782 for s in ranked)


def test_pipeline_limit_caps_candidates():
    ranked, stats = run(_icp(), client=TwoOrgClient(), max_candidates=1)
    assert stats.enriched == 1
    assert any("capped" in n for n in stats.notes)
