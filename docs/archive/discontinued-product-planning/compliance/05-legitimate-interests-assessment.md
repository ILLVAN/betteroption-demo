> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Legitimate-interests assessment: security and abuse prevention

Status: internal draft requiring review  
Interest: provide a secure, stable invitation-only service; prevent credential
stuffing, token abuse, scraping, denial of service, fraud, and unauthorised
access; investigate incidents and defend legal claims.

## Purpose test

The interests are lawful and benefit both operator and users. The alpha cannot
protect confidential career preferences without authentication controls,
minimal content-free security events, and processor-side edge protection.

## Necessity test

The selected data is limited to what the control needs:

- authentication rate limiting stores an HMAC-derived subject rather than the
  raw email/IP combination;
- the application retains content-free authentication/security events, but
  disables Caddy and Uvicorn HTTP access logs; Caddy's default runtime/error
  logger removes the complete HTTP request object, including URI and query,
  before encoding, and every container log has finite size-based rotation;
- Cloudflare and Netcup may process technical connection data under separately
  reviewed processor settings and retention periods;
- invitation/recovery tokens are stored only as hashes;
- provider telemetry stores provider, purpose, time, units, status and cost
  estimate, not request/response content.

Less intrusive options alone are insufficient: a service with no security logs
cannot reliably detect or investigate attacks. Persistent fingerprinting,
advertising identifiers, behavioural analytics, and indefinite IP storage were
rejected.

## Balancing test

Users reasonably expect essential account-security processing in an
authenticated online service. Harm is limited through invitation-only access,
short retention, HMAC/pseudonymisation, role restriction, TLS, and no secondary
marketing or model-evaluation use. Security monitoring can still reveal usage
patterns and network addresses, so it must remain narrowly accessed and
time-limited.

Children are excluded. Career-transition data can be sensitive in context, so
no profile content is placed in security logs. A user may object under Article
21; the operator must evaluate the objection, while compelling security grounds
may justify continuing the minimum necessary processing.

## Outcome

Art. 6(1)(f) is provisionally selected for the controls above, subject to
external review and verified implementation of the retention/access limits.
This assessment does not cover product analytics, marketing, or training.

Owner approval: **[name/date]**
