> **Historical engineering record.** This document is retained from the discontinued MVP.
> Its release, launch, and future-work statements describe the original checkpoint.
> Start with the [technical documentation](../../../README.md) for the portfolio overview.

# Netcup + Cloudflare first private-alpha deployment — v0.7.2j

> **Superseded deployment identity.** `j` remains the accepted functional
> baseline, but it was not deployed. Use the otherwise equivalent current
> [`v0.7.2k` first-deploy runbook](netcup-cloudflare-private-alpha-v0.7.2k.md).

Status: operator runbook dated 5 August 2026. This is the first server deploy.
Neither `v0.7.2h` nor `v0.7.2i` was deployed. The server therefore starts with
a new PostgreSQL database and exactly zero application accounts. The local
Windows installation and the server installation remain separate.

This guide deliberately assumes that the operator has never administered a
Linux server before. Read a section completely, then copy one command at a
time. Do not copy the explanatory `$`, `PS>` or shell prompt from screenshots.
Stop at every **STOP gate**. A green container is not by itself permission to
invite testers.

The examples use:

- public application hostname: `alpha.betteroption.example`;
- server account: `wlb`;
- server directory: `/srv/betteroption/app`;
- release tag: `v0.7.2j`;
- placeholders such as `203.0.113.10`, `OWNER/REPOSITORY` and
  `owner@example.com` which **must** be replaced.

If another hostname is chosen, use that same exact hostname everywhere:
Cloudflare Access, Tunnel route, `SITE_ADDRESS`, and
`BETTEROPTION_PUBLIC_BASE_URL`.

## 0. What this deployment builds

The final request path is:

1. the tester opens `https://alpha.betteroption.example`;
2. Cloudflare Access checks that exact email address;
3. Cloudflare Tunnel carries the request outbound-to-outbound, without an open
   web port on the VPS;
4. Caddy forwards internally to the BetterOption web container;
5. BetterOption requires its own account and keeps account/persona data in
   PostgreSQL;
6. a separate worker container runs durable Explore/Match tasks;
7. a retention container and a local backup scheduler run separately.

Compose must publish **no** host port for the app, Caddy, Cloudflare metrics, or
PostgreSQL. Only SSH is reachable directly at the Netcup IP. Cloudflare Access
and the BetterOption login are two independent layers; passing Access does not
log a person into BetterOption.

Caddy HTTP access logging is deliberately disabled. Some manual-source rescue
links carry the original job URL in a query parameter, so a conventional
request-URI log would retain private job-search metadata. Caddy can still emit
runtime/error metadata; its **default runtime logger removes the complete
`request` object before encoding**, including URI and query string. Every
Compose service also uses Docker's `json-file` driver with a maximum of five
10 MB files. That is a finite **size-based** rotation, not a promised number of
days. Do not enable Caddy access logs or weaken the request filter without a new
adapted-JSON test and privacy review.

### Fixed first-alpha decisions

- VPS: Netcup VPS 1000 G12 or better, x86-64/amd64.
- OS for this guide: Ubuntu Server 24.04 LTS, minimal official image.
- Database: a new PostgreSQL volume; no local SQLite import.
- Source: the immutable private-GitHub tag `v0.7.2j`, checked against a commit
  ID recorded on Windows before deployment.
- GitHub credential: one repository-scoped, read-only deploy key generated on
  the server.
- Registration: `first_user` for one exact owner email, then immediately
  `invite_only`.
- Ingress: one Cloudflare Tunnel route protected by an Access application that
  already exists before the route.
- Runtime: one `app` container and one separate `worker` container. The hosted
  app must not also start an embedded worker.

Expected release identities are:

```text
Application/source: 0.7.2j
Python distribution: 0.7.2+j
Matching algorithm: matching-v0.7.2i
Database migration head: 0033_background_task_leases
Privacy draft: 2026-08-05-feedback-draft
```

The matching identifier deliberately remains `i`; `j` changes lifecycle/UI
behavior but not the scoring contract.

Never upload or copy the local `.env`, SQLite database, test personas, CVs,
job text, provider responses, uploads, sessions, or local backups to this VPS.

## 1. Prepare an operator record and password-manager entries

Create a private note in a password manager or encrypted operator vault. Do
not store it in the repository. Record the following non-secret facts as they
become known:

- Netcup contract/product, price including VAT, billing interval, minimum term,
  cancellation date, location and server identifier;
- Netcup IPv4 and IPv6 addresses;
- the chosen hostname;
- Cloudflare account, zone ID, Access application ID and Tunnel ID;
- Netcup SSH host-key fingerprint verified through the SCP console;
- Windows operator public-key fingerprint;
- GitHub deploy-key fingerprint;
- exact `v0.7.2j` commit ID and release ZIP SHA-256 from the release handoff;
- deployed container image IDs from `docker compose images`;
- backup/restore drill date, dump checksum and off-server location;
- primary and recovery operators.

Create separate password-manager entries for:

- Netcup Customer Control Panel/Server Control Panel login;
- Cloudflare login and recovery codes;
- the Windows SSH-key passphrase;
- the Linux root console password used only through Netcup Screen/VNC;
- the Linux `wlb` user's local sudo password;
- the BetterOption owner password;
- PostgreSQL password;
- BetterOption authentication rate-limit secret;
- backup-encryption passphrase;
- provider API keys, each separately.

Do not reuse any of these values. Never paste a private key, `.env`, Tunnel
token, database password, API key, invitation link or recovery link into chat,
GitHub issues, screenshots or support tickets.

**STOP gate 1:** continue only when the final `v0.7.2j` commit/tag and release
hash have been delivered and pushed to the private GitHub repository. Do not
deploy a working tree, moving branch, draft ZIP, or untagged commit.

## 2. Put the domain on Cloudflare without breaking existing email

Skip only the nameserver-change subsection if the domain already shows
**Active** in the same Cloudflare account. A Cloudflare Tunnel public hostname
requires an active Cloudflare zone.

### 2.1 Inventory the domain before changing anything

At the current DNS provider/registrar, export or screenshot every existing DNS
record. Pay particular attention to:

- `MX` records used by email or email forwarding;
- SPF, DKIM and DMARC `TXT` records;
- verification `TXT`/`CNAME` records;
- any existing apex, `www`, mail or other application records;
- whether DNSSEC is currently enabled and which DS record is at the registrar.

Cloudflare's automatic scan is not guaranteed to find every record. Losing an
MX or TXT record can break email even though the new alpha subdomain works.
Cloudflare documents the full-zone process and this record review in its
[authoritative DNS setup guide](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/).

### 2.2 Add the apex domain to Cloudflare

1. Sign in to the Cloudflare dashboard and enable MFA; store the recovery
   codes outside the VPS.
2. Open **Domains** and select **Onboard a domain**.
3. Enter only the apex, for example `betteroption.example`, not
   `alpha.betteroption.example`.
4. Select the intended Cloudflare plan.
5. Let Cloudflare scan the records.
6. Compare the result line by line with the inventory from 2.1. Add every
   missing mail/verification record before continuing.
7. Mail records must remain **DNS only**. Never proxy an SMTP/mail host through
   the orange cloud.

Do **not** create an `A` or `AAAA` record from the alpha hostname to the Netcup
IP. The Tunnel route will create the required proxied DNS record later. A
direct origin record would disclose a path that this architecture intentionally
does not use.

### 2.3 Change authoritative nameservers safely

1. If DNSSEC is active at the registrar, turn it off **before** changing
   nameservers. Cloudflare warns that changing nameservers with the old DS
   record active can make the domain unreachable.
2. In Cloudflare's zone overview, copy the two assigned Cloudflare nameservers.
3. At the domain registrar, replace the existing authoritative nameservers with
   exactly those two values. Do not add them as ordinary NS records inside the
   old DNS zone.
4. Return to Cloudflare and wait until the zone status is **Active**.
5. Test the existing website and email/forwarding before proceeding.

From Windows PowerShell, replace the domain if necessary:

```powershell
Resolve-DnsName -Type NS betteroption.example
Resolve-DnsName -Type MX betteroption.example
Resolve-DnsName -Type TXT betteroption.example
```

The NS output must contain the two assigned Cloudflare nameservers. Compare MX
and relevant TXT results with the inventory.

