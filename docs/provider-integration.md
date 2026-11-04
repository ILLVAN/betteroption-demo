# Provider integration

Provider adapters are optional implementation examples. External availability,
terms, and prices may have changed since development ended. Keys belong in a
private local environment; examples contain no usable deployment credentials.

| Capability | Adapter/source | Main configuration |
| --- | --- | --- |
| Structured profile/job extraction and application material | [OpenAI adapters](../src/betteroption/providers) | `OPENAI_API_KEY`, task-specific model settings |
| Unresolved semantic match evidence | [openai_match_evidence.py](../src/betteroption/providers/openai_match_evidence.py) | `BETTEROPTION_MATCH_EVIDENCE_MAX_JOBS` |
| Web discovery | [Brave](../src/betteroption/brave_search.py), [Exa/You source mesh](../src/betteroption/discovery_sources.py) | `BRAVE_SEARCH_API_KEY`, `EXA_API_KEY`, `YDC_API_KEY` |
| Structured vacancies | [JSearch](../src/betteroption/providers/openwebninja_jsearch.py), [Apify adapters](../src/betteroption/providers) | `OPENWEBNINJA_JSEARCH_API_KEY`, `APIFY_API_TOKEN` |
| Public job boards | [discovery.py](../src/betteroption/discovery.py), [discovery_sources.py](../src/betteroption/discovery_sources.py) | Arbeitnow and explicitly configured ATS boards |
| Exact commute evidence | [mobility.py](../src/betteroption/mobility.py) | Google Routes, OpenRouteService, Transitous, Valhalla settings |
| Local place resolution | [geography.py](../src/betteroption/geography.py) | Bundled reference data; optional geocoder fallback |

## Request and failure boundaries

Discovery candidates pass deduplication and source checks before presentation.
Providers have independent deadlines and status reporting; a failing source can
degrade one capability while stored user work remains available. Every configured
source also remains subject to account-owned provider permissions.

Profile/job extraction proposes evidence-backed structure. Semantic matching
receives selected confirmed criteria and public job facts for unresolved
relations, rather than an unrestricted candidate-profile dump. Exact routing
uses endpoints, mode, and time; Explore itself ranks with approximate geography.

See [settings.py](../src/betteroption/settings.py) and
[.env.example](../.env.example) for the retained settings. Blank API keys do not
disable all networking: public ATS, discovery, and route services can be keyless.

## Budgets and telemetry

[operations.py](../src/betteroption/operations.py) reserves metadata-only provider
budget before outbound I/O. Daily and workflow limits, cancellation, provider
outcomes, and estimated costs remain inspectable. Zero pricing inputs mean
**unpriced**, rather than free.

For Apify All Jobs, the default 120-item readback/presentation guard limits
results read/displayed. The separate USD 0.40 pay-per-event charge ceiling is
sent to the actor API. The implementation preserves this distinction; neither
value establishes a current vendor price.

## Diagnostics

```bash
python scripts/diagnose_config.py
python scripts/diagnose_openai.py
python scripts/diagnose_jsearch.py
```

Review each diagnostic before running it. JSearch only performs its fixed live
probe with `--live`; provider checks can consume requests. Do not print or commit
real keys, user payloads, authenticated URLs, or response bodies. Historical
[provider reviews](archive/engineering-history/providers) preserve the contracts
examined during implementation.
