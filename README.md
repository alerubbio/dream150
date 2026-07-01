# dream150

**Bring your own ICP, get a ranked "Dream 150" of nonprofits — from free public IRS data.**

You describe your ideal nonprofit customer in a small YAML file (cause area, revenue band, geography, size). `dream150` searches the [ProPublica Nonprofit Explorer](https://projects.propublica.org/nonprofits/api) — a free, no-key API over public IRS Form 990 data — enriches each match with its latest financials, scores it for fit, and hands back a ranked, exportable list.

No API keys. No paid data vendors. No account. Just `pip install` and a config file.

```
$ dream150 run --config icp.yaml --out dream.csv
ICP "Sample ICP — mid-size human-services nonprofits"  query="food bank"  ntee_major=5 (Human Services)  revenue >=$5,000,000 <=$250,000,000
  622 candidates after NTEE filter (of 1,000 hits)
  enriching 150/150: ...
Done. 622 candidates -> 150 enriched -> 118 in revenue band -> top 118 written.
  wrote dream.csv
```

## Why

Prospecting into the nonprofit sector usually means paying for a data platform whose "insight" is, underneath, just parsed public IRS filings. That data is free and open. `dream150` turns the repeatable part — *search a segment, pull financials, rank by fit* — into a small, transparent tool where **the targeting lives in your config, not in the code**. Swap the ICP, get a different list.

## Install

```bash
pip install -e .
# or, once released:  pip install dream150
```

Requires Python 3.9+. The only runtime dependency is PyYAML.

## Quickstart

1. Copy the sample ICP and edit it for your target:

   ```bash
   cp icp.sample.yaml icp.local.yaml   # icp.local.yaml is gitignored
   ```

2. Run it:

   ```bash
   dream150 run --config icp.local.yaml --out dream.csv --json
   ```

You get `dream.csv` (and `dream.json`) ranked best-fit first, with a score breakdown per org and a link to each ProPublica profile and 990 PDF.

### Other commands

```bash
dream150 search "food bank" --state CA        # raw search, no scoring
dream150 org 237111782                        # one org's profile + financials
dream150 org 237111782 --json                 # raw API payload
```

CLI flags override the config for a one-off run: `--state`, `--query`, `--min-revenue`, `--max-revenue`, `--top-n`, `--limit`.

## The ICP config

Every field is optional; anything omitted falls back to a sensible default. See [`icp.sample.yaml`](icp.sample.yaml) for the fully-commented version.

```yaml
name: "Mid-size human-services nonprofits"

search:            # narrows the pull server-side, before anything downloads
  query: "food bank"
  state: null           # "CA", or null for national
  ntee_major: 5         # ProPublica major group (5 = Human Services); null to skip
  subsection_code: 3    # 501(c)(3); null to skip

filters:           # applied locally after each org's financials are fetched
  ntee_prefixes: ["P", "K"]   # fine NTEE codes to keep; [] to skip
  min_revenue: 5000000
  max_revenue: 250000000

scoring:
  reference_year: 2024
  revenue_sweet_spot: [10000000, 100000000]
  recency_full_credit_years: 2
  weights:
    revenue_fit: 0.5
    recency: 0.25
    financial_health: 0.25

output:
  top_n: 150

suppression:
  file: null   # optional do-not-contact CSV with ein/domain columns
```

**NTEE codes:** ProPublica's `ntee_major` filter is coarse (10 major groups). Use `ntee_prefixes` for fine control — e.g. `["P"]` keeps human-services orgs, `["K31"]` keeps food banks. The prefix filter runs on the free search fields, so it costs nothing.

## How scoring works

The default model is **generic on purpose** and scores only on fields the free API exposes. It is a labeled starting point — retune or zero-out any weight in your config without touching code:

| Component | What it rewards |
|---|---|
| `revenue_fit` | Revenue inside your target band, with full credit in an optional sweet spot |
| `recency` | A fresh latest filing (a proxy for an active, reachable org) |
| `financial_health` | Reports both revenue and expenses and runs roughly in balance |

Each component is `0..1`; the total is their weighted average, scaled to `0..100`.

## What this does *not* do (yet)

The ProPublica API exposes an org's **total** revenue and functional expenses, but **not** the Form 990 Part IX split (program vs. management vs. **fundraising** expense). That breakdown — often the most useful fit signal for a fundraising-driven segment — lives only in the raw IRS 990 e-file XML.

A follow-up project parses that XML directly and plugs into this same scoring interface, so a `fundraising_fit` component can drop in without a rewrite. Until then, `dream150` ranks on what the free API gives.

Also out of scope here: contact/persona resolution (finding the right person and email) — that's a separate concern from building the account list.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests run **fully offline** against recorded API fixtures in `tests/fixtures/`, so they're deterministic and need no network.

## Data & etiquette

Data comes from the IRS via ProPublica's Nonprofit Explorer, which is free and public. The client is polite by default (a minimum interval between requests plus backoff on throttling); keep `--min-interval` reasonable on large runs. Please cite [ProPublica Nonprofit Explorer](https://projects.propublica.org/nonprofits/) as the data source, per their API terms.

## License

MIT — see [LICENSE](LICENSE).
