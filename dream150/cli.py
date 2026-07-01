"""Command-line interface for dream150.

    dream150 run   --config icp.yaml [--out dream.csv] [overrides]
    dream150 search "food bank" --state CA
    dream150 org 237111782
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import List, Optional

from . import __version__
from .client import NotFound, ProPublicaClient, ProPublicaError
from .config import ConfigError, load_icp
from .pipeline import run as run_pipeline
from .scoring import ScoredOrg
from .suppression import load_suppression

ROW_FIELDS = [
    "rank", "ein", "name", "city", "state", "ntee_code",
    "latest_revenue", "latest_expenses", "latest_tax_year",
    "score", "revenue_fit", "recency", "financial_health",
    "profile_url", "pdf_url",
]


def _eprint(*a) -> None:
    print(*a, file=sys.stderr)


def _progress(stage: str, current: int, total: Optional[int], message: str) -> None:
    if stage == "enrich" and total:
        # Overwrite a single line so long runs don't scroll off the screen.
        _eprint(f"\r  enriching {current}/{total}: {message[:48]:<48}", )
    elif stage in ("search", "done"):
        _eprint(f"  {message}")


def _write_csv(rows: List[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ROW_FIELDS)
        w.writeheader()
        w.writerows(rows)


def _write_json(rows: List[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def _ranked_rows(ranked: List[ScoredOrg]) -> List[dict]:
    rows = []
    for i, s in enumerate(ranked, start=1):
        row = {"rank": i}
        row.update(s.as_row())
        rows.append(row)
    return rows


def cmd_run(args: argparse.Namespace) -> int:
    try:
        icp = load_icp(args.config)
    except (OSError, ConfigError) as e:
        _eprint(f"config error: {e}")
        return 2

    # CLI overrides win over the file.
    if args.state is not None:
        icp.state = args.state
    if args.query is not None:
        icp.query = args.query
    if args.min_revenue is not None:
        icp.min_revenue = args.min_revenue
    if args.max_revenue is not None:
        icp.max_revenue = args.max_revenue
    if args.top_n is not None:
        icp.top_n = args.top_n

    _eprint(icp.describe())
    suppression = load_suppression(icp.suppression_file)
    if len(suppression):
        _eprint(f"  suppression: {len(suppression)} entries loaded")

    client = ProPublicaClient(min_interval=args.min_interval)
    try:
        ranked, stats = run_pipeline(
            icp, client=client, suppression=suppression,
            max_candidates=args.limit, progress=_progress,
        )
    except ProPublicaError as e:
        _eprint(f"\nAPI error: {e}")
        return 1
    _eprint("")  # newline after the progress line

    rows = _ranked_rows(ranked)
    base = args.out
    if base.endswith(".csv"):
        base = base[:-4]
    _write_csv(rows, base + ".csv")
    if args.json:
        _write_json(rows, base + ".json")

    _eprint(
        f"\nDone. {stats.after_prefix_filter} candidates -> {stats.enriched} enriched "
        f"-> {stats.after_revenue_filter} in revenue band -> top {len(rows)} written."
    )
    if stats.suppressed:
        _eprint(f"  {stats.suppressed} suppressed")
    if stats.errors:
        _eprint(f"  {stats.errors} fetch errors (skipped)")
    for note in stats.notes[:5]:
        _eprint(f"  note: {note}")
    written = base + ".csv" + ("  + .json" if args.json else "")
    _eprint(f"  wrote {written}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    client = ProPublicaClient(min_interval=args.min_interval)
    try:
        page = client.search(
            query=args.query, state=args.state,
            ntee_major=args.ntee_major, subsection_code=args.subsection_code,
        )
    except ProPublicaError as e:
        _eprint(f"API error: {e}")
        return 1
    print(f"{page.total_results} results across {page.num_pages} pages "
          f"(showing page {page.cur_page}):")
    for h in page.hits:
        loc = ", ".join(x for x in (h.city, h.state) if x)
        print(f"  {h.ein:<11} {h.name[:44]:<44} {h.ntee_code or '':<6} {loc}")
    return 0


def cmd_org(args: argparse.Namespace) -> int:
    client = ProPublicaClient(min_interval=args.min_interval)
    try:
        org = client.organization(args.ein)
    except NotFound:
        _eprint(f"No organization found for EIN {args.ein}")
        return 1
    except ProPublicaError as e:
        _eprint(f"API error: {e}")
        return 1
    if args.json:
        print(json.dumps(org.raw, indent=2))
        return 0
    print(f"{org.name}  (EIN {org.ein})")
    print(f"  {', '.join(x for x in (org.city, org.state) if x)}   NTEE {org.ntee_code}")
    print(f"  latest revenue:  {org.latest_revenue:,}" if org.latest_revenue else "  latest revenue:  n/a")
    print(f"  latest expenses: {org.latest_expenses:,}" if org.latest_expenses else "  latest expenses: n/a")
    print(f"  latest filing:   TY{org.latest_tax_year}" if org.latest_tax_year else "  latest filing:   n/a")
    print(f"  profile: {org.profile_url}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dream150",
        description="Bring your own ICP, get a ranked Dream 150 of nonprofits "
                    "from free public IRS data (ProPublica Nonprofit Explorer).",
    )
    p.add_argument("--version", action="version", version=f"dream150 {__version__}")
    p.add_argument("--min-interval", type=float, default=0.2,
                   help="min seconds between API requests (politeness; default 0.2)")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run the full ICP -> ranked Dream N pipeline")
    r.add_argument("--config", "-c", default="icp.yaml", help="path to ICP YAML (default icp.yaml)")
    r.add_argument("--out", "-o", default="dream150.csv", help="output path (.csv; .json added with --json)")
    r.add_argument("--json", action="store_true", help="also write a JSON file")
    r.add_argument("--limit", type=int, default=None, help="cap candidates that get an enrichment fetch")
    r.add_argument("--state", default=None, help="override ICP search.state")
    r.add_argument("--query", default=None, help="override ICP search.query")
    r.add_argument("--min-revenue", type=int, default=None, help="override filters.min_revenue")
    r.add_argument("--max-revenue", type=int, default=None, help="override filters.max_revenue")
    r.add_argument("--top-n", type=int, default=None, help="override output.top_n")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("search", help="raw search, print matching orgs")
    s.add_argument("query", nargs="?", default=None, help="free-text query")
    s.add_argument("--state", default=None)
    s.add_argument("--ntee-major", type=int, default=None, help="ProPublica major group 1-10")
    s.add_argument("--subsection-code", type=int, default=None, help="e.g. 3 for 501(c)(3)")
    s.set_defaults(func=cmd_search)

    o = sub.add_parser("org", help="print one organization by EIN")
    o.add_argument("ein", type=int, help="employer identification number")
    o.add_argument("--json", action="store_true", help="dump the raw API payload")
    o.set_defaults(func=cmd_org)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
