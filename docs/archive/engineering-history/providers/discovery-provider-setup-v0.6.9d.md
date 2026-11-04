> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Discovery provider setup and cost guide

Checked against the providers' official public pricing on 22 July 2026. Always
confirm the provider dashboard before production because prices and terms can
change.

## Recommended local evaluation setup

1. Keep the keyless Arbeitnow and public ATS connectors enabled.
2. Add Exa as the preferred semantic web-discovery layer.
3. Add Brave Search only when the broader recall layer is useful for the test.
4. Keep `BETTEROPTION_DISCOVERY_FALLBACK_MIN_RESULTS=60` as the threshold below
   which configured supplemental broad-web sources may run.

The API keys stay server-side in `.env`; they are never rendered into HTML or
sent to the browser.

```dotenv
BETTEROPTION_ARBEITNOW_PAGES=30
EXA_API_KEY=replace-with-your-exa-key
BRAVE_SEARCH_API_KEY=replace-with-your-brave-key
BETTEROPTION_DISCOVERY_FALLBACK_MIN_RESULTS=60
BETTEROPTION_EXA_SEARCH_BUDGET_SECONDS=140
```

Restart Uvicorn after changing `.env`.

## Brave Search

Create a Search API subscription and key in Brave's developer dashboard, then
place the key in `BRAVE_SEARCH_API_KEY`. BetterOption calls the Web Search
endpoint (`/res/v1/web/search`) and therefore requires the **Search** product.
Brave's separate **Answers** plan returns generated answers and is not used by
Explore or company research. Do not substitute an Answers-only key or add a
`BRAVE_ANSWERS_API_KEY` for BetterOption.

Check the effective configuration without revealing either key:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py
```

Brave is a supplemental recall source and may legitimately make no request when
the preferred mesh already reaches the configured result floor. If Search is
configured but no `Brave Web` cards ever appear when that floor is not reached,
make one fixed,
non-user-data Web Search probe. This consumes one Search request:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_config.py --probe-brave-search
```

The probe distinguishes rejected authentication, missing Search-plan access,
rate/credit limits, provider availability, and an unexpected response. A pass
proves endpoint access only; a real job query can still return zero candidates
after job-page and location-quality filters.

Official price: USD 5 per 1,000 Search requests, with USD 5 in credits each
month. A regional Compass search performs up to ten role-by-city queries. The
origin-focused query may request one additional page, for a maximum of eleven
Brave requests per Explore action. At the current public price that is at most
about USD 0.055 per full Brave-backed Explore action before monthly credits.
The free USD 5 corresponds to 1,000 requests, or roughly 90 maximum-depth
regional searches.

Brave states that the card on a free subscription is used for anti-fraud
verification. Confirm storage rights and attribution requirements for the plan
before retaining more than URLs, snippets, and request metadata.

- Pricing: https://api-dashboard.search.brave.com/documentation/pricing
- Authentication: https://api-dashboard.search.brave.com/documentation/guides/authentication
- Web Search endpoint: https://api-dashboard.search.brave.com/api-reference/web/search/get
- Product and privacy information: https://brave.com/search/api/

## Exa

Create an API key in the Exa dashboard and place it in `EXA_API_KEY`. BetterOption
uses focused role, locality and optional saved-portal `fast` requests within the
configured time budget. Exa runs with the preferred source mesh when enabled;
every returned URL still passes the ordinary ranking, safety, deduplication and
availability boundaries. The exact request count is recorded in the secret-safe
operations view.

Exa's official Search product currently lists USD 7 per 1,000 requests. Its
official bundled/x402 pricing lists USD 0.007 for a fast request and USD 0.001
per returned page for highlights. At the current 40-result request shape, a
conservative upper estimate is therefore about USD 0.047 per focused Exa
request. A complete Explore run can use several independent requests, so actual
API-key billing must be checked in the Exa dashboard because
result count, returned contents, account plan, and future pricing can change.

- Search product pricing: https://exa.ai/products/search
- Bundled request/content pricing: https://exa.ai/docs/reference/x402-guide

## Cost guardrails before an online alpha

- Record provider, request count, result count, latency, and estimated cost for
  every Explore invocation; never store API keys or full user Compass text in
  telemetry.
- Apply a per-workspace daily Explore allowance before opening registration.
- Cache keyless feed pages and ATS boards. Do not cache third-party content
  beyond the provider's allowed storage rights.
- Keep Explore on approximate offline geography. Exact road/transit/bicycle
  routing belongs only in an explicit Matching run.
- A future 200-company regional pool should be a scheduled, rate-limited,
  source-attributed background index—not 200 synchronous page requests from a
  user's browser action.
