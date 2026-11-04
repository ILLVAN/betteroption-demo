> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Retention and deletion schedule

Status: implemented application/infrastructure baseline; launch remains blocked
until staging evidence and provider-side retention have been reviewed.

| Data class | Primary period | Trigger/action | Backup/provider treatment |
| --- | --- | --- | --- |
| Invitation | 72 hours | Invalidate at expiry/use/revocation; delete record within 7 days | Aged out with 14-day backup cycle |
| Password recovery | 60 minutes | Invalidate at expiry/use; delete record within 7 days | Same |
| Auth session | 30 days maximum | Revoke at logout/reset/disable; delete expired/revoked row within 7 days | Same |
| Auth-rate attempts | 15-minute decision window; 7-day record max | Automated purge | HMAC subject only |
| Raw Compass answer and user conversation message | 30 days after successful extraction | Delete raw message/section text; retain only structured user-controlled facts | OpenAI default abuse-monitoring content may remain up to 30 days unless approved ZDR |
| Pending/inferred fact | 30 days | Delete if not confirmed | No evaluation reuse |
| Rejected fact and ordinary review event | 7 days after rejection | Delete fact/source and routine event after undo window | Aggregate non-personal count permitted only if anonymous |
| Confirmed profile fact and current preferences | Active account plus inactivity limit | Notify after 12 months inactivity; delete account data after 13 months unless user returns or law requires hold | Provider data follows provider deletion/expiry |
| CV original binary | Never persisted | Hold in memory/temp processing only; delete immediately | Never sent to provider |
| Locally extracted/redacted CV text | Until the extraction request completes | Delete immediately after provider request/result; no alpha retention option | Provider retention disclosed separately |
| CV structured proposals | Pending 30 days; confirmed facts as above | Same as pending/confirmed profile data | No training/evaluation reuse |
| Saved jobs, matches, route estimates, application state | Active account plus inactivity limit | Delete with account; refresh/delete stale public data under corpus rules | Provider query logs per register |
| Semantic match assessment and cited job-fact fingerprints | Retained with the corresponding match under the active-account/inactivity limit | Replace on full rematch; delete with match/persona/account; ignore locally when a cited fact is corrected | OpenAI request/output retention follows the separately approved API configuration; internal provider telemetry remains content-free and follows its 90-day period |
| Salary benchmark evidence and provenance | Retained with the corresponding match under the active-account/inactivity limit | Delete with match/persona/account; refresh or abstain when source evidence is stale or no longer attributable | OpenAI web-search and source-site technical records follow the separately reviewed configuration/policies; no candidate salary target is transferred |
| Editable application draft | 180 days after last update | Automated purge; delete immediately on user request or persona/account deletion | OpenAI request/output retention follows reviewed API configuration; no employer copy |
| Private-alpha product feedback, triage status and operator note | 180 days after last update | Automated purge; delete immediately on the user's feedback deletion or account deletion | Stored only in the WorkLifeBalance database; never sent to AI, model evaluation, analytics or advertising; aged out with 14-day backup cycle |
| Provider operation telemetry | 90 days | Automated purge | No prompt/query/profile/location content |
| Reverse-proxy/application HTTP access logs | Not retained by WorkLifeBalance in the reviewed alpha stack | Keep Caddy access logging absent and Uvicorn `--no-access-log`; verify after every deploy | Cloudflare/Netcup technical connection-data retention separately verified |
| Container runtime/error output | No fixed time period; size-based rotation only | Every Compose service uses Docker `json-file` with at most five 10 MB files. Caddy removes the complete HTTP request object, including URI/query, before encoding runtime/error events | Rotation bounds local Docker output; it is not a time-based retention promise |
| Security/incident events | 90 days ordinarily | Delete unless attached to active incident/legal hold | Incident file as below |
| Support request | 12 months after closure | Delete or anonymise | Provider deletion where applicable |
| DSR completion evidence | 3 years after closure | Keep minimal request/action/date evidence | Restricted access |
| Incident/breach file | 3 years after closure or longer concrete legal requirement | Review annually; delete when purpose/hold ends | Restricted/encrypted |
| Encrypted database backup | 14 rolling days | Automatic expiry and cryptographic/physical deletion | Deletion from live DB reaches every backup by day 14 |
| Billing/tax contract records | Statutory period applicable to actual operator | Separate from product profile; restrict use | Confirm with tax/legal advisor |

## Legal holds

A legal hold must identify the data, legal basis, owner, start/review/end dates.
It suspends only the relevant deletion and never authorises new use. The user is
informed unless legally prohibited.

## Verification

Monthly until stable, then quarterly:

1. confirm the `retention` and `backup-scheduler` services are healthy/running;
2. run `python -m betteroption.retention once` and archive its content-free counts;
3. adapt and validate the Caddy config, confirm no HTTP access logger exists and confirm the default runtime logger deletes the complete `request` field;
4. confirm every resolved Compose service uses `json-file`, `max-size: 10m` and `max-file: 5`, and Uvicorn still uses `--no-access-log`;
5. sample each table/log store without exposing content;
6. verify oldest permissible timestamp;
7. verify provider/project settings;
8. verify oldest backup and restore one test account;
9. record deviations, owner, deadline, and remediation.

The application sidecar runs the purge at least every 24 hours. It removes
expired sessions; ages invitation and recovery records out after their
seven-day audit window; purges HMAC auth attempts, raw Compass conversations,
pending and rejected facts, source excerpts, legacy stored CV text, model
invocation metadata, provider-operation telemetry, application drafts, and
product feedback older than their configured finite periods. New CV uploads are never
persisted. Caddy and Uvicorn HTTP access logging remain disabled. Caddy removes
the complete request object before encoding runtime/error output, and all
container logs use finite size-based rotation; neither control is represented
as a fixed time-based runtime-log period. The backup scheduler creates a daily
database dump with a rolling 14-day local expiry.
Encrypted off-server handling and deletion still require deployment evidence.
