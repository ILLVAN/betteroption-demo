> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Netcup and Cloudflare staging runbook

This runbook creates a private staging origin for `betteroption.example`. It is
written for the invited alpha, not a public launch. Commands assume Ubuntu
24.04 LTS and the packaged single-node Compose topology.

## 1. Order the Netcup server

Start with:

- **Netcup VPS 500 G12**, x86, Nuremberg;
- Ubuntu 24.04 LTS;
- the standard IPv4 and IPv6 addresses;
- an SSH key at creation time;
- no paid Local Block Storage initially.

The alpha runs one Caddy edge, one FastAPI process with the durable in-process
worker, and PostgreSQL. Heavy search, language-model, and route work is
provider-side, so 4 GB RAM is a reasonable first measurement point for 10–30
invited testers. Measure memory, CPU, disk, latency, and provider concurrency
before resizing. The root NVMe is sufficient initially; same-host block storage
is not an off-site backup.

Record the server IPv4, IPv6, and the Netcup Server Control Panel access in the
operator password manager. Enable two-factor authentication on Netcup,
Cloudflare, GitHub, and every provider account.

## 2. Apply the Netcup firewall

Create an ingress policy for the server:

| Protocol | Port | Source | Purpose |
| --- | ---: | --- | --- |
| TCP | 22 | the operator's fixed administration IP | SSH |
| TCP | 80 | any | HTTP redirect and certificate validation |
| TCP | 443 | any | HTTPS |
| UDP | 443 | any | optional HTTP/3 |

Do not expose PostgreSQL `5432` or application port `8000`. Remove UDP 443 if
HTTP/3 is not wanted. If the operator IP changes, update the SSH rule before
ending the working session. Keep a Netcup console session available while
changing network controls.

## 3. Create and verify the deploy account

Connect as root using the SSH key:

```sh
ssh root@SERVER_IPV4
apt update
apt full-upgrade -y
apt install -y ca-certificates curl git ufw unattended-upgrades
adduser deploy
usermod -aG sudo deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
```

Open a second terminal and prove that `ssh deploy@SERVER_IPV4` and `sudo -v`
work before tightening SSH. Then set `/etc/ssh/sshd_config.d/99-betteroption.conf`:

```text
PasswordAuthentication no
PermitRootLogin prohibit-password
```

Validate and reload without closing the verified deploy session:

```sh
sudo sshd -t
sudo systemctl reload ssh
```

Add the host firewall as a second boundary, replacing `ADMIN_IP`:

```sh
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from ADMIN_IP to any port 22 proto tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable
sudo ufw status verbose
```

## 4. Install Docker from Docker's Ubuntu repository

Run as the deploy user:

```sh
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker deploy
```

Sign out and back in, then verify:

```sh
docker version
docker compose version
```

## 5. Add staging DNS at Cloudflare

In Cloudflare DNS for `betteroption.example`:

1. create an `A` record named `staging` pointing to the Netcup IPv4;
2. leave **Proxy status: DNS only** while the origin is first verified;
3. set a five-minute TTL during setup;
4. add an `AAAA` record only after IPv6 firewall and reachability are proven.

Do not change the apex domain yet. Staging and production should be separate
hostnames and secrets.

## 6. Copy the application and create server secrets

Use a read-only GitHub deploy key or another narrowly scoped repository
credential. Never put a personal token in the repository:

```sh
sudo mkdir -p /opt/betteroption
sudo chown deploy:deploy /opt/betteroption
git clone git@github.com:ILLVAN/betteroption.git /opt/betteroption
cd /opt/betteroption
cp deploy/.env.staging.example deploy/.env.staging
openssl rand -hex 32
chmod 600 deploy/.env.staging
```

Put the generated hexadecimal value in `POSTGRES_PASSWORD`. Fill:

