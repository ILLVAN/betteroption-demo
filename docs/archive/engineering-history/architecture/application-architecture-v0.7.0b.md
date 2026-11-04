> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.0b account and operator architecture

## Identity

Email is the stable sign-in identifier. Username is a mutable presentation
identity with a separate case-insensitive uniqueness key. Both constraints are
enforced in the database, not only in forms.

| Action | Authentication rule | Security result |
|---|---|---|
| Change username | Current password required | Email and sessions unchanged |
| Change password | Current password required | Every session revoked |
| Export | Current session required | Authentication secrets omitted |
| Delete account | Current password plus exact phrase | Private tenant graph deleted |

## Maintenance surface

Normal accounts remain equal in the product data model. Operator access is a
deployment concern configured by normalized email allowlist:

```dotenv
BETTEROPTION_OPERATOR_EMAILS=owner@example.com,backup-operator@example.com
```

The maintenance route is deliberately absent from product navigation and Home.
The route still performs explicit authorization and returns 404 for a signed-in
account outside the allowlist. Removing a link is not a security control.

The current allowlist is appropriate for a controlled private alpha. A later
operational deployment can move this surface to a separately hosted process,
identity-aware proxy, or administrative identity provider without changing
tenant account roles.

## Next security gates

Before the first online alpha:

- terminate HTTPS at a hardened reverse proxy and enable secure cookies;
- add invite/email verification, recovery, and authentication rate limits;
- deploy PostgreSQL with least-privilege credentials and encrypted backups;
- define log retention without profile, prompt, CV, or search payloads;
- run dependency, secret, static-analysis, and dynamic security checks;
- test tenant authorization and deletion paths independently;
- complete privacy, terms, processor, and legal-basis review.
