import os

from dream150.suppression import (
    SuppressionList,
    load_suppression,
    normalize_domain,
    normalize_ein,
)


def test_normalize_ein():
    assert normalize_ein("23-7111782") == "237111782"
    assert normalize_ein(237111782) == "237111782"
    assert normalize_ein("12345") == "000012345"
    assert normalize_ein("") is None
    assert normalize_ein(None) is None


def test_normalize_domain():
    assert normalize_domain("https://www.example.org/path") == "example.org"
    assert normalize_domain("Example.ORG") == "example.org"
    assert normalize_domain("http://sub.example.org") == "sub.example.org"
    assert normalize_domain("") is None
    assert normalize_domain(None) is None


def test_empty_suppression_matches_nothing():
    s = SuppressionList.empty()
    assert len(s) == 0
    assert not s.contains_ein(237111782)
    assert not s.contains_domain("example.org")


def test_from_csv(tmp_path):
    p = tmp_path / "dnc.csv"
    p.write_text("ein,domain\n23-7111782,\n,www.blocked.org\n")
    s = SuppressionList.from_csv(str(p))
    assert s.contains_ein(237111782)
    assert s.contains_domain("https://blocked.org")
    assert not s.contains_ein(363673599)


def test_load_suppression_none():
    assert len(load_suppression(None)) == 0
