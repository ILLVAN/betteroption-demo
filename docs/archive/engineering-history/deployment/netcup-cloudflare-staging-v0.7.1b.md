> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Deploy v0.7.1b to Netcup and Cloudflare

> **Historical only:** this guide publishes a direct origin and must not be used
> for a new deployment. Use the tunnel-only
> [`v0.7.2k` private-alpha runbook](netcup-cloudflare-private-alpha-v0.7.2k.md),
> which creates Access before the route and exposes no host web ports.

This runbook upgrades the existing Debian 13 Netcup staging server at
`staging.betteroption.example`. It assumes:

- SSH alias `wlb-alpha`;
- repository `/srv/betteroption/app`;
- Cloudflare proxy enabled;
- Docker Compose already installed;
- the owner account already exists;
- `deploy/.env.staging` exists only on the server.

Never copy the local `.env`, SQLite database, profiles, CVs, or provider secrets
into Git or a release archive.

## 1. Install and test locally

In Windows PowerShell:

```powershell
cd C:\projects\betteroption

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1
```

Start a local smoke test in a separate terminal:

```powershell
cd C:\projects\betteroption
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Check Home, Compass, Explore, Matching, Archive, Account, and Operations. Local
mode does not reproduce secure-cookie or Cloudflare behavior; the automated
tests cover that boundary.

## 2. Commit and push

Stop the local server, inspect the exact release, then push manually:

```powershell
cd C:\projects\betteroption
git status --short
git diff --stat
git add -A
git commit -m "Add secure invitation onboarding v0.7.1b"
ssh-add "$HOME\.ssh\id_ed25519"
git push origin main
git log -1 --oneline
```

Do not continue on the server until GitHub shows that commit.

## 3. Fetch the release on Netcup

```powershell
ssh wlb-alpha
```

On the server:

```sh
cd /srv/betteroption/app
git status --short
git fetch origin
git log --oneline HEAD..origin/main
git pull --ff-only
git log -1 --oneline
grep '^version' pyproject.toml
```

The worktree must be clean and the version must be `0.7.1+b`.

## 4. Back up PostgreSQL

```sh
cd /srv/betteroption/app
mkdir -p /srv/betteroption/backups
docker compose --env-file deploy/.env.staging exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | gzip > "/srv/betteroption/backups/before-v071b-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
ls -lh /srv/betteroption/backups/
```

This same-host copy is a rollback aid, not the required off-server backup.

## 5. Update the server environment

Generate a separate authentication HMAC secret:

```sh
openssl rand -hex 32
nano deploy/.env.staging
```

Set or verify:

```dotenv
BETTEROPTION_AUTH_MODE=accounts
BETTEROPTION_REGISTRATION_MODE=invite_only
BETTEROPTION_AUTH_SESSION_DAYS=30
BETTEROPTION_AUTH_SECURE_COOKIE=true
BETTEROPTION_AUTH_INVITATION_HOURS=72
BETTEROPTION_AUTH_RECOVERY_MINUTES=60
BETTEROPTION_AUTH_RATE_LIMIT_ATTEMPTS=8
BETTEROPTION_AUTH_RATE_LIMIT_MINUTES=15
BETTEROPTION_AUTH_RATE_LIMIT_SECRET=replace-with-the-new-random-hex-value
BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=false
BETTEROPTION_APP_ENVIRONMENT=staging
BETTEROPTION_PUBLIC_BASE_URL=https://staging.betteroption.example
BETTEROPTION_OPERATOR_EMAILS=your-owner-email@example.com
```

Keep Cloudflare-header trust `false` while ports 80/443 on the origin accept
traffic from the Internet. The application will still throttle authentication;
it simply will not trust a forgeable visitor-IP header.

Every numeric price setting must contain a number. Blank values cause settings
validation to fail. Use an explicit `0` while a price is unknown:

```dotenv
BETTEROPTION_OPENAI_INPUT_COST_PER_MILLION_USD=0
BETTEROPTION_OPENAI_OUTPUT_COST_PER_MILLION_USD=0
BETTEROPTION_BRAVE_SEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_EXA_SEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_COMPANY_RESEARCH_ESTIMATED_COST_PER_CALL_USD=0
BETTEROPTION_GOOGLE_ROUTES_ESTIMATED_COST_PER_CALL_USD=0
```

Zero means unpriced, never free. Keep operation-count limits active even before
the monetary estimates are calibrated.

Do not set legal or operational readiness flags to `true` merely to unlock
invitations. Record them only after the corresponding work is actually complete.

Verify the secret file:

```sh
chmod 600 deploy/.env.staging
docker compose --env-file deploy/.env.staging config --quiet
```

## 6. Deploy migration-first

The packaged script builds the app, starts PostgreSQL, applies migration `0017`,
runs preflight, and replaces the services:

```sh
cd /srv/betteroption/app
bash deploy/scripts/deploy_staging.sh
```

Then verify:

```sh
docker compose --env-file deploy/.env.staging ps
docker compose --env-file deploy/.env.staging logs --tail=100 app
curl -fsS https://staging.betteroption.example/health/live
curl -fsS https://staging.betteroption.example/health/ready
```

Preflight warnings about zero prices and incomplete invitation readiness are
expected until the real values and reviews exist. A `FAIL` is not acceptable.

## 7. Staging smoke test

1. Sign in as the existing owner.
2. Open `/operations`; confirm the account shows **Verified**.
3. Confirm registration mode shows **Invite Only**.
4. In a private browser window, open `/register`; direct account creation must
   be unavailable.
5. Confirm existing Compass, Archive, Matching, application states, and Explore
   results remain intact.
6. Run one small extraction and Match workflow; inspect Operations for provider
   and background-task behavior.
7. Confirm Cloudflare still uses **Full (strict)** TLS.

Invitation creation stays disabled while readiness items are incomplete. That is
the correct safe state.

## 8. Test one invitation only after the gate is real

After legal review, processor review, incident plan, and the restore drill are
actually complete, set their four flags to `true`, redeploy, and create one
controlled internal test invitation in Operations.

Copy the one-time fragment link immediately and send it to the exact intended
email address through a trusted channel. Verify:

- it creates only that normalized email address;
- the resulting account is Verified;
- reopening the same link fails;
- the new account cannot access the owner's workspace or job URLs.

Issue a recovery link from Operations, reset the password, and confirm an older
session is signed out.

## 9. Roll back

If the app smoke test fails:

```sh
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging logs --tail=200 app db caddy
git log --oneline -5
```

Return source to the last accepted commit only after confirming that it can run
against migration `0017`. Do not delete tables or restore an older database for
a presentation-only defect. For a genuine data migration incident, stop writes
and restore the verified pre-deployment dump using the documented restore
procedure.

## 10. Next gate

Proceed to v0.7.1c only after staging is stable. That increment adds redacted
error reporting, service/disk/database/worker alerts, encrypted off-server
backup automation, and a documented restore drill.
