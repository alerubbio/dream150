from dream150.client import Filing, Organization
from dream150.config import icp_from_dict
from dream150.scoring import _financial_health, _recency, _revenue_fit, score_org


def _org(revenue=None, expenses=None, tax_year=None, ntee="K31", ein=1):
    filing = Filing(
        tax_year=tax_year, total_revenue=revenue,
        total_functional_expenses=expenses, form_type=0, pdf_url="",
    )
    return Organization(
        ein=ein, name="Test Org", city="X", state="CA", ntee_code=ntee,
        subsection_code=3, revenue_amount=revenue, filings=[filing],
    )


def _icp(**over):
    base = {
        "filters": {"min_revenue": 5_000_000, "max_revenue": 250_000_000},
        "scoring": {
            "reference_year": 2024,
            "revenue_sweet_spot": [10_000_000, 100_000_000],
            "recency_full_credit_years": 2,
        },
    }
    base.update(over)
    return icp_from_dict(base)


def test_revenue_fit_in_sweet_spot():
    assert _revenue_fit(23_000_000, _icp()) == 1.0


def test_revenue_fit_below_band_is_zero():
    assert _revenue_fit(1_000_000, _icp()) == 0.0


def test_revenue_fit_above_band_is_zero():
    assert _revenue_fit(300_000_000, _icp()) == 0.0


def test_revenue_fit_tapers_below_sweet_spot():
    v = _revenue_fit(7_000_000, _icp())  # between min 5M and sweet-low 10M
    assert 0.0 < v < 1.0


def test_recency_fresh_full_credit():
    assert _recency(2023, _icp()) == 1.0
    assert _recency(2022, _icp()) == 1.0  # age 2 == full_credit_years


def test_recency_old_decays_to_zero():
    assert _recency(2018, _icp()) == 0.0
    assert _recency(None, _icp()) == 0.0


def test_financial_health_balanced():
    org = _org(revenue=23_338_085, expenses=23_350_748)
    assert _financial_health(org) == 1.0


def test_financial_health_missing_is_zero():
    assert _financial_health(_org(revenue=10_000_000, expenses=None)) == 0.0
    assert _financial_health(_org(revenue=None, expenses=10_000_000)) == 0.0


def test_score_total_bounds_and_ordering():
    icp = _icp()
    strong = score_org(_org(revenue=23_000_000, expenses=23_000_000, tax_year=2023), icp)
    weak = score_org(_org(revenue=6_000_000, expenses=1_000_000, tax_year=2019), icp)
    assert 0.0 <= weak.total <= strong.total <= 100.0
    assert strong.total == 100.0  # all three components maxed


def test_as_row_shape():
    row = score_org(_org(revenue=23_000_000, expenses=23_000_000, tax_year=2023), _icp()).as_row()
    for key in ("ein", "name", "score", "revenue_fit", "recency", "financial_health", "profile_url"):
        assert key in row
