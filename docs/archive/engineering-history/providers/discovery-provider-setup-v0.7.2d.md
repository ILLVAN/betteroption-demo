> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Explore provider setup — v0.7.2d

Copy [`.env.example`](../../../../.env.example) to the private runtime `.env`. Configure
only services you intend to test, then choose them under Account → Provider
choices. Never put real credentials in source control, screenshots or ZIPs.

## Equal-source policy

`BETTEROPTION_DISCOVERY_CALL_ALL_PROVIDERS=true` starts every configured and
account-enabled discovery source concurrently. It does not make every source
equally relevant; it makes each provider eligible for the same local ranking.
Content, seniority, exclusions, distance, freshness and evidence quality decide.

Use the canonical fallback setting name:

```dotenv
BETTEROPTION_DISCOVERY_FALLBACK_MIN_RESULTS=60
```

The older `BETTEROPTION_EXA_FALLBACK_MIN_RESULTS` remains accepted for local
compatibility but is inactive while call-all-providers is true and should be
removed from current `.env` files.

## Controlled diagnostics

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
.\.venv\Scripts\python.exe scripts\diagnose_config.py --probe-brave-search
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py
.\.venv\Scripts\python.exe scripts\diagnose_jsearch.py --live
```

The Brave probe and JSearch live probe each spend exactly one provider request.
The JSearch live probe is deliberately synthetic and does not include Compass
or CV text. The successful `v0.7.2d` acceptance observation returned ten jobs.

## Cost boundary

Every `*_ESTIMATED_COST_*` field must reflect the current account contract.
Zero means unpriced, not free. Zero in either provider USD cost ceiling disables
that monetary guard. Before invitations, set measured non-zero daily and
per-workflow ceilings and test their blocked behavior.

The source panel reports found and contributed counts per provider. Operations
retains provider IDs, request/run units, latency, outcome and configured cost
estimates without storing keys, queries, URLs, responses or job bodies.

For exact source contracts and current legal/processor decisions, retain the
provider's own current documentation and the project compliance register; this
setup note is an engineering configuration guide, not authorization to enable a
provider online.
