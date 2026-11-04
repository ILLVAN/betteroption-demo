> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# BetterOption v0.6.10a — Provider operations foundation

v0.6.10a begins the 0.6.10 evidence-quality line without disturbing the accepted
v0.6.9j search, routing, and match presentation. It fixes one polarity defect,
makes Compass-led discovery the obvious path, restores accessible destructive
confirmation, and introduces the first durable provider-usage boundary.

## Product corrections

- `no internship` remains a narrow exclusion. It blocks an evidenced internship,
  not an ordinary junior individual-contributor role.
- Search with Compass is now the primary Explore action. Manual role and location
  fields remain available as a secondary, expandable tool.
- Archive, Match, reference, and detail-page deletion use one accessible modal.
  The server still receives explicit destructive intent, so stale or disabled
  JavaScript cannot weaken deletion semantics.

Because exclusion evaluation changed, run Matching once after installing this
release. Existing jobs do not need to be imported again.

## Provider-operation ledger

Migration `0009_provider_operations` records operational envelopes for model
invocations, source-mesh searches, company research, and actual route-provider
calls. It stores provider, purpose, outcome, budget decision, timestamps,
latency, units, result count, configured estimated cost, failure class, and cache
status. It has no columns for search phrases, addresses, URLs, prompts, model
responses, CV text, job text, or API keys.

The Home page contains a collapsed private-alpha operations pulse. Pricing is
not hardcoded: OpenAI token rates and logical discovery/company/Google operation
estimates are optional environment settings. Unconfigured providers therefore
show usage and failures while contributing `$0` to the estimate.

The daily operation and estimated-cost ceilings are deliberately conservative,
best-effort guards for local alpha testing. Durable per-task reservations,
provider-specific fallback budgets, retries, and persisted progress belong to
v0.6.11.

## Upgrade

The normal installer runs the database migration automatically and preserves
`.env`, the database, CV text, and local data:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_latest_release.ps1
```

No profile data, database, `.env`, API key, CV, or release ZIP is included in
the source archive.
