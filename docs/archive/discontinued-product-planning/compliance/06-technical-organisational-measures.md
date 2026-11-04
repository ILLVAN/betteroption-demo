> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Technical and organisational measures

Status: target/control register; each item needs operational evidence

| Domain | Required measure | Evidence |
| --- | --- | --- |
| Governance | Named controller, privacy/security owners, annual and material-change review | Signed launch record |
| Access | Individual operator account, least privilege, no shared admin login, MFA for Netcup/Cloudflare/OpenAI/GitHub where offered | Account screenshots/export |
| Authentication | Verified invite-only accounts, strong password hashing, single-use hashed invitation/recovery tokens | Tests and configuration |
| Sessions | Secure, HttpOnly, SameSite cookies; 30-day maximum; revoke on reset/disable; purge expired rows | Tests and purge report |
| Browser security | HTTPS, HSTS after validation, CSP/security headers, same-origin CSRF enforcement, no third-party analytics | Header test |
| Tenant isolation | Every private query scoped to account/workspace; cross-tenant adversarial tests | CI results |
| Network edge | Cloudflare Full (strict); restrict origin to Cloudflare ranges or tunnel before trusting visitor-IP headers | Firewall rules and external probe |
| Data minimisation | City/postcode default; no employer access; no auto application; metadata-only ledger | Product tests and UI review |
| CV safety | Server-local parse, identifier redaction, sensitive-category rejection, editable preview, separate action, transient deletion | Test corpus and deletion test |
| AI provider | Separate project/API key, no training opt-in, `store=false` where supported, approved model/endpoint/region, spend limits | Provider settings record |
| Salary research | Disabled for external users until approved; one bounded public-job-only batch; no candidate criterion/target or profile fields; explicit source-domain allowlist; tool-reported source verification; country/currency/period provenance and cross-country abstention | Captured-schema tests, source-policy record and adversarial country tests |
| External providers | Default disabled; explicit allow after contract/transfer/retention review | Processor register approval |
| Secrets | Environment/secret store only, mode 600, no Git/ZIP/log exposure, rotation after incident/personnel change | Secret scan and rotation log |
| Database | PostgreSQL with strong unique credential, account deletion cascades, migrations before app start | Preflight and schema test |
| Encryption | TLS in transit; encrypted off-server backups; encrypted operator devices | Config/evidence |
| Logging | Caddy and Uvicorn HTTP access logs disabled; Caddy default runtime/error logger deletes the complete HTTP request object before encoding; Docker `json-file` output for every service limited to five 10 MB files (size-based, not time-based); no passwords, tokens, CV/profile/prompt text in application logs; content-free security events limited to 90 days | Caddy adapted-JSON assertion, resolved-Compose rotation assertion, security-event sampling and purge report; processor retention evidence |
| Backups | Daily encrypted backup, separate credential/location, 14-day rolling expiry, quarterly restore drill | Hashes, deletion and restore report |
| Vulnerability handling | Locked dependencies, routine updates, lint/tests, secret scan, urgent patch path | CI/dependency record |
| Availability | Health endpoints, service/database monitoring, resource alerts, documented rollback | Monitoring screenshots and drill |
| Incident response | Named 24/7 escalation path, breach register, 72-hour authority workflow, evidence preservation | Tabletop report |
| Rights | Authenticated export/delete, manual restriction/correction path, provider/backups checklist | DSR dry-run record |
| Personnel | Confidentiality, access review, privacy/security training; remove access immediately on departure | Access/training log |
| Disposal | Automated data-class purges and provider deletion; secure destruction of exports/backups/media | Deletion reports |

No checkbox is considered implemented merely because it appears in this file.
