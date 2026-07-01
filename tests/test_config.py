import os

import pytest

from dream150.config import ConfigError, icp_from_dict, load_icp

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "icp.sample.yaml")


def test_load_sample_icp():
    icp = load_icp(SAMPLE)
    assert icp.name.startswith("Sample ICP")
    assert icp.query == "food bank"
    assert icp.ntee_major == 5
    assert icp.subsection_code == 3
    assert icp.ntee_prefixes == ["P", "K"]
    assert icp.min_revenue == 5000000
    assert icp.max_revenue == 250000000
    assert icp.revenue_sweet_spot == (10000000, 100000000)
    assert icp.top_n == 150
    assert abs(sum(icp.weights.values()) - 1.0) < 1e-9


def test_defaults_when_empty():
    icp = icp_from_dict({})
    assert icp.name == "Unnamed ICP"
    assert icp.subsection_code == 3
    assert icp.ntee_prefixes == []
    assert icp.top_n == 150


def test_ntee_prefixes_uppercased_and_string_coerced():
    icp = icp_from_dict({"filters": {"ntee_prefixes": "p"}})
    assert icp.ntee_prefixes == ["P"]


def test_min_greater_than_max_rejected():
    with pytest.raises(ConfigError):
        icp_from_dict({"filters": {"min_revenue": 100, "max_revenue": 10}})


def test_unknown_weight_rejected():
    with pytest.raises(ConfigError):
        icp_from_dict({"scoring": {"weights": {"made_up": 1.0}}})


def test_bad_ntee_major_rejected():
    with pytest.raises(ConfigError):
        icp_from_dict({"search": {"ntee_major": 42}})


def test_bad_sweet_spot_rejected():
    with pytest.raises(ConfigError):
        icp_from_dict({"scoring": {"revenue_sweet_spot": [100, 10]}})


def test_zero_weights_rejected():
    with pytest.raises(ConfigError):
        icp_from_dict({"scoring": {"weights": {"revenue_fit": 0, "recency": 0, "financial_health": 0}}})
