"""Generic do-not-contact suppression.

A suppression file is a plain CSV with any of these columns (case-insensitive):
`ein`, `domain`, `website`. Rows are matched against candidate orgs by EIN
(exact, digits only) or by website domain (host, `www.` stripped). This is a
standard opt-in exclusion feature, not anyone's specific list.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from typing import Optional, Set
from urllib.parse import urlparse


def normalize_ein(value) -> Optional[str]:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits.zfill(9) if digits else None


def normalize_domain(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().lower()
    if not v:
        return None
    if "//" not in v:
        v = "//" + v  # let urlparse find the host even without a scheme
    host = urlparse(v).netloc or ""
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


@dataclass
class SuppressionList:
    eins: Set[str] = field(default_factory=set)
    domains: Set[str] = field(default_factory=set)

    def __len__(self) -> int:
        return len(self.eins) + len(self.domains)

    def contains_ein(self, ein) -> bool:
        n = normalize_ein(ein)
        return n is not None and n in self.eins

    def contains_domain(self, website: Optional[str]) -> bool:
        d = normalize_domain(website)
        return d is not None and d in self.domains

    @classmethod
    def empty(cls) -> "SuppressionList":
        return cls()

    @classmethod
    def from_csv(cls, path: str) -> "SuppressionList":
        eins: Set[str] = set()
        domains: Set[str] = set()
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fields = {(name or "").strip().lower(): name for name in (reader.fieldnames or [])}
            ein_col = fields.get("ein")
            dom_col = fields.get("domain") or fields.get("website")
            for row in reader:
                if ein_col:
                    n = normalize_ein(row.get(ein_col))
                    if n:
                        eins.add(n)
                if dom_col:
                    d = normalize_domain(row.get(dom_col))
                    if d:
                        domains.add(d)
        return cls(eins=eins, domains=domains)


def load_suppression(path: Optional[str]) -> SuppressionList:
    if not path:
        return SuppressionList.empty()
    return SuppressionList.from_csv(path)
