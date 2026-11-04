> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# v0.7.1b-legal: local-to-offline-staging and controlled relaunch

This runbook preserves the tested v0.7.1b deployment while keeping the public
alpha unavailable during legal/privacy completion.

## 0. Keep production unreachable

In Cloudflare DNS, record the current A-record name, IPv4 address, proxy status
and TTL, then delete only the A record for
`staging.betteroption.example`. Do not delete unrelated MX, TXT, CAA or apex
records.

On Netcup:

```bash
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging stop caddy app
docker compose --env-file deploy/.env.staging ps
```

Keep PostgreSQL running only if you need maintenance. Deleting DNS alone is not
an access control; stopping the web services prevents direct-IP/hosts-file
access.

## 1. Install and test the overlay on Windows

Place `betteroption_v0_7_1b_legal_compliance_baseline.zip` in Downloads, then:

```powershell
cd C:\projects\betteroption

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_latest_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\test_release.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_web.ps1
```

Expected package identity:

```text
0.7.1+b.legal
```

Review locally:

- `/legal/imprint`, `/legal/privacy`, `/legal/terms`, `/legal/ai`,
  `/legal/storage`;
- the AI notice before the first guided Compass answer;
- CV parse → local preview → specific OpenAI action → Review Tray;
- a CV containing an email, phone, exact address and apparent prohibited
  category;
- Account export/delete and existing matching/explore/archive pages.

The legal pages must still show a launch blocker until real facts and reviews
are complete.

## 2. Commit and push

```powershell
git status --short
git diff --stat
git add -A
git commit -m "Add v0.7.1b-legal compliance baseline"
git push origin main
git log -1 --oneline
```

Confirm GitHub shows the commit. Never commit `.env`, database files, CVs,
profiles, exports or backups.

## 3. Back up before the server pull

```bash
ssh wlb-alpha
cd /srv/betteroption/app

mkdir -p /srv/betteroption/backups
chmod 700 /srv/betteroption/backups

docker compose --env-file deploy/.env.staging exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | gzip > "/srv/betteroption/backups/before-v071b-legal-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"

ls -lh /srv/betteroption/backups/
```

Copy the backup to the reviewed encrypted off-server location. Do not treat a
same-server file as disaster recovery.

## 4. Pull while the web remains stopped

```bash
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging stop caddy app

git status --short
git fetch origin
git log --oneline HEAD..origin/main
git pull --ff-only
git log -1 --oneline
grep '^version' pyproject.toml
```

Expected:

```text
version = "0.7.1+b.legal"
```

## 5. Set the fail-closed staging configuration

Edit without printing secrets:

```bash
nano deploy/.env.staging
chmod 600 deploy/.env.staging
```

During legal work:

```dotenv
BETTEROPTION_REGISTRATION_MODE=invite_only

BETTEROPTION_LEGAL_OPERATOR_NAME=<REAL LEGAL NAME AND FORM>
BETTEROPTION_LEGAL_OPERATOR_ADDRESS=<COMPLETE SERVICE ADDRESS>
BETTEROPTION_LEGAL_CONTACT_EMAIL=<PUBLIC PRIVACY/LEGAL EMAIL>
BETTEROPTION_LEGAL_TERMS_VERSION=2026-07-29-draft
BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-07-29-draft

BETTEROPTION_LEGAL_REVIEW_COMPLETED=false
BETTEROPTION_PROCESSOR_REVIEW_COMPLETED=false
BETTEROPTION_INCIDENT_PLAN_READY=false
BETTEROPTION_BACKUP_RESTORE_TESTED=false

BRAVE_SEARCH_API_KEY=
EXA_API_KEY=
GOOGLE_ROUTES_API_KEY=
OPENROUTESERVICE_API_KEY=
BETTEROPTION_TRANSITOUS_ENABLED=false
BETTEROPTION_VALHALLA_ENABLED=false
BETTEROPTION_OSM_GEOCODER_ENABLED=false

BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=false
```

Numeric provider prices must contain `0` or a real number and must never be
blank. `0` means unknown/unpriced, never free.

Validate:

```bash
docker compose --env-file deploy/.env.staging config --quiet
```

## 6. Build, migrate and preflight without exposing the site

```bash
docker compose --env-file deploy/.env.staging build app retention
docker compose --env-file deploy/.env.staging up --detach --wait db

docker compose --env-file deploy/.env.staging run --rm --no-deps \
  --entrypoint python app -m betteroption.deployment migrate

docker compose --env-file deploy/.env.staging run --rm --no-deps \
  --entrypoint python app -m betteroption.deployment preflight

docker compose --env-file deploy/.env.staging run --rm --no-deps \
  --entrypoint python app -m betteroption.retention once

docker compose --env-file deploy/.env.staging stop app caddy retention backup-scheduler
docker compose --env-file deploy/.env.staging ps
```

Warnings and blocked invitations are expected. Do not run the full deploy script
yet because it starts the public web services.

## 7. Complete the offline launch record

Use `docs/archive/discontinued-product-planning/compliance/11-external-review-and-launch-record.md`. Obtain the real
operator facts and external review, execute and archive provider contracts,
archive a retention run plus Caddy/backup expiry evidence, complete a DSR dry
run, incident tabletop, encrypted backup restore and expiry test, and restrict
direct origin access.

Only then create final, non-draft document versions and set a flag to `true`
when its own evidence exists. Do not set all four together merely to silence
preflight.

## 8. Controlled relaunch

After every gate is complete:

1. Add back the Cloudflare proxied A record for
   `staging.betteroption.example` using the recorded Netcup IPv4 address.
2. Keep SSL/TLS at `Full (strict)`.
3. Deploy:

```bash
cd /srv/betteroption/app
bash deploy/scripts/deploy_staging.sh
```

4. Verify:

```bash
docker compose --env-file deploy/.env.staging ps
docker compose --env-file deploy/.env.staging logs --tail=100 app
docker compose --env-file deploy/.env.staging logs --tail=100 caddy

curl -fsS https://staging.betteroption.example/health/live
curl -fsS https://staging.betteroption.example/health/ready
```

5. In a private browser, verify direct registration is closed, legal pages have
   no placeholders/draft warning, the AI notice appears before processing, and
   no invitation can be created unless all readiness gates are complete.

Keep invitations unissued for an observation period after relaunch. Public
reachability is not itself permission to process external users' data.
