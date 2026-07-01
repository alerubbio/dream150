"""dream150 — bring your own ICP, get a ranked Dream 150 of nonprofits.

Built entirely on the free ProPublica Nonprofit Explorer API (public IRS data).
"""
from .client import (
    NTEE_MAJOR_GROUPS,
    Filing,
    NotFound,
    Organization,
    ProPublicaClient,
    ProPublicaError,
    RateLimited,
    SearchHit,
)
from .config import ICP, ConfigError, icp_from_dict, load_icp
from .pipeline import RunStats, run
from .scoring import ScoredOrg, score_org
from .suppression import SuppressionList, load_suppression

__version__ = "0.1.0"

__all__ = [
    "ProPublicaClient",
    "Organization",
    "Filing",
    "SearchHit",
    "ProPublicaError",
    "NotFound",
    "RateLimited",
    "NTEE_MAJOR_GROUPS",
    "ICP",
    "ConfigError",
    "load_icp",
    "icp_from_dict",
    "score_org",
    "ScoredOrg",
    "SuppressionList",
    "load_suppression",
    "run",
    "RunStats",
    "__version__",
]