- `SITE_ADDRESS=staging.betteroption.example`;
- `BETTEROPTION_PUBLIC_BASE_URL=https://staging.betteroption.example`;
- the owner's email in `BETTEROPTION_OPERATOR_EMAILS`;
- a separate server-side OpenAI project key;
- separate staging Brave, Exa, Google Routes, or OpenRouteService keys as used;
- current provider prices and conservative operation limits;
- real operator/legal details only after review.

Keep `BETTEROPTION_REGISTRATION_MODE=first_user` only until the owner account
exists. Do not copy the local `.env`, SQLite database, CVs, profiles, or API
keys from the development machine.

## 7. Run the preflight and deploy

Inspect the interpolated Compose model without printing the environment file:

```sh
cd /opt/betteroption
docker compose --env-file deploy/.env.staging config --quiet
docker compose --env-file deploy/.env.staging build app
docker compose --env-file deploy/.env.staging run --rm --no-deps \
  app python -m betteroption.deployment preflight
```

Resolve every `FAIL`. Record and assign every `WARN`; warnings about legal
review, processor review, the incident plan, or the restore drill prohibit user
invitations even though they do not prevent an internal staging deployment.

Deploy:

```sh
sh deploy/scripts/deploy_staging.sh
docker compose --env-file deploy/.env.staging ps
curl -fsS https://staging.betteroption.example/health/live
curl -fsS https://staging.betteroption.example/health/ready
```

Only Caddy publishes ports. The application and PostgreSQL remain on the private
Compose network.

## 8. Finish the Cloudflare edge

After direct HTTPS succeeds:

1. change the `staging` record to **Proxied**;
2. set SSL/TLS mode to **Full (strict)**;
3. enable **Always Use HTTPS**;
4. keep caching disabled for authenticated HTML and API responses;
5. postpone HSTS until HTTPS, rollback, and every required subdomain have been
   verified.

Cloudflare is the public reverse proxy, but Caddy still terminates a valid
origin certificate. Never choose Flexible SSL.

## 9. Bootstrap and lock registration

Create the first owner account through HTTPS. Then change:

```text
BETTEROPTION_REGISTRATION_MODE=disabled
```

Redeploy and confirm that a second unauthenticated visitor cannot register:

```sh
sh deploy/scripts/deploy_staging.sh
```

Invitation-only account creation, verified email, and recovery arrive in the
next gated increments. Until then, do not invite external testers.

## 10. Back up and prove restoration

Create a logical backup:

```sh
cd /opt/betteroption
sh deploy/scripts/backup_postgres.sh
```

Copy the dump and checksum to encrypted storage in a separate EU failure
domain. A Netcup snapshot or same-host volume is useful for recovery speed but
is not the only backup. Restore into a disposable database, verify the checksum,
sign-in boundary, account counts, and migration head, then set
`BETTEROPTION_BACKUP_RESTORE_TESTED=true`.

## 11. Routine deployment and rollback

Before an update:

```sh
cd /opt/betteroption
sh deploy/scripts/backup_postgres.sh
git fetch --tags origin
git status --short
git pull --ff-only
sh deploy/scripts/deploy_staging.sh
curl -fsS https://staging.betteroption.example/health/ready
```

Tag every accepted staging release. Roll back application source to the prior
tag only after checking whether the database migration is backward compatible.
Do not restore an older database merely to reverse presentation code.

## Invitation gate

External invitations require all of the following:

- reviewed operator information, Privacy Notice, Terms, and processor register;
- DPAs and subprocessor decisions for Netcup, Cloudflare, OpenAI, Brave, Exa,
  Google, and any mail/monitoring provider actually used;
- verified email, controlled invitations, recovery, throttling, CSRF and proxy
  review;
- uptime/error/disk/database/worker alerts with payload-redacted logs;
- encrypted off-server backups and a documented successful restore;
- tested account export and complete deletion;
- incident, support, and tester communication procedures;
- provider prices, caps, and cost alerts calibrated from staging.

This runbook is an engineering checklist, not legal advice.