After the zone is active and ordinary DNS/email tests pass, enable DNSSEC in
Cloudflare under the zone's DNS settings, copy Cloudflare's new DS values to the
registrar, and wait for Cloudflare to show DNSSEC active. Do not reuse the old
provider's DS record. See Cloudflare's
[DNSSEC procedure](https://developers.cloudflare.com/dns/dnssec/).

**STOP gate 2:** Cloudflare must show the zone as Active, existing mail must
still work, and no alpha `A`/`AAAA` record may point at the Netcup origin.

## 3. Create a dedicated Windows SSH key

This key is for the human operator connecting from Windows to Netcup. It is not
the GitHub deploy key; the latter will be created separately on the VPS.

### 3.1 Check/install the Windows OpenSSH client

Open **PowerShell as Administrator** and run:

```powershell
Get-WindowsCapability -Online | Where-Object Name -Like 'OpenSSH.Client*'
```

If `State` is `Installed`, close the administrator window and continue in a
normal PowerShell window. If it is `NotPresent`, still in the administrator
window run:

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

Microsoft documents the Windows client and key tools in
[OpenSSH for Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-overview)
and its
[key-management guide](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement).

### 3.2 Generate the key without overwriting another key

Open a normal PowerShell window:

```powershell
$NetcupKey = Join-Path $env:USERPROFILE '.ssh\wlb_netcup_ed25519'
New-Item -ItemType Directory -Force (Split-Path $NetcupKey) | Out-Null

if (Test-Path $NetcupKey) {
    throw "STOP: $NetcupKey already exists. Do not overwrite it."
}

ssh-keygen.exe -t ed25519 -a 100 -C 'wlb-netcup-operator-2026' -f $NetcupKey
```

When prompted, enter a strong key passphrase twice. The typing is intentionally
not displayed. Do not use an empty passphrase for this human operator key.

Confirm the pair and print only the safe public information:

```powershell
Get-Item $NetcupKey, "$NetcupKey.pub"
ssh-keygen.exe -lf "$NetcupKey.pub"
Get-Content "$NetcupKey.pub"
```

The `.pub` line may be copied to Netcup. The file without `.pub` is the private
key and must never be displayed or uploaded.

Back up the private key and its passphrase in an encrypted location. Losing
both the key and Netcup console access can lock out the server.

## 4. Order and install the Netcup VPS

At checkout, verify the actual VAT-inclusive price, VPS model/resources,
datacenter, IPv4/IPv6 allocation, billing term, minimum term and cancellation
date. This guide uses VPS 1000 G12; buying more cores does not remove external
provider/model latency.

Netcup sends separate emails for the Customer/Server Control Panels and the
server. Change the initial SCP password immediately to a unique value. Netcup's
[first-use guide](https://www.netcup.com/en/helpcenter/documentation/server/accessing-server)
explains the SCP, initial server details and the emergency Screen/VNC console.

### 4.1 Save the public SSH key in SCP

1. Sign in to the Netcup Server Control Panel (SCP).
2. Select the new server.
3. Open **Options** and the SSH-key management area (the precise label may vary
   slightly).
4. Add a key named `wlb-netcup-operator-2026`.
5. Paste the one-line contents of `wlb_netcup_ed25519.pub`, never the private
   file.
6. Compare the fingerprint shown in SCP, if present, with the Windows
   `ssh-keygen -lf` output.

Netcup's published
[SCP SSH-key walkthrough](https://community.netcup.com/en/tutorials/sshkey-setup-image-scp)
shows this key-to-image workflow.

### 4.2 Install Ubuntu 24.04 LTS

This reinstallation destroys any existing disk content. It is authorized here
only because this is a newly ordered, intentionally empty VPS.

1. In SCP open the server's **Media → Images** area.
2. Choose the official **Ubuntu Server 24.04 LTS**, amd64/x86-64, minimal image.
3. Assign the saved SSH public key to the installation.
4. Choose the normal full-disk/default partition option so the root filesystem
   uses the intended VPS disk. Do not knowingly retain Netcup's small initial
   partition layout.
5. Confirm installation and wait until SCP reports the server running.
6. Record the assigned IPv4 and IPv6 addresses.
7. Keep the SCP Screen/VNC console available throughout hardening.

Do not install Plesk, a web-hosting panel, Docker from a marketplace image, or
an unofficial appliance.

## 5. Verify the server's SSH host key out of band

Never accept a first-contact SSH fingerprint merely because a dialog appeared.
Obtain it through Netcup's independent Screen/VNC console first.

### 5.1 Read the fingerprint in the SCP console

Open **Screen** for the server, log in as `root`, and run:

```sh
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Record the complete `SHA256:...` value in the operator record.

### 5.2 Make the first Windows connection

In normal Windows PowerShell:

```powershell
$ServerIp = '203.0.113.10'
$NetcupKey = Join-Path $env:USERPROFILE '.ssh\wlb_netcup_ed25519'

if ($ServerIp -eq '203.0.113.10') {
    throw 'STOP: replace the documentation IP with the real Netcup IPv4 address.'
}

ssh.exe -o IdentitiesOnly=yes -i $NetcupKey "root@$ServerIp"
```

At the first connection prompt, compare the displayed ED25519 fingerprint with
the SCP-console fingerprint character for character. Type `yes` only if they
match.

Immediately replace Netcup's emailed Linux root password with a unique
break-glass console password:

```sh
passwd
```

Enter the new value twice and store it in the password manager. This is not the
SCP account password, SSH-key passphrase, or later `wlb` sudo password. Root SSH
will be disabled below, but the root password remains the recovery credential
for Netcup Screen/VNC.

If the key was not injected, do not disable authentication yet. Use the
one-time root password from Netcup only after the host fingerprint is verified,
or use the SCP console to add the public key. Never send that password anywhere.

If the server was deliberately reinstalled and Windows reports a changed key,
first obtain the new fingerprint from SCP Screen. Only after that independent
verification remove the old entry and reconnect:

```powershell
ssh-keygen.exe -R $ServerIp
```

An unexpected changed host key on a server that was not reinstalled is a stop
condition, not a nuisance to click away.

## 6. Create the `wlb` operator and prove sudo before lock-down

Keep the initial root SSH session and the SCP console open. In the root shell:

```sh
test -s /root/.ssh/authorized_keys
adduser wlb
usermod -aG sudo wlb
install -d -m 700 -o wlb -g wlb /home/wlb/.ssh
install -m 600 -o wlb -g wlb /root/.ssh/authorized_keys \
  /home/wlb/.ssh/authorized_keys
```

The first `test` must succeed. If it does not, the SCP image did not install the
public key: while root/password access is still available, create
`/root/.ssh/authorized_keys`, paste only the Windows `.pub` line, set directory
mode 700 and file mode 600, then prove a fresh root key login. Do not proceed to
password lock-down with no installed public key.

`adduser` asks for a local Linux password. Generate/store a unique sudo
password in the password manager. The optional full-name/phone fields may be
left blank by pressing Enter; answer `Y` when the summary is correct.

Do not use `adduser --disabled-password` here: Ubuntu's normal sudo policy asks
for the operator's local password, so a disabled-password account would not be
able to complete the following administration steps.

Open a **second** Windows PowerShell window and test:

```powershell
$ServerIp = '203.0.113.10'
$NetcupKey = Join-Path $env:USERPROFILE '.ssh\wlb_netcup_ed25519'
ssh.exe -o IdentitiesOnly=yes -i $NetcupKey "wlb@$ServerIp"
```

Inside that second session:

```sh
id
sudo -v
sudo whoami
```

Expected results:

- `id` includes group `sudo`;
- `sudo -v` accepts the new local password;
- `sudo whoami` prints `root`.

Do not proceed until all three are true.

## 7. Patch Ubuntu, set time, and configure the host firewall

All commands in this section run in the `wlb` session.

### 7.1 Set hostname, timezone and synchronized time

```sh
sudo hostnamectl set-hostname betteroption-alpha
grep -n '^127\.0\.1\.1' /etc/hosts || true
sudo timedatectl set-timezone Europe/Berlin
sudo timedatectl set-ntp true
hostnamectl
timedatectl
```

If `/etc/hosts` contains a `127.0.1.1` line with the old hostname, edit it with
`sudo nano /etc/hosts` and replace only that old hostname with
`betteroption-alpha`. If no `127.0.1.1` line exists, add exactly
`127.0.1.1 betteroption-alpha` on a new line. Then verify:

```sh
hostname
getent hosts "$(hostname)"
```

The first command must print `betteroption-alpha`; the second must resolve that
same name locally. This avoids later `sudo: unable to resolve host` warnings.

The `timedatectl` output should eventually show the system clock synchronized.
Correct time matters for TLS, Cloudflare tokens, sessions, leases and backup
timestamps.

### 7.2 Install all current Ubuntu updates

```sh
sudo apt-get update
sudo apt-get full-upgrade --yes
sudo apt-get install --yes ca-certificates curl git jq openssl ripgrep ufw \
  unattended-upgrades update-notifier-common
```

Check whether a reboot is requested:

```sh
if [ -f /var/run/reboot-required ]; then
  echo 'A reboot is required before continuing.'
else
  echo 'No reboot is currently required.'
fi
```

If required, run `sudo reboot`, wait one minute, reconnect as `wlb`, and repeat
`sudo apt-get update` plus `sudo apt-get full-upgrade --yes` until no reboot is
pending.

Ubuntu includes daily security updates through `unattended-upgrades`. Confirm
the service/timers and keep automatic reboots disabled until an explicit
maintenance window exists:

```sh
systemctl status unattended-upgrades --no-pager
systemctl list-timers 'apt-daily*' --no-pager
sudo unattended-upgrade --dry-run --debug
```

Ubuntu documents the behavior and configuration in
[Automatic updates](https://documentation.ubuntu.com/server/how-to/software/automatic-updates/).
Third-party repositories, including Docker's repository, are not automatically
covered by Ubuntu's default origins; the maintenance section therefore includes
an explicit Docker update step.

### 7.3 Restrict inbound traffic with UFW

First find and validate the public IPv4 address of the Windows connection. In a
separate Windows PowerShell window run:

```powershell
$TraceLines = curl.exe -4 -s https://www.cloudflare.com/cdn-cgi/trace
$IpLine = $TraceLines | Where-Object { $_ -like 'ip=*' } | Select-Object -First 1
if (-not $IpLine) {
    throw 'STOP: Cloudflare trace returned no ip= line.'
}

$OperatorIpv4 = $IpLine.Substring(3).Trim()
$ParsedAddress = $null
if (-not [System.Net.IPAddress]::TryParse($OperatorIpv4, [ref]$ParsedAddress) -or
    $ParsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw "STOP: expected an IPv4 address, received '$OperatorIpv4'."
}

$OperatorIpv4
```

The last line must be a dotted IPv4 address such as `198.51.100.24`, never an
IPv6 address containing colons. Copy that address only. Back on the server,
first inspect whether UFW is already active:

```sh
sudo ufw status verbose
```

On the new official image it should say `Status: inactive`. If it is already
active, stop and inspect its numbered rules through the still-open SSH and
Netcup Screen sessions before changing defaults; do not assume the following
fresh-firewall sequence is safe. When it is inactive, replace the example:

```sh
OPERATOR_IPV4='198.51.100.24'
test "$OPERATOR_IPV4" != '198.51.100.24'
case "$OPERATOR_IPV4" in
  ''|*[!0-9.]*) echo 'STOP: OPERATOR_IPV4 is not dotted IPv4.' >&2; exit 1 ;;
esac
OPERATOR_CIDR="${OPERATOR_IPV4}/32"

sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from "$OPERATOR_CIDR" to any port 22 proto tcp \
  comment 'WorkLifeBalance operator SSH'
sudo ufw show added
sudo ufw enable
sudo ufw status verbose
```

Before `ufw enable`, `ufw show added` must show port 22 allowed from the exact
IPv4 plus `/32` printed by PowerShell. If it does not, stop and correct the rule
while UFW is still disabled. UFW warns that enabling a firewall can disrupt
SSH. Type `y` only after that source-limited rule is visible and the Netcup
Screen recovery console is available.

Expected: one inbound SSH rule limited to the operator IPv4; no inbound rule for
80, 443, 2000, 5432 or 8000. UFW should report IPv6 enabled but no public IPv6
allow rule for those ports.

Residential public IPs can change. If that happens, use Netcup Screen/VNC to
replace the old `/32` rule with the new verified source address. Do not reopen
password SSH to the world. Keep the console recovery path tested.

Open a **third** Windows terminal and prove a fresh `wlb` SSH login still works
through UFW before changing sshd.

## 8. Disable root/password SSH only after the second login works

Ubuntu supports configuration snippets under `/etc/ssh/sshd_config.d`. In the
working `wlb` session run:

```sh
sudo nano /etc/ssh/sshd_config.d/10-worklifebalance.conf
```

Enter exactly:

```text
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
X11Forwarding no
AllowUsers wlb
```

In Nano, save with `Ctrl+O`, press Enter, then exit with `Ctrl+X`. Validate
before reloading:

```sh
sudo sshd -t
sudo systemctl reload ssh
sudo systemctl status ssh --no-pager
```

`sudo sshd -t` must print nothing and exit successfully. If it prints an error,
fix the file while the existing session remains open; do not reload.

Open one more new PowerShell window and verify `wlb` key login again. Also
confirm that a root login is refused:

```powershell
$ServerIp = '203.0.113.10'
$NetcupKey = Join-Path $env:USERPROFILE '.ssh\wlb_netcup_ed25519'
ssh.exe -o IdentitiesOnly=yes -i $NetcupKey "wlb@$ServerIp"
ssh.exe -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no -o IdentitiesOnly=yes -i $NetcupKey "root@$ServerIp"
```

The first must work; the second must fail. Only now close the original root
session. Keep the Netcup Screen console as the break-glass path. Ubuntu's
[OpenSSH server guide](https://ubuntu.com/server/docs/how-to/security/openssh-server/)
documents the snippet mechanism.

Optional Windows convenience: create or edit
`$env:USERPROFILE\.ssh\config` with Notepad:

```text
Host betteroption-alpha
    HostName 203.0.113.10
    User wlb
    IdentityFile C:/Users/YOUR-WINDOWS-USER/.ssh/wlb_netcup_ed25519
    IdentitiesOnly yes
```

After replacing the IP and Windows username, `ssh betteroption-alpha` uses the
same key. Do not put a password in this file.

## 9. Install Docker Engine and Compose from Docker's Ubuntu repository

Do not use `curl | sh`, Ubuntu's `docker.io`, a Snap package, Docker Desktop, or
the legacy standalone `docker-compose` binary on this server. Docker's current
[Ubuntu installation guide](https://docs.docker.com/engine/install/ubuntu/)
uses the official apt repository:

```sh
docker_conflicts="$(dpkg --get-selections docker.io docker-compose \
  docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc \
  2>/dev/null | cut -f1)"
if [ -n "$docker_conflicts" ]; then
  # The expansion is deliberately unquoted: dpkg returned a whitespace-separated
  # list of package names, never user input.
  sudo apt-get remove --yes $docker_conflicts
else
  echo 'No conflicting Docker packages are installed.'
fi

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update
sudo apt-get install --yes docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker version
sudo docker compose version
```

Add only the trusted operator to Docker's group:

```sh
sudo usermod -aG docker wlb
```

Membership in `docker` is root-equivalent. Never add an app user or tester to
this group. Log out of SSH completely, reconnect as `wlb`, then verify commands
work without `sudo`:

```sh
id
docker version
docker compose version
docker run --rm hello-world
```

Docker warns that published container ports can bypass UFW because Docker
routes them before UFW's normal chains. This repository avoids that boundary by
having no Compose `ports:` entries. Never add a temporary `8000:8000`,
`5432:5432`, `80:80`, `443:443` or metrics mapping. See Docker's
[firewall behavior](https://docs.docker.com/engine/network/packet-filtering-firewalls/).

## 10. Create the Cloudflare Access wall before any Tunnel route

A Tunnel route without Access would publish the application to the Internet.
Cloudflare explicitly recommends creating Access first. The authoritative flow
is [Publish a self-hosted application](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/).

### 10.1 Create the Zero Trust organization and login method

1. In Cloudflare open **Zero Trust**.
2. If prompted, choose a unique team name and complete the Zero Trust account
   setup.
3. Open **Integrations → Identity providers**.
4. For this small external alpha, add **One-time PIN** and save it.

As of June 2026, new Zero Trust accounts use Cloudflare's own identity provider
by default; OTP is no longer necessarily preconfigured. The explicit steps are
in Cloudflare's
[One-time PIN guide](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/).

### 10.2 Create the exact-host Access application

1. Go to **Zero Trust → Access controls → Applications**.
2. Select **Create new application**.
3. Select **Self-hosted and private**.
4. Select **Add public hostname**.
5. Name it `WorkLifeBalance private alpha`.
6. Enter only `alpha.betteroption.example`, with no wildcard and all paths.
7. Create an Access policy named `private-alpha-exact-emails`:
   - Action: **Allow**;
   - Include selector: **Emails**;
   - Value: the owner's exact normalized email address;
   - no `Everyone`, no email-domain rule, no `Bypass`.
8. Select One-time PIN as the allowed identity provider.
9. Choose a short application session such as eight hours.
10. Save/create the Access application.

An Access application is deny-by-default, but a broad Allow or Bypass policy
defeats that property. With multiple exact emails, each Include value is an OR;
only list people intentionally admitted to this alpha.

If those identities already exist in the Cloudflare Zero Trust user registry,
use the policy tester with the exact owner email and a non-member identity. The
owner must match the Allow policy; the non-member must not. In a completely new
Zero Trust account, the tester may have no authenticated user identity to test
yet; do not add a broad rule to work around that. Record the static policy
review now and perform the mandatory live owner/non-member tests in section 20
as soon as the protected route exists. Later, add a tester's exact email to
Access **before** sending that person a BetterOption invitation.

Do not create the Tunnel public-hostname route yet.

**STOP gate 3:** the exact-host Access application exists with only the intended
exact-email Allow entry and no Bypass/Everyone rule, and there is still no
public Tunnel route. If registered identities were available, their policy
tests must also have passed. The live owner/non-member test remains mandatory
at STOP gate 4.

## 11. Record the immutable Git release on Windows

In the local Windows repository, after the final release commit/tag has been
pushed, run:

```powershell
Set-Location C:\projects\betteroption
$ReleaseTag = 'v0.7.2j'

git fetch origin --tags --prune
git status --short
$ReleaseCommit = (git rev-list -n 1 $ReleaseTag).Trim()
$ReleaseCommit
git show --no-patch --decorate --oneline $ReleaseTag
git ls-remote --exit-code --tags origin "refs/tags/$ReleaseTag" "refs/tags/$ReleaseTag^{}"
```

`git status --short` must be empty. Record `$ReleaseCommit` in the operator
record. Confirm GitHub visibly shows tag `v0.7.2j`. If a final ZIP was supplied,
also verify and record its handoff hash:

```powershell
Get-FileHash "$env:USERPROFILE\Downloads\betteroption_v0_7_2j.zip" -Algorithm SHA256
```

Do not proceed if the tag, commit or ZIP hash differs from the final release
handoff.

## 12. Give the VPS read-only access to the private GitHub repository

Generate this second key **on the VPS as `wlb`**. It grants access to one
repository and is not reused for Netcup login.

### 12.1 Generate the repository deploy key

```sh
install -d -m 700 /home/wlb/.ssh
test ! -e /home/wlb/.ssh/betteroption_github
ssh-keygen -t ed25519 -C 'betteroption-netcup-readonly-2026' \
  -f /home/wlb/.ssh/betteroption_github -N ''
chmod 600 /home/wlb/.ssh/betteroption_github
chmod 644 /home/wlb/.ssh/betteroption_github.pub
ssh-keygen -lf /home/wlb/.ssh/betteroption_github.pub
cat /home/wlb/.ssh/betteroption_github.pub
```

The empty passphrase is intentional only for this non-human, read-only,
single-repository credential. Its private file remains mode 600 on the server.
Record its fingerprint.

### 12.2 Add only the public key in GitHub

1. Open the private GitHub repository.
2. Go to **Settings → Deploy keys → Add deploy key**.
3. Title: `Netcup private alpha read-only`.
4. Paste the one-line `.pub` output.
5. Leave **Allow write access** unchecked.
6. Select **Add key**.

GitHub documents that deploy keys are repository-scoped and read-only by
default in [Managing deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys).

### 12.3 Pin GitHub's host key before connecting

Do not blindly accept whatever `ssh-keyscan` returns. Fetch it to a temporary
file, print its fingerprint, and compare with GitHub's official
[SSH key fingerprint page](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints/):

```sh
ssh-keyscan -t ed25519 github.com 2>/dev/null > /tmp/github-ed25519-hostkey
ssh-keygen -lf /tmp/github-ed25519-hostkey
```

At the date of this runbook, GitHub documents the Ed25519 fingerprint as:

```text
SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU
```

Check the official page at deployment time. If it differs, stop and investigate;
do not append the key. If it matches:

```sh
touch /home/wlb/.ssh/known_hosts
chmod 600 /home/wlb/.ssh/known_hosts
cat /tmp/github-ed25519-hostkey >> /home/wlb/.ssh/known_hosts
rm /tmp/github-ed25519-hostkey
```

Create a dedicated SSH alias:

```sh
nano /home/wlb/.ssh/config
```

Enter:

```text
Host github-betteroption
    HostName github.com
    User git
    IdentityFile /home/wlb/.ssh/betteroption_github
    IdentitiesOnly yes
    StrictHostKeyChecking yes
```

Save, exit, then:

```sh
chmod 600 /home/wlb/.ssh/config
ssh -T github-betteroption
```

GitHub normally prints a successful-authentication/no-shell message and exits
with status 1 because it does not provide an interactive shell. That message is
success; a host-key warning, password request or `Permission denied` is not.

## 13. Clone and pin exactly `v0.7.2j`

Create the application parent directory:

```sh
sudo install -d -m 0750 -o wlb -g wlb /srv/betteroption
```

Replace `OWNER/REPOSITORY` with the private GitHub path, then clone:

```sh
git clone --filter=blob:none \
  git@github-betteroption:OWNER/REPOSITORY.git \
  /srv/betteroption/app

cd /srv/betteroption/app
git fetch origin --tags --force --prune
git switch --detach v0.7.2j
git status --short
git rev-list -n 1 v0.7.2j
git tag --points-at HEAD
```

Compare the server's `git rev-list` output with `$ReleaseCommit` recorded on
Windows. `git status --short` must be empty and `git tag --points-at HEAD` must
include `v0.7.2j`.

Do not run `git pull` on a deployment tag, do not deploy `main`, and do not
give the deploy key write access.

Basic source checks:

```sh
test -f compose.yaml
test -f Dockerfile
test -f deploy/.env.staging.example
test -f deploy/scripts/deploy_staging.sh
git check-ignore .env deploy/.env.staging deploy/cloudflared-token \
  local-data local-backups deploy/backups uploads
git ls-files .env deploy/.env.staging deploy/cloudflared-token \
  local-data local-backups deploy/backups uploads
```

The final `git ls-files` command must print nothing.

## 14. Create server-only directories and `.env`

Everything in this section stays on the VPS and is ignored by Git.

```sh
cd /srv/betteroption/app
test ! -e deploy/.env.staging
test ! -e deploy/cloudflared-token
install -d -m 700 deploy/backups
cp deploy/.env.staging.example deploy/.env.staging
chmod 600 deploy/.env.staging
```

Generate two independent URL-safe values. Copy each output directly into the
password manager and then into the appropriate `.env` field; do not reuse one:

```sh
openssl rand -hex 32
openssl rand -hex 32
```

Edit with:

```sh
nano deploy/.env.staging
```

### 14.1 Values that must be changed for the first owner rehearsal

Use the real hostname/email and the two different generated values:

```dotenv
SITE_ADDRESS=alpha.betteroption.example
BETTEROPTION_PUBLIC_BASE_URL=https://alpha.betteroption.example
POSTGRES_DB=betteroption
POSTGRES_USER=betteroption
POSTGRES_PASSWORD=<first-64-character-hex-value>
BETTEROPTION_AUTH_RATE_LIMIT_SECRET=<second-64-character-hex-value>

BETTEROPTION_AUTH_MODE=accounts
BETTEROPTION_REGISTRATION_MODE=first_user
BETTEROPTION_AUTH_SECURE_COOKIE=true
BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=false
BETTEROPTION_OPERATOR_EMAILS=owner@example.com
BETTEROPTION_APP_ENVIRONMENT=staging

BETTEROPTION_BACKGROUND_WORKER_ENABLED=false
BETTEROPTION_BACKGROUND_WORKER_EXTERNAL=true
BETTEROPTION_EMPLOYER_JOB_POSTING_ENABLED=false

BACKUP_RETENTION_DAYS=14
BACKUP_INTERVAL_SECONDS=86400
```

Rules:

- `SITE_ADDRESS` is only the hostname, without `https://` or a path.
- `BETTEROPTION_PUBLIC_BASE_URL` is the exact HTTPS origin, without credentials.
- The owner email must exactly match both the Access Allow email and the email
  later entered on `/register`.
- Keep the hexadecimal PostgreSQL password. Compose embeds it in a SQLAlchemy
  URL, so arbitrary URL punctuation is deliberately avoided.
- Do not put spaces around `=`.
- Do not reuse the local `.env`.

For the owner-only infrastructure rehearsal, it is valid to leave provider keys
blank and review flags false. Replace example placeholders such as
`OPENAI_API_KEY=replace-...` with either a real restricted server-side project
key or an empty value; never leave a fake key that appears configured.

Keep these fail-closed until the underlying work is genuinely complete:

```dotenv
BETTEROPTION_LEGAL_REVIEW_COMPLETED=false
BETTEROPTION_PROCESSOR_REVIEW_COMPLETED=false
BETTEROPTION_INCIDENT_PLAN_READY=false
BETTEROPTION_BACKUP_RESTORE_TESTED=false
BETTEROPTION_APIFY_ALL_JOBS_HOSTED_ENABLED=false
BETTEROPTION_EMPLOYER_JOB_POSTING_ENABLED=false
```

Do not turn a flag true simply to remove a warning. In hosted mode, incomplete
processor review intentionally blocks external providers, and invitation
creation intentionally remains locked until all four readiness gates pass.

When actual provider keys are added later:

- create restricted server/project credentials rather than copying broad
  personal development keys;
- fill the corresponding current cost values and daily/action limits;
- keep only reviewed providers enabled;
- preserve the All Jobs per-platform/readback/charge caps from the current
  `v0.7.2j` example;
- restart/recreate both `app` and `worker` through the deploy script.

Keep the reviewed Salary web-search content ceiling even while the provider is
disabled, and recheck it before enabling Salary research:

```dotenv
BETTEROPTION_SALARY_RESEARCH_SEARCH_CONTENT_TOKEN_CEILING=128000
```

This is the conservative total Responses web-search content-token ceiling for
one Salary batch, **not** an allowance for each tool call. Raising it is a cost
and data-minimisation change that requires a new provider-budget review.

Save Nano with `Ctrl+O`, Enter, and exit with `Ctrl+X`. Check without printing
secrets:

```sh
chmod 600 deploy/.env.staging
stat -c '%a %U:%G %n' deploy/.env.staging

if grep -qE 'replace-with|owner@example.com|alpha\.example\.com|staging\.worklifebalance\.ai' \
  deploy/.env.staging; then
  echo 'STOP: at least one documentation placeholder remains.'
else
  echo 'No standard deployment placeholder remains.'
fi

git check-ignore -v deploy/.env.staging deploy/backups
git status --short
```

Expected mode is `600`, owner/group `wlb:wlb`, the paths are ignored, and Git
status stays clean.

## 15. Create the remotely managed Tunnel, but still no route

1. In Cloudflare Zero Trust go to **Networks/Networking → Tunnels**.
2. Select **Create a tunnel** and choose the Cloudflared connector.
3. Name it `wlb-private-alpha`.
4. Choose the Docker connector instructions.
5. Cloudflare displays a long installation command containing a Tunnel token.
   Copy only the token value, not the `docker run` command.
6. Do not create the public-hostname route yet.

On the server:

```sh
cd /srv/betteroption/app
install -m 600 /dev/null deploy/cloudflared-token
nano deploy/cloudflared-token
```

Paste only the token on one line, save and exit. Then:

```sh
chmod 600 deploy/cloudflared-token deploy/.env.staging
test -s deploy/cloudflared-token
stat -c '%a %U:%G %n' deploy/cloudflared-token deploy/.env.staging
git check-ignore -v deploy/cloudflared-token
git status --short
```

Never print the token back to the terminal. If it is exposed, rotate it in
Cloudflare and replace this file before starting the connector. Cloudflare's
[remotely managed Tunnel guide](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)
is the authoritative dashboard reference.

## 16. Validate Compose without writing resolved secrets to disk

Run from the repository root:

```sh
cd /srv/betteroption/app

grep '^BETTEROPTION_REGISTRATION_MODE=first_user$' deploy/.env.staging
grep '^BETTEROPTION_BACKGROUND_WORKER_ENABLED=false$' deploy/.env.staging
grep '^BETTEROPTION_BACKGROUND_WORKER_EXTERNAL=true$' deploy/.env.staging
grep '^BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=false$' deploy/.env.staging
grep '^BETTEROPTION_LEGAL_PRIVACY_VERSION=2026-08-05-feedback-draft$' \
  deploy/.env.staging
grep '^BETTEROPTION_SALARY_RESEARCH_SEARCH_CONTENT_TOKEN_CEILING=128000$' \
  deploy/.env.staging

docker compose --env-file deploy/.env.staging config --quiet
docker compose --env-file deploy/.env.staging config --services
docker compose --env-file deploy/.env.staging config --images

docker compose --env-file deploy/.env.staging config --format json \
  | jq -e '[.services[] | (.ports // []) | .[]] | length == 0'
docker compose --env-file deploy/.env.staging config --format json \
  | jq -e '.services.worker.stop_grace_period == "20s"'
docker compose --env-file deploy/.env.staging config --format json \
  | jq -e '
      .services as $services
      | ($services | length) as $count
      | [
          $services[]
          | select(
              .logging.driver == "json-file"
              and .logging.options."max-size" == "10m"
              and .logging.options."max-file" == "5"
            )
        ]
      | length == $count
    '
```

Expected services are `db`, `migrate`, `app`, `worker`, `retention`, `caddy`,
`cloudflared`, `backup`, and `backup-scheduler`. All three `jq` commands must
print `true`: there are no published host ports, the worker has a 20-second stop
grace period, and **every resolved service** has `json-file`, `max-size: 10m`
and `max-file: 5`. This bounds local container output by size; it does not set a
time-based retention. `backup` is a tools-profile service and is not
long-running.

Do not save unrestricted `docker compose config` output: resolved environment
values can contain secrets. If troubleshooting requires such a file, use
`umask 077`, keep it local to the server, and delete it immediately afterward.

Inspect the effective source boundary:

```sh
rg -n 'ports:|expose:|stop_grace_period|TUNNEL_TOKEN|BETTEROPTION_DATABASE_URL' \
  compose.yaml
```

If `rg` is unavailable, use `grep -nE`. `compose.yaml` must have only internal
`expose` entries and no `ports:` entry.

## 17. Build, migrate and preflight before starting the public stack

Pull/build the images:

```sh
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging pull db caddy cloudflared \
  backup-scheduler
docker compose --env-file deploy/.env.staging build migrate app worker retention
```

Before any HTTP service starts, make the Caddy image adapt and validate the
mounted file, then inspect the **adapted JSON** rather than trusting Caddyfile
text or comments:

```sh
docker compose --env-file deploy/.env.staging run --rm --no-deps \
  --entrypoint caddy caddy \
  adapt --config /etc/caddy/Caddyfile --adapter caddyfile --validate --pretty \
  | jq -e '
      .logging.logs.default.encoder.format == "filter"
      and .logging.logs.default.encoder.fields.request.filter == "delete"
      and ([.apps.http.servers[] | has("logs")] | all(. == false))
    '
```

Expected: Caddy may print a harmless warning to stderr that this internal
server listens only on HTTP; `jq` must print `true`. The first two conditions
prove that the default runtime/error logger deletes the **entire** request
object before encoding. The final condition proves that no site HTTP access
logger was adapted. If the command, validation or JSON assertion fails, stop;
do not start Caddy or `cloudflared` and do not replace it with a textual `grep`.

Start PostgreSQL alone and wait for its health check:

```sh
docker compose --env-file deploy/.env.staging up --detach --wait db
docker compose --env-file deploy/.env.staging ps db
```

Run the one-shot migration:

```sh
docker compose --env-file deploy/.env.staging up --no-deps migrate
docker compose --env-file deploy/.env.staging ps --all migrate
docker compose --env-file deploy/.env.staging logs --tail=100 migrate
```

Expected: migration exits with code 0 and reports the schema current. Confirm
the deployed migration revision directly:

```sh
docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select version_num from alembic_version;"'
```

Compare the result with the `v0.7.2j` release handoff/release notes.
The expected single revision is `0033_background_task_leases`.

Run the secret-safe deployment preflight:

```sh
docker compose --env-file deploy/.env.staging run --rm --no-deps \
  --entrypoint python app -m betteroption.deployment preflight
```

Expected before owner creation:

- no `FAIL` line;
- PostgreSQL, HTTPS origin, secure cookie, separate auth secret and empty
  first-owner state pass;
- warnings about `first_user` and unfinished legal/processor/incident/restore
  work are expected and must remain honest.

If the result says `BLOCKED`, stop. Do not run migrations repeatedly, delete a
volume, or weaken a check to make the message disappear.

## 18. Start the private stack and prove the Tunnel connector healthy

Use the repository's reviewed deploy script:

```sh
cd /srv/betteroption/app
sh deploy/scripts/deploy_staging.sh
```

Then inspect all services:

```sh
docker compose --env-file deploy/.env.staging ps --all
docker compose --env-file deploy/.env.staging logs --tail=150 \
  app worker db caddy cloudflared retention backup-scheduler
docker compose --env-file deploy/.env.staging exec -T cloudflared \
  cloudflared tunnel ready
docker compose --env-file deploy/.env.staging images

docker compose --env-file deploy/.env.staging exec -T app python -c \
  "import betteroption; from importlib.metadata import version; from betteroption.results import CURRENT_MATCHING_ALGORITHM; from betteroption.settings import Settings; print(betteroption.__version__); print(version('betteroption')); print(CURRENT_MATCHING_ALGORITHM); print(Settings().legal_privacy_version)"
```

Expected:

- `db`, `app` and `cloudflared` healthy;
- `worker`, `retention`, `caddy`, and `backup-scheduler` running;
- `migrate` exited successfully;
- no restart loop;
- the app environment shows a separate external worker, never an embedded
  second worker;
- the worker's effective Compose stop grace is 20 seconds;
- every service's effective container output is size-rotated at five 10 MB
  `json-file` files;
- the adapted Caddy configuration has no HTTP access logger and its default
  runtime/error logger deletes the complete request object;
- the final command prints `0.7.2j`, `0.7.2+j`,
  `matching-v0.7.2i`, and `2026-08-05-feedback-draft` on separate lines.

Record `docker compose images` in the operator record. The source tag alone is
not a byte-identical container guarantee because several upstream image/base
tags are mutable.

At this point the Tunnel connector may be Healthy in Cloudflare, but there is
still intentionally no route and therefore no public application hostname.

## 19. Add the one protected public-hostname route

Only now, after Access exists and the connector is healthy:

1. In Cloudflare open `wlb-private-alpha`.
2. Add a **Published application** route.
3. Hostname: exactly `alpha.betteroption.example`.
4. Service type: `HTTP`.
5. Service URL: exactly `http://caddy:80`.
6. Enable **Protect with Access** so `cloudflared` validates the Access token.
7. Save.

Do not use `localhost`, `https://caddy`, `app:8000`, the Netcup IP, port 8000,
or a wildcard. In a full Cloudflare DNS setup the route creates the proxied DNS
record automatically. Do not add a second manual `A`/`AAAA` record.

In Cloudflare DNS verify one proxied alpha record associated with the Tunnel.
In Access verify the application still contains only the exact-email Allow
policy and no Bypass/Everyone rule.

If Access was accidentally omitted, immediately stop the connector while
correcting the Cloudflare configuration:

```sh
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging stop cloudflared
```

Restart it only after the Access application and **Protect with Access** are
confirmed:

```sh
docker compose --env-file deploy/.env.staging start cloudflared
```

## 20. Network and Access acceptance before owner registration

### 20.1 Test from an external Windows connection

Use the real values:

```powershell
$AlphaHost = 'alpha.betteroption.example'
$ServerIp = '203.0.113.10'

Resolve-DnsName $AlphaHost
curl.exe -I "https://$AlphaHost/"

22, 80, 443, 2000, 5432, 8000 | ForEach-Object {
    Test-NetConnection -ComputerName $ServerIp -Port $_ |
        Select-Object ComputerName, RemotePort, TcpTestSucceeded
}
```

Expected:

- DNS resolves through Cloudflare and does not disclose the Netcup origin IP;
- an unauthenticated HTTPS request is redirected/challenged/denied by
  Cloudflare Access, not served the BetterOption page directly;
- direct ports 80, 443, 2000, 5432 and 8000 are false;
- port 22 is true only from the operator's allowed source IP.

Repeat the direct-port checks for the Netcup IPv6 address if one is assigned.
Do not treat successful ping/ICMP as an exposed application port.

Open a private/incognito browser and try a non-member email at Access. It must
not receive application access. Cloudflare may display a generic “code sent”
message even for a denied address to avoid account enumeration; the actual
policy decision/log must be denied.

### 20.2 Test from the VPS

```sh
cd /srv/betteroption/app
sudo ufw status verbose
sudo ss -lntup
docker compose --env-file deploy/.env.staging ps
docker compose --env-file deploy/.env.staging port app 8000 || true
docker compose --env-file deploy/.env.staging port db 5432 || true
docker stats --no-stream
free -h
df -h
```

`ss` will show SSH listening, with UFW restricting who can reach it. It must not
show host listeners for the app, database, Caddy, or Cloudflare metrics. The two
`docker compose port` commands must not return a published host mapping.

### 20.3 Trust Cloudflare visitor headers only after origin isolation passes

With `BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=false`, authentication rate
limits use the immediate proxy peer and several testers can share one apparent
address. After every direct-origin test above has failed, change exactly this
line in `deploy/.env.staging`:

```dotenv
BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=true
```

Then recreate the services and preflight:

```sh
cd /srv/betteroption/app
grep '^BETTEROPTION_AUTH_TRUST_CLOUDFLARE_HEADERS=true$' deploy/.env.staging
sh deploy/scripts/deploy_staging.sh
docker compose --env-file deploy/.env.staging run --rm --no-deps \
  --entrypoint python app -m betteroption.deployment preflight
```

Repeat the Access and direct-origin checks. Set this value back to `false`
before introducing any direct listener or alternate proxy path; otherwise an
attacker on that path could forge visitor-address headers and evade the intended
authentication throttling.

**STOP gate 4:** owner Access works, non-member Access fails, all direct-origin
web/database/metrics ports fail, and all containers are stable.

## 21. Create exactly one owner, then close registration immediately

### 21.1 Create the owner through the browser

1. Open a new private/incognito browser window.
2. Visit `https://alpha.betteroption.example`.
3. Complete Cloudflare Access with the exact owner email.
4. BetterOption then shows its own login/register surface. Open `/register`.
5. Enter:
   - a unique display name of at most 32 characters;
   - the **same exact owner email** configured in
     `BETTEROPTION_OPERATOR_EMAILS`;
   - a unique BetterOption password of at least 10 characters;
   - the required age/Terms/Privacy confirmations.
6. Create the account once. Do not open two registration tabs.
7. Open `/operations`. Confirm the only account is the owner and its Workspace
   role is **Admin**.
8. In the account-access card, optionally set the owner's Alpha access to
   **Full alpha tester**, enter the current admin password, and save. Role and
   tester tier are separate.

The first owner claim is database-serialized, but any unexpected second account
or missing Admin role is still a stop condition.

### 21.2 Change `first_user` to `invite_only`

On the VPS:

```sh
cd /srv/betteroption/app
nano deploy/.env.staging
```

Change exactly:

```dotenv
BETTEROPTION_REGISTRATION_MODE=invite_only
```

Save, then redeploy and preflight:

```sh
grep '^BETTEROPTION_REGISTRATION_MODE=invite_only$' deploy/.env.staging
sh deploy/scripts/deploy_staging.sh
docker compose --env-file deploy/.env.staging run --rm --no-deps \
  --entrypoint python app -m betteroption.deployment preflight
```

Expected: preflight sees at least one persisted database Admin and registration
restricted to invitations. Warnings remain until their real gates are done.

In another private browser session, `/register` must no longer allow an
anonymous account. Existing owner login must still work.

If the browser session was lost before switching modes, log back in; do not
attempt to register the owner twice. If preflight reports a non-empty database
while mode is `first_user`, stop and inspect the existing account instead of
resetting PostgreSQL.

## 22. Verify `v0.7.2j` web/worker behavior end to end

Perform these checks with disposable owner data before inviting anyone.
Checks 2–8 need at least one deliberately reviewed and configured external
processor/provider. Hosted mode correctly blocks those calls while
`BETTEROPTION_PROCESSOR_REVIEW_COMPLETED=false`. If that review is not complete
yet, perform check 1, mark checks 2–8 **OPEN**, continue with the backup drill
and readiness work, and return here after the review and restricted server
credential are complete. Do not turn the flag true merely to make this test
run, and do not invite the recovery operator or a tester until every deferred
check has passed.

When the provider boundary is genuinely ready, redeploy both web and worker,
rerun preflight, and then run the whole list:

1. Confirm the application identifier is `0.7.2j`, the installed Python
   distribution is `0.7.2+j`, the migration is
   `0033_background_task_leases`, and Matching remains
   `matching-v0.7.2i`. The Privacy draft must display
   `2026-08-05-feedback-draft`.
2. Create a disposable persona and run one Explore search.
3. Confirm background progress moves through the bounded 0–94% running phase
   and does not sit at 0% for the entire operation.
4. While a disposable task runs, restart only the web process:

   ```sh
   cd /srv/betteroption/app
   docker compose --env-file deploy/.env.staging restart app
   ```

   Refresh the task page. The separate server worker must continue.
5. Start another disposable task and press **Abort task**. It must become a
   terminal cancelled state promptly; the `Cancelling…` state must not behave
   like a second clickable action, and a later retry must not resurrect it.
6. During another disposable task, restart only the worker:

   ```sh
   docker compose --env-file deploy/.env.staging restart --timeout 20 worker
   ```

   After the lease/recovery interval, work must safely resume or end honestly,
   not remain stale forever.
7. Paste one manual job, override its company name, and verify the job-card
   header updates. Every overridden automatic value must remain visible as gray
   strikethrough evidence.
8. From that manual job's detail page, start **Match this job only** and confirm
   only that job is evaluated.
9. Review server logs for unexpected tracebacks:

   ```sh
   docker compose --env-file deploy/.env.staging logs --since=30m app worker
   ```

   Do not paste a real job URL or query token into a log-search command. The
   invariant that Caddy cannot encode the HTTP request must be proven through
   the adapted-JSON assertion in section 17, not by deliberately generating a
   private URL and hoping it does not appear.

Do not use real CVs or private tester data for this infrastructure acceptance.

## 23. Create and verify the first database backup

The Compose scheduler creates same-host PostgreSQL dumps, but a same-host dump
is not disaster recovery. First verify the repository script, then create an
encrypted off-server copy and restore a copy into an isolated database.

This procedure protects the authoritative PostgreSQL data only. The repository
script does not archive the `app_data` volume (job/source reproducibility files),
the Caddy data volume, container images, `.env`, or Tunnel token. Server secrets
must be recoverable from the password manager and Tunnel credentials can be
rotated in Cloudflare. Do not describe a PostgreSQL dump as a full-server image.

### 23.1 Create/check an on-demand dump

```sh
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging run --rm backup \
  sh /scripts/backup_postgres.sh
ls -lah deploy/backups
docker compose --env-file deploy/.env.staging run --rm backup sh -c \
  'for checksum in /backups/betteroption-*.dump.sha256; do sha256sum -c "$checksum"; done'
```

Expected: a timestamped `.dump` and `.dump.sha256`, and checksum output `OK`.
The container may create mode-600 root-owned files; that is why the encrypted
export below uses `sudo` rather than weakening backup permissions.

### 23.2 Restore the newest dump into an isolated verification database

This does not overwrite production:

```sh
cd /srv/betteroption/app
latest_dump="$(find deploy/backups -maxdepth 1 -type f \
  -name 'betteroption-*.dump' -printf '%f\n' | sort | tail -n 1)"
test -n "$latest_dump"
printf 'Testing isolated restore of %s\n' "$latest_dump"

docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'dropdb --if-exists -U "$POSTGRES_USER" betteroption_restore_verify && createdb -U "$POSTGRES_USER" betteroption_restore_verify'

docker compose --env-file deploy/.env.staging run --rm \
  -e POSTGRES_DB=betteroption_restore_verify \
  -e ALLOW_RESTORE=true \
  -e RESTORE_FILE="/backups/$latest_dump" \
  backup sh /scripts/restore_postgres.sh

docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d betteroption_restore_verify -c "\\dt"'
docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d betteroption_restore_verify -c "select version_num from alembic_version;"'
```

Only after both queries succeed, remove the isolated verification database:

```sh
docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'dropdb --if-exists --force -U "$POSTGRES_USER" betteroption_restore_verify'
```

### 23.3 Encrypt and copy one dump off the VPS

Create a temporary export directory inaccessible to other Linux users:

```sh
install -d -m 700 /home/wlb/backup-export
cd /srv/betteroption/app
latest_dump="$(find deploy/backups -maxdepth 1 -type f \
  -name 'betteroption-*.dump' -printf '%f\n' | sort | tail -n 1)"
test -n "$latest_dump"
export_file="/home/wlb/backup-export/${latest_dump}.aes256"

sudo openssl enc -aes-256-cbc -salt -pbkdf2 -iter 600000 \
  -in "deploy/backups/$latest_dump" -out "$export_file"
sudo chown wlb:wlb "$export_file"
chmod 600 "$export_file"
sudo cat "deploy/backups/${latest_dump}.sha256"
sha256sum "$export_file"
```

OpenSSL prompts for the separate backup-encryption passphrase. Store it in the
password manager, not in a shell variable or command. Record the encrypted-file
SHA-256 and filename. Also record the first 64-character value printed from the
original `.dump.sha256`; it is the decrypted-dump checksum needed by the
off-site restore drill.

From Windows PowerShell, choose an encrypted/BitLocker-protected backup folder:

```powershell
$ServerIp = '203.0.113.10'
$NetcupKey = Join-Path $env:USERPROFILE '.ssh\wlb_netcup_ed25519'
$BackupFolder = 'D:\EncryptedBackups\WorkLifeBalance'
New-Item -ItemType Directory -Force $BackupFolder | Out-Null

scp.exe -o IdentitiesOnly=yes -i $NetcupKey "wlb@${ServerIp}:/home/wlb/backup-export/PASTE-EXACT-FILENAME.aes256" $BackupFolder

Get-FileHash (Join-Path $BackupFolder 'PASTE-EXACT-FILENAME.aes256') -Algorithm SHA256
```

The Windows hash must equal the server hash. Keep at least one further
independent encrypted location that is not the VPS and not the only Windows
disk. After the copy is verified, remove only the temporary encrypted export
from the VPS; the scheduled source dump remains:

```sh
rm -- /home/wlb/backup-export/PASTE-EXACT-FILENAME.aes256
```

### 23.4 Prove the off-server bytes can be decrypted

For a real disaster-recovery drill, copy the downloaded encrypted file back to
a separate input name, then decrypt and restore that copy rather than quietly
reusing the original server dump.

From Windows:

```powershell
$ServerIp = '203.0.113.10'
$NetcupKey = Join-Path $env:USERPROFILE '.ssh\wlb_netcup_ed25519'
$EncryptedBackup = 'D:\EncryptedBackups\WorkLifeBalance\PASTE-EXACT-FILENAME.aes256'

scp.exe -o IdentitiesOnly=yes -i $NetcupKey $EncryptedBackup "wlb@${ServerIp}:/home/wlb/backup-export/offsite-restore-input.aes256"
```

On the VPS, first prove that the uploaded encrypted bytes are the same bytes
whose hash was recorded before the Windows download. Replace the placeholder
with the recorded encrypted-file hash:

```sh
expected_encrypted_sha256='PASTE-RECORDED-ENCRYPTED-FILE-SHA256'
test "$expected_encrypted_sha256" != \
  'PASTE-RECORDED-ENCRYPTED-FILE-SHA256'
printf '%s  %s\n' "$expected_encrypted_sha256" \
  /home/wlb/backup-export/offsite-restore-input.aes256 | sha256sum -c -
```

The result must be `OK`. If it is not, stop and recopy the file. Do not try to
repair or restore mismatching bytes.

Now decrypt to a new exact temporary dump and compute its hash:

```sh
cd /srv/betteroption/app
restore_copy="offsite-restore-verify.dump"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 \
  -in /home/wlb/backup-export/offsite-restore-input.aes256 \
  -out "deploy/backups/$restore_copy"
sha256sum "deploy/backups/$restore_copy"
```

The decrypted hash must match the original unencrypted dump hash contained in
its `.dump.sha256` record. Create a checksum file using that verified hash.
Paste only the original 64-character dump hash:

```sh
original_dump_sha256='PASTE-ORIGINAL-DUMP-SHA256'
test "$original_dump_sha256" != 'PASTE-ORIGINAL-DUMP-SHA256'
printf '%s  /backups/%s\n' "$original_dump_sha256" "$restore_copy" \
  > "deploy/backups/${restore_copy}.sha256"

docker compose --env-file deploy/.env.staging run --rm backup sh -c \
  'sha256sum -c /backups/offsite-restore-verify.dump.sha256'
```

The checksum must again report `OK`. Restore these off-server bytes into a
second isolated database; the production database is not changed:

```sh
docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'dropdb --if-exists -U "$POSTGRES_USER" betteroption_offsite_restore_verify && createdb -U "$POSTGRES_USER" betteroption_offsite_restore_verify'

docker compose --env-file deploy/.env.staging run --rm \
  -e POSTGRES_DB=betteroption_offsite_restore_verify \
  -e ALLOW_RESTORE=true \
  -e RESTORE_FILE=/backups/offsite-restore-verify.dump \
  backup sh /scripts/restore_postgres.sh

docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d betteroption_offsite_restore_verify -c "\\dt"'
docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'psql -U "$POSTGRES_USER" -d betteroption_offsite_restore_verify -c "select version_num from alembic_version;"'
```

The restore command must say it completed, `\dt` must list the application
tables, and the revision query must print `0033_background_task_leases`.
Only after all three checks succeed, drop only this isolated verification
database and remove only the three exact temporary files:

```sh
docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'dropdb --if-exists --force -U "$POSTGRES_USER" betteroption_offsite_restore_verify'

rm -- /home/wlb/backup-export/offsite-restore-input.aes256
rm -- deploy/backups/offsite-restore-verify.dump
rm -- deploy/backups/offsite-restore-verify.dump.sha256
```

Record start/end time, operator, encrypted hash, decrypted hash, table check,
migration revision and off-server locations. Only after this drill genuinely
passes may `BETTEROPTION_BACKUP_RESTORE_TESTED=true` be set.

The repository currently provides local scheduled dumps, not an automated
encrypted off-site replication/alerting service. A recurring off-site process
must be selected and tested before friends rely on this as their only copy.

## 24. Finish readiness and create the recovery admin before friends

BetterOption intentionally refuses to create invitations until all of these are
true:

- `BETTEROPTION_REGISTRATION_MODE=invite_only`;
- `BETTEROPTION_LEGAL_REVIEW_COMPLETED=true`;
- `BETTEROPTION_PROCESSOR_REVIEW_COMPLETED=true`;
- `BETTEROPTION_INCIDENT_PLAN_READY=true`;
- `BETTEROPTION_BACKUP_RESTORE_TESTED=true`.

Before changing them, complete the corresponding dossier/reviews, real legal
operator name/address/contact, processor/source decisions, incident contacts,
retention checks and the off-site restore drill. Then edit `.env`, redeploy and
rerun preflight. Do not use `true` as a UI-unlock trick. If live provider/task
checks in section 22 were deferred, configure only the reviewed restricted
server credential and its real cost/operation limits, return to section 22,
and complete every open check **before** proceeding to 24.1.

### 24.1 Add the recovery operator

1. Add the recovery person's exact email to the Cloudflare Access Allow policy.
2. Test that exact email and retest a non-member email.
3. Sign in as owner and open Operations.
4. Create an exact-email invitation. The application displays the secret link
   once and does not email it automatically.
5. Copy it immediately and send it through a separately trusted channel.
6. The recovery operator passes Access, opens the link, creates the account and
   signs in.
7. The owner opens Operations, changes that account's role to **Admin**, chooses
   the intended tester tier, enters the owner's current admin password, and
   saves.
8. The recovery admin signs out/in and proves `/operations` access.

Maintain exactly two named human admins for the alpha. BetterOption prevents
removing the last Admin, but it cannot recover a lost Cloudflare/Netcup account
or a missing off-site backup by itself.

### 24.2 Invite each tester

For every tester, in this order:

1. add the exact email to Cloudflare Access;
2. test the policy;
3. create the exact-email BetterOption invitation;
4. copy the one-time link once and deliver it privately;
5. confirm the tester can pass Access and accept the link;
6. assign **Full alpha tester** only if intended;
7. manually verify account/persona isolation with non-sensitive data.

For immediate offboarding, perform both Cloudflare steps in this order:

1. remove the person's exact email from the Access Allow policy and save it;
2. go to **Zero Trust → Team & Resources → Users**, select that user, then
   **Action → Revoke → Revoke sessions**;
3. test that email against the application policy and verify denial in a new
   private browser session.

Removing the policy entry prevents a new session; revoking terminates the
already-issued session. Either step alone is incomplete. Cloudflare documents
the per-user sequence in
[Access session management](https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/session-management/#per-user).

The current Operations surface does not provide a general admin-side
account-disable control. The person's BetterOption account therefore remains
stored until the user uses the supported self-delete flow or a separately
reviewed account-deletion procedure is performed. Do not imply that changing
role/tester tier revokes login; one layer does not automatically update the
other.

## 25. Daily and weekly operation

SSH to the server and run:

```sh
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging ps
docker compose --env-file deploy/.env.staging logs --since=24h \
  app worker cloudflared backup-scheduler
docker stats --no-stream
free -h
df -h
sudo ufw status verbose
```

Check at least:

- container restart counts and health;
- oldest queued/running task and worker heartbeat/lease recoveries;
- p50/p95 local page time separately from external provider time;
- CPU, RAM, swap/OOM, load and CPU steal;
- disk/database/backup growth and free space;
- latest backup timestamp/checksum and last off-site copy;
- Cloudflare Tunnel health and Access authentication logs;
- provider operation/cost limits and billing reconciliation;
- pending Ubuntu reboot and Docker package updates.

Cloudflare Access authentication events are available under **Zero Trust →
Insights → Logs**; see
[Access authentication logs](https://developers.cloudflare.com/cloudflare-one/insights/logs/dashboard-logs/access-authentication-logs/).

At a planned maintenance window:

```sh
sudo apt-get update
apt list --upgradable
sudo apt-get upgrade --yes
```

This also considers the configured Docker repository. If a reboot is required,
create/verify a fresh backup first, notify testers, wait until no user task is
running, and give the worker more than its internal ten-second cooperative join
window:

```sh
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging stop --timeout 20 worker
sudo reboot
```

After reconnecting, explicitly start the manually stopped worker, then repeat
Compose, Tunnel, Access and direct-origin checks:

```sh
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging start worker
docker compose --env-file deploy/.env.staging ps
```

Do not use `docker system prune -a`, `docker volume prune`,
`docker compose down -v`, `git clean -fdx`, or broad recursive deletion as a
routine cleanup command. They can destroy the database, backups or secrets.

## 26. Upgrade to the next immutable release

Never update a server by pulling a moving branch. For an example next tag
`v0.7.2k`:

### 26.1 Prepare and record the release on Windows

```powershell
Set-Location C:\projects\betteroption
git fetch origin --tags --prune
git status --short
$NextTag = 'v0.7.2k'
$NextCommit = (git rev-list -n 1 $NextTag).Trim()
$NextCommit
git show --no-patch --decorate --oneline $NextTag
```

The local release tests, ZIP hash and GitHub tag must already be accepted.

### 26.2 Back up before changing source

On the VPS create a fresh dump, verify it, copy it encrypted off-server and
record its checksum using section 23. Keep the current tag/commit in the record.

### 26.3 Fetch and compare, then switch detached

```sh
cd /srv/betteroption/app
git status --short
git fetch origin --tags --force --prune
git rev-list -n 1 v0.7.2k
git show --no-patch --decorate --oneline v0.7.2k
```

Compare the printed server commit with `$NextCommit`. Then:

```sh
docker compose --env-file deploy/.env.staging stop --timeout 20 worker
git switch --detach v0.7.2k
git status --short
docker compose --env-file deploy/.env.staging config --quiet
docker compose --env-file deploy/.env.staging config --format json \
  | jq -e '[.services[] | (.ports // []) | .[]] | length == 0'
docker compose --env-file deploy/.env.staging config --format json \
  | jq -e '
      .services as $services
      | ($services | length) as $count
      | [
          $services[]
          | select(
              .logging.driver == "json-file"
              and .logging.options."max-size" == "10m"
              and .logging.options."max-file" == "5"
            )
        ]
      | length == $count
    '
docker compose --env-file deploy/.env.staging pull caddy
docker compose --env-file deploy/.env.staging run --rm --no-deps \
  --entrypoint caddy caddy \
  adapt --config /etc/caddy/Caddyfile --adapter caddyfile --validate --pretty \
  | jq -e '
      .logging.logs.default.encoder.format == "filter"
      and .logging.logs.default.encoder.fields.request.filter == "delete"
      and ([.apps.http.servers[] | has("logs")] | all(. == false))
    '
sh deploy/scripts/deploy_staging.sh
```

Repeat version, migration, container, Access, origin-negative, backup and
worker lifecycle checks. Read the release notes for new `.env` keys before
deploying; copying a new example over `deploy/.env.staging` would erase secrets
and is prohibited.

## 27. Safe rollback after a migration

Database migrations are forward-moving. Do not merely check out the old tag
against a database migrated by a newer release. The recoverable rollback is the
old code plus its matching pre-upgrade dump.

The safest no-data-destruction method creates a second database and leaves the
failed-upgrade database untouched:

1. stop user-facing/work services but leave PostgreSQL running;
2. create a uniquely named rollback database;
3. restore the pre-upgrade dump into it;
4. switch to the old tag;
5. change `POSTGRES_DB` to the rollback database;
6. deploy and verify;
7. retain the failed database until the incident is understood.

Example, with real tags/dump/name substituted:

```sh
cd /srv/betteroption/app
docker compose --env-file deploy/.env.staging stop \
  app worker retention caddy cloudflared backup-scheduler

docker compose --env-file deploy/.env.staging exec -T db sh -c \
  'createdb -U "$POSTGRES_USER" betteroption_rb_20260805'

docker compose --env-file deploy/.env.staging run --rm \
  -e POSTGRES_DB=betteroption_rb_20260805 \
  -e ALLOW_RESTORE=true \
  -e RESTORE_FILE=/backups/PASTE-EXACT-PREUPGRADE.dump \
  backup sh /scripts/restore_postgres.sh

git switch --detach v0.7.2j
```

Edit only `POSTGRES_DB` in `deploy/.env.staging` to
`betteroption_rb_20260805`, then:

```sh
docker compose --env-file deploy/.env.staging config --quiet
sh deploy/scripts/deploy_staging.sh
docker compose --env-file deploy/.env.staging ps
docker compose --env-file deploy/.env.staging logs --tail=150 app worker migrate
```

Verify the old application/version, expected migration revision, Access,
origin isolation and critical workflows. Do not drop either database during the
incident. A later cleanup requires a separate, explicitly reviewed decision
with verified backups.

If the rollback fails, stop `cloudflared`, return to the newer tag/database and
ship a reviewed forward fix. Record every command and timestamp.

## 28. Troubleshooting by symptom

### SSH says `REMOTE HOST IDENTIFICATION HAS CHANGED`

- If the VPS was intentionally reinstalled, obtain the new ED25519 fingerprint
  through SCP Screen first, compare it, then use `ssh-keygen -R <IP>` on
  Windows.
- If no reinstall occurred, stop. Treat it as a possible wrong IP or host-key
  event.

### SSH is locked out after UFW or an ISP-address change

- Use Netcup SCP **Screen**, not a public password workaround.
- Run `sudo ufw status numbered`.
- Add the new verified `/32` SSH rule, test a new Windows session, then delete
  only the numbered obsolete rule.
- Keep root SSH disabled.

### `sudo` rejects the `wlb` password

- Confirm `id` includes `sudo`.
- The Linux sudo password is not the SSH-key passphrase, Netcup password or app
  password.
- Recover through the still-open root/SCP console; do not enable password SSH.

### GitHub asks for a password or says `Permission denied (publickey)`

```sh
ssh -Tv github-betteroption
ssh-keygen -lf /home/wlb/.ssh/betteroption_github.pub
git remote -v
```

Confirm the public key is in the correct repository's Deploy keys, read-only;
the SSH alias uses the correct IdentityFile; and GitHub's host key matches its
official fingerprint. Never put a GitHub token in a clone URL.

### GitHub says repository not found

The common causes are a mistyped `OWNER/REPOSITORY`, deploy key added to a
different repo, or an organization policy blocking deploy keys. Fix GitHub
access; do not reuse a personal write credential.

### Compose reports a missing/invalid variable

```sh
cd /srv/betteroption/app
stat -c '%a %U:%G %n' deploy/.env.staging deploy/cloudflared-token
docker compose --env-file deploy/.env.staging config --quiet
```

Compare key names with the current `deploy/.env.staging.example`. Do not post
the real file or a fully rendered Compose config. Hex secrets avoid URL parser
problems.

### Migration exits non-zero

```sh
docker compose --env-file deploy/.env.staging ps --all migrate db
docker compose --env-file deploy/.env.staging logs --tail=250 migrate db
```

Stop. Preserve logs and backup state. Do not delete the PostgreSQL volume and
do not repeatedly edit Alembic state by hand.

### Cloudflare Tunnel is unhealthy

```sh
docker compose --env-file deploy/.env.staging ps cloudflared caddy app
docker compose --env-file deploy/.env.staging logs --tail=250 \
  cloudflared caddy app
docker compose --env-file deploy/.env.staging exec -T cloudflared \
  cloudflared tunnel ready
```

Check that the token file contains only the current token, outbound traffic is
allowed, and the route points to `http://caddy:80`.

### Browser shows Cloudflare 502

- Tunnel connected but cannot reach the internal service.
- Check `app` health, then Caddy logs.
- Confirm `SITE_ADDRESS` equals the request hostname and the route service is
  exactly `http://caddy:80`.
- Do not solve this by publishing port 8000.

### Browser reaches BetterOption without an Access challenge

This is a security incident. Immediately stop `cloudflared`, then inspect:

- exact Access application hostname;
- exact-email Allow policy;
- absence of Bypass/Everyone policies;
- Tunnel route's **Protect with Access** setting;
- absence of origin `A`/`AAAA` records and host-published ports.

Restart the connector only after a non-member denial is proven.

### Access OTP does not arrive

Cloudflare intentionally does not reveal whether an email matched. Check the
exact-email spelling and Access authentication logs. OTP must be configured as
an identity provider. Codes expire and are single-use; security mail scanners
can consume links. See Cloudflare's
[Access troubleshooting](https://developers.cloudflare.com/cloudflare-one/access-controls/troubleshooting/).

### `/register` says registration is closed during owner bootstrap

- Confirm `.env` contains `BETTEROPTION_REGISTRATION_MODE=first_user`.
- Recreate the app through the deploy script after changing `.env`.
- Run preflight. `first_user` requires an empty database and the exact
  allowlisted operator email.
- If an account already exists, do not reset the database; sign in/recover that
  account and inspect Operations.

### Owner exists but is not Admin

Stop external use. Preflight and Operations should reveal aggregate/admin
state. Do not create more accounts. Preserve the database and use the tested
recovery/role procedure or a reviewed code/database fix.

### Background task is stale or cancellation never finishes

```sh
docker compose --env-file deploy/.env.staging ps app worker db
docker compose --env-file deploy/.env.staging logs --since=30m worker app
docker compose --env-file deploy/.env.staging restart --timeout 20 worker
```

Wait through the configured lease interval and refresh the stored task page.
Do not switch personas as an operational task-kill mechanism. Capture task ID,
timestamps and secret-free logs for a `v0.7.2j` regression report.

### Disk or memory is low

```sh
df -h
free -h
docker stats --no-stream
docker system df
sudo journalctl -k --since=-24h | grep -iE 'oom|out of memory' || true
```

Identify the growing database, backups, build cache or logs. Never run a broad
prune while diagnosing. More VPS cores will not repair an unbounded disk,
provider timeout or single-worker bottleneck.

### Backup scheduler has no recent dump

```sh
docker compose --env-file deploy/.env.staging ps backup-scheduler db
docker compose --env-file deploy/.env.staging logs --tail=250 \
  backup-scheduler db
ls -lah deploy/backups
```

Run the on-demand backup and checksum procedure. Treat missing off-site copies
or alerts as a failed readiness control.

## 29. Honest external gates and current deployment limitations

The following are not completed by cloning the repository or following a shell
command:

- Netcup contract/order, real IP allocation and independent console access;
- Cloudflare domain activation, retained mail DNS, Access exact-email policy,
  OTP/IdP behavior, Tunnel route and real non-member denial;
- real server/provider/API credentials and their processor/source review;
- actual legal operator details, legal review and launch decision;
- named incident contacts and an exercised response process;
- recurring encrypted off-server backup storage and failure alerting;
- external monitoring/alert delivery for web, worker, Tunnel, backup, disk and
  container restarts;
- creation and acceptance of the first owner/recovery accounts;
- live task, cancellation, worker restart and origin-bypass acceptance;
- GitHub tag/commit and release-hash publication.

Known repository/deployment limitations that this runbook cannot silently fix:

1. The included backup scheduler writes rotating dumps to the same VPS. It does
   not encrypt or replicate them off-site and does not alert on failure. Section
   23 gives a manual first drill; a recurring external mechanism remains an
   operator gate.
2. PostgreSQL/Caddy and the Dockerfile base use upstream image tags rather than
   immutable image digests. Rebuilding the same Git tag later can therefore
   resolve newer upstream bytes. Record deployed image IDs and test every
   rebuild; true byte-for-byte container reproducibility requires a later
   reviewed Compose/Dockerfile change.
3. The deployment script treats unfinished legal/processor/incident/restore
   items as visible preflight warnings so an owner-only rehearsal is possible.
   It is the invitation code and this stop-gated procedure—not the shell exit
   code alone—that prevent a premature friend alpha.
4. Monitoring and off-site backup providers are not provisioned in this
   repository. They require separate accounts, credentials, retention choices
   and acceptance tests.
5. Operations does not currently expose a general admin-side account-disable
   action. Cloudflare exact-email removal plus per-user session revocation is the
   immediate perimeter offboarding control; application-account deletion still
   needs the supported user flow or a separately reviewed operator procedure.
6. The backup scripts cover PostgreSQL, not the `app_data` or Caddy named
   volumes and not server secrets. PostgreSQL contains the authoritative account,
   persona, job and result records; loss of `app_data` still loses local
   reproducibility/cache files. If those files become a recovery requirement,
   add and test a separately encrypted volume-backup procedure rather than
   assuming the database dump contains them.
7. Container output is bounded by size, not by age: each service can retain up
   to five 10 MB Docker `json-file` files until rotation overwrites them. There
   is no central log archive or alerting in this repository. Caddy removes its
   complete HTTP request object before runtime/error encoding, but operators
   must still avoid logging secrets or personal content elsewhere.

These are not reasons to import the local database, publish a temporary port,
weaken Access, or mark a readiness flag true. Keep the alpha owner-only until
the relevant gate is genuinely complete.

## 30. Primary references checked for this runbook

- [Netcup: First use of your server](https://www.netcup.com/en/helpcenter/documentation/server/accessing-server)
- [Netcup: Save SSH keys in SCP](https://community.netcup.com/en/tutorials/sshkey-setup-image-scp)
- [Microsoft: OpenSSH for Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-overview)
- [Microsoft: OpenSSH key management](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement)
- [Ubuntu: OpenSSH server](https://ubuntu.com/server/docs/how-to/security/openssh-server/)
- [Ubuntu: Automatic updates](https://documentation.ubuntu.com/server/how-to/software/automatic-updates/)
- [Docker: Install Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Docker: Packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
- [Docker: `json-file` logging options and rotation](https://docs.docker.com/engine/logging/drivers/json-file/)
- [Docker Compose: service `stop_grace_period`](https://docs.docker.com/reference/compose-file/services/#stop_grace_period)
- [Caddy: global `log` option](https://caddyserver.com/docs/caddyfile/options#log)
- [Caddy: filter encoder and `delete`](https://caddyserver.com/docs/caddyfile/directives/log#filter-encoder)
- [Caddy issue 5703: runtime errors can contain the request URI](https://github.com/caddyserver/caddy/issues/5703)
- [GitHub: Managing deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)
- [GitHub: SSH host-key fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints/)
- [Cloudflare: Full DNS setup](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/)
- [Cloudflare: DNSSEC](https://developers.cloudflare.com/dns/dnssec/)
- [Cloudflare: One-time PIN](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/)
- [Cloudflare: Self-hosted Access application](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)
- [Cloudflare: Remotely managed Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)
- [Cloudflare: Access authentication logs](https://developers.cloudflare.com/cloudflare-one/insights/logs/dashboard-logs/access-authentication-logs/)
- [Cloudflare: Access session management and revocation](https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/session-management/)
