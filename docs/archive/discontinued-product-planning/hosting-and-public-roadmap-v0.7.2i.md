> **Discontinued product planning.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../README.md) for the portfolio overview.

# Private-alpha hosting decision — v0.7.2i

Status: architecture and capacity decision dated 5 August 2026. It does not
claim that a server was ordered, configured, or accepted. The executable first
deployment sequence is in
[`netcup-cloudflare-private-alpha-v0.7.2i.md`](../engineering-history/deployment/netcup-cloudflare-private-alpha-v0.7.2i.md).

## Decision

Order **Netcup VPS 1000 G12** for the private alpha, preferably with the optional
hourly billing if the checkout still offers it. The official snapshot
shows 4 shared x86 vCore, 8 GB ECC RAM, 256 GB NVMe, and €10.37/month including
19% German VAT. Verify the accepted checkout price, location, IPv4 treatment,
term, and cancellation date instead of treating this note as an order record.

The VPS 500 G12 remains a minimum owner-only rehearsal size. It is not the new
default: the extra €4.46/month for the 1000 gives PostgreSQL, the web process,
the dedicated task worker, Caddy, cloudflared, retention, and backup work useful
headroom without turning the alpha into an infrastructure project.

## Why not 2000, 4000, 8000, or AWS now?

| Option | Official snapshot | Decision |
| --- | --- | --- |
| Netcup VPS 500 G12 | 2 vCore, 4 GB, 128 GB, €5.91/month incl. VAT | Minimum rehearsal only |
| **Netcup VPS 1000 G12** | **4 vCore, 8 GB, 256 GB, €10.37/month incl. VAT** | **Private-alpha default** |
| Netcup VPS 2000 G12 | 8 vCore, 16 GB, 512 GB, €19.25/month incl. VAT | Upgrade only after measured pressure |
| Netcup VPS 4000 G12 | 12 vCore, 32 GB, 1 TB, €32.41/month incl. VAT | Out of scope |
| Netcup VPS 8000 G12 | 16 vCore, 64 GB, 2 TB, €47.95/month incl. VAT | Out of scope |
| AWS Lightsail public-IPv4 Linux | 2 vCPU/4 GB at $24/month or 2 vCPU/8 GB at $44/month, before any applicable German VAT | No automatic speed advantage for this alpha |

Sources: [Netcup VPS plans](https://www.netcup.com/en/server/vps) and
[AWS Lightsail pricing](https://aws.amazon.com/lightsail/pricing/).

Netcup documents an
[in-generation upgrade through the Customer Control Panel](https://www.netcup.com/en/helpcenter/documentation/general/instance-upgrade),
subject to availability. It restarts the VPS, begins a new minimum term/billing
period, and cannot be reversed as a downgrade, so it is an observed-capacity
decision rather than a casual resize toggle.

Explore runs many provider calls concurrently, but most elapsed time is external
network, actor, or model latency. All Jobs executes remotely on Apify and can
occupy most of its own bounded window. The app intentionally has one durable
task worker. More cores improve page responsiveness under overlap and reduce
memory pressure; they do not make a remote provider return twice as fast.

Do not raise Uvicorn worker count as a capacity shortcut. `v0.7.2i` separates
the web container from one durable queue worker so web restarts do not strand
work, but task concurrency remains intentionally bounded. Scale the worker
architecture before multiplying processes.

## Upgrade evidence

Remain on VPS 1000 until at least two observation windows show a material
constraint. Record:

- p50 and p95 application-route latency excluding provider wait pages;
- worker queue depth, oldest queued age, lease recovery count, and task duration;
- container RSS, host `free -h`, swap activity, OOM kills, and restart count;
- load average, sustained CPU, and CPU steal;
- PostgreSQL size, query latency, connection count, and backup duration;
- disk use and at least 25% free-space headroom;
- external-provider duration separately from local processing time.

VPS 2000 becomes reasonable when measured local contention—not an external API
wait—causes sustained high CPU/steal, swapping/OOM risk, unacceptable p95 page
latency, or queue lag. VPS 4000/8000 require a redesigned multi-worker/load
test and a user volume that the private alpha does not have.

## Reliability boundary

The deployment keeps Cloudflare Access in front of product login, Tunnel as
the only web ingress, no published app/database ports, a fresh PostgreSQL
database, and encrypted off-host backups with a timed restore drill. A larger
VPS does not replace those controls.

Local Windows development stays local with its own SQLite database. The server
starts from an empty PostgreSQL volume; local test personas, matches, CVs,
ratings, provider results, `.env`, and uploads are never transferred.

The first deployment is not accepted until the owner account is bootstrapped,
registration is switched to `invite_only`, Access rejects a non-member, direct
origin ports fail, the worker survives a web-container restart, cancellation
works, and a backup has been restored into an isolated verification database.
