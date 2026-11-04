> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Processor, recipient, and transfer register

Review date: 2026-08-05  
Rule: **not approved means disabled**

This is a due-diligence record, not an executed contract. Attach contract PDFs,
account configuration exports, subprocessor snapshots, transfer assessments,
retention/deletion test results, and incident contacts to the launch record.

| Service | Role/limited data | Current official findings | Alpha decision | Missing evidence |
| --- | --- | --- | --- | --- |
| Netcup selected EU server | Processor for hosted account/profile/database/log data | Netcup offers an Art. 28 agreement through CCP. Locations include Nürnberg, Vienna, Amsterdam, US and Singapore; the actual server location must be verified. | **Conditional** | Execute/archive AVV; prove this server is in approved EEA location; subprocessor/TOM/incident review; backup location |
| Cloudflare DNS/proxy/TLS | Processor for connection/HTTP metadata and proxied content as configured | Customer DPA v6.4 (2026-04-03) includes subprocessors and transfer terms. Default network/metadata processing is global; EU Customer Metadata Boundary is a separate enterprise control. | **Conditional** | Accept/archive DPA; product/config inventory; subprocessor snapshot; transfer assessment; retention/log settings; restrict origin |
| OpenAI API and Responses web search | Processor for selected Compass/CV text and model output; per-job unresolved confirmed criterion key/value/level plus canonical public job facts/short quotes for semantic match evidence; minimised confirmed Compass/job fields for requested drafting; and bounded public job fields for configured salary research. Semantic matching excludes account/persona metadata, raw Compass answers, CV text, private ratings, home location, URLs and full advertisements. The salary adapter must never receive a candidate's criterion/target or profile data | EEA customers contract with OpenAI Ireland under DPA effective 2026-01-01; SCC/adequacy safeguards apply. API data is not used to train by default unless customer opts in. Default abuse logs can contain prompts/outputs for up to 30 days; approved ZDR/MAM has separate eligibility. Web search adds source retrieval and citation data flows | **Conditional; external-alpha approval incomplete** | Execute/archive DPA; disable sharing/opt-in; document each endpoint/tool/model, `store` and include settings, project, region, retention, subprocessors, TIA, deletion/incident contacts; verify semantic prompt minimisation, supplied-ID validation, 25-job default bound, local reuse/invalidation and confidence/blocker rules; verify salary payload isolation, source-domain policy and tool-reported citation enforcement |
| Salary benchmark source sites reached through OpenAI web search | Independent web recipients for public job-related search/retrieval; no candidate profile, salary target, account or home-location data | Source coverage is country- and occupation-dependent. The current allowlist contains official EU/national employment/statistics sources and the European Central Bank for necessary currency conversion. No secondary salary source is enabled. Source sites may receive ordinary search/retrieval request and technical data through OpenAI and apply their own policies | **Disabled for external alpha pending exact source policy; local development only** | Approved country/source inventory and fallback rules; terms/robots/licence, role, location/transfer, technical-log/retention, deletion, security and incident review; prove no German/cross-country extrapolation and abstention when unsupported; separately review and corroborate any proposed secondary source before adding its domain |
| Brave Search API | Search-query recipient/possible processor depending contract | Ordinary API notice says query records may be retained up to 90 days and excludes Search Query Data from its DPA; enterprise ZDR is a separate offering. | **Disabled** | Contract covering end-user query data; acceptable retention/ZDR; transfer/subprocessor/TIA review |
| Exa API | Processor under its DPA for customer personal data, but ordinary query service terms are risky | Public DPA uses controller-to-processor SCCs and permits subprocessors. Public privacy notice states Query Data is used to improve products, including model training/fine-tuning; enterprise ZDR is separate. | **Disabled** | Enterprise contract/ZDR; confirm query data is covered by DPA and excluded from training; subprocessor/retention/TIA evidence |
| You.com Search API | Search-query recipient/possible processor; receives a bounded job-search query made from user-entered terms or selected Compass role/preference terms and market location, plus ordinary request metadata. It does not receive the account identifier or complete Compass | No approved project evidence is attached for the applicable API contract/DPA, query use or model-training treatment, retention, subprocessors, processing locations or international transfers. Local technical integration is not approval. | **Disabled; review required** | Execute/archive the applicable contract and DPA or document the controller analysis; verify query use and training controls, log/content retention, subprocessors and locations, transfer safeguards/TIA, deletion procedure/test, security and incident contact |
| Google Maps Platform Routes | Independent-controller relationship under EEA Maps terms | EEA terms say Google collects search terms, IP and coordinates; parties accept controller-controller terms; express prior revocable location consent and public notices/Google terms are required. Caching/attribution restrictions apply. | **Disabled** | Necessity and consent design; exact product/config/retention/transfer review; required terms/privacy/attribution implementation |
| Transitous public API | Independent public endpoint/operator for route query and technical logs | Privacy page records IP, time, URL, user agent; URL may contain endpoints/time/mode; logs kept up to 2 days. No bespoke Art. 28 contract identified. | **Disabled pending written approval** | Confirm commercial/private-alpha use, role/contract, security/incident contact and minimised city-level queries |
| FOSSGIS Valhalla public API | Independent public endpoint/operator for route query and technical logs | Public routing terms allow use subject to attribution, caching and max 1 request/s; service is single-server/no availability guarantee. Public material does not establish an Art. 28 agreement or clear routing-log retention. | **Disabled** | Written role/privacy/retention/commercial-use confirmation; attribution and rate-limit verification |
| OpenRouteService / HeiGIT | Independent endpoint/possible processor depending plan | Terms require attribution and limit use. Public privacy material covers IP/API account data; a forum response says server logs are deleted after 14 days, but this is insufficient contract evidence. | **Disabled** | Current signed terms/DPA or controller analysis; exact retention, subprocessor/location/incident evidence |
| Public Nominatim endpoint | Independent public endpoint | Not separately reviewed in this dossier; queries can reveal locations and public-use policies impose limits. | **Disabled** | Operator privacy/usage/retention/role review or self-hosting |
| Public ATS/job sites | Independent controllers/web recipients | Receive server IP, user agent, requested URL/time; page content may contain professional personal data. | **Conditional per source** | Source allowlist, terms/robots/licence review, request minimisation, deletion/freshness rules |

## Official evidence starting points

- Netcup AVV: <https://www.netcup.com/de/helpcenter/dokumentation/general/avv>
- Netcup locations: <https://www.netcup.com/de/ueber-netcup/server-standorte>
- Cloudflare DPA: <https://www.cloudflare.com/cloudflare-customer-dpa/>
- Cloudflare data localisation: <https://developers.cloudflare.com/data-localization/>
- OpenAI DPA: <https://openai.com/policies/data-processing-addendum/>
- OpenAI API data controls: <https://developers.openai.com/api/docs/guides/your-data>
- OpenAI web search: <https://developers.openai.com/api/docs/guides/tools-web-search>
- Brave API privacy: <https://api-dashboard.search.brave.com/privacy-policy>
- Exa DPA: <https://exa.ai/dpa>
- Exa privacy: <https://exa.ai/privacy-policy>
- Google Maps EEA terms: <https://cloud.google.com/terms/maps-platform/eea>
- Google Routes policies: <https://developers.google.com/maps/documentation/routes/policies>
- Transitous privacy: <https://transitous.org/privacy/>
- FOSSGIS public-service terms: <https://fossgis.de/arbeitsgruppen/osm-server/nutzungsbedingungen/>
- OpenRouteService terms: <https://openrouteservice.org/terms-of-service/>
- HeiGIT privacy: <https://heigit.org/de/datenschutzerklaerung/>
