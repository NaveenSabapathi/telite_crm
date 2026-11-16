# Run Telite CRM beside ATS on the existing VPS

Prepared 16 November 2026 for the supplied Hostinger screenshots: VPS IPv4 `147.93.110.111`, ATS on 3000/8000/5433/6379. Screenshots also show `jhipster-app` and `jhipster-db` still running. These are observations from screenshots, not a live server inspection.

The current repo already contains CI (`CRM verification`). This change adds image publication and optional deployment after successful main-branch CI. It does not log into or modify your VPS. Use a new Compose project `telitecrm`, a dedicated PostgreSQL volume `telitecrm_pgdata`, and loopback port **18080**. Docker project separation avoids accidental shared commands, but CPU/RAM/disk and the host Docker daemon remain shared.

## 1. Inspect and record the existing services first

Run in the VPS console as root. These are inspection commands:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker compose ls
ss -lntp
free -h
df -h /
docker stats --no-stream
systemctl is-active nginx
nginx -t
```

Confirm 18080 is free. Record the existing ATS domain and verify it loads. The following instructions assume **host Nginx already handles 80/443**. If Apache, Caddy, Traefik or another container owns those ports, stop here and adapt the domain route to that existing proxy. Do not install a second proxy onto the same ports or click Hostinger “Deploy Traefik” over an existing Nginx setup.

Take a Hostinger snapshot and an application-consistent ATS DB backup using the existing ATS runbook. Snapshot restoration affects the whole VPS, so prefer app-specific DB recovery when possible. Keep root-only copies of existing Nginx configuration. Do not print full Docker inspect/environment output because it can expose ATS passwords.

```bash
install -d -m 700 /root/pre-crm
cp -a /etc/nginx /root/pre-crm/nginx-$(date -u +%Y%m%dT%H%M%SZ)
docker ps --format '{{.Names}} {{.Status}} {{.Ports}}' > /root/pre-crm/containers.txt
```

Unused JHipster is a separate optional cleanup. Inspect its mounts and Compose labels before changing it. If you confirm it is unused and its data is backed up, disable restart and stop **only these names**:

```bash
docker update --restart=no jhipster-app jhipster-db
docker stop jhipster-app jhipster-db
```

Do not remove these containers/volumes yet. ATS containers (`ats_v2-*`) are not part of CRM deployment. Avoid global `docker stop`, `docker system prune`, `docker volume prune`, restarting Docker, rebooting, or running another project's `compose down` during this task. Host-wide security updates/reboot should have a separate maintenance window.

## 2. Choose the CRM hostname and add DNS

Example used below: **crm.mindhootlabs.cloud**. You can instead use an owned independent domain such as `yourcrm.com`; replace the example consistently in DNS, env, certificate and Nginx. DNS does not encode a port.

At the DNS provider authoritative for that domain:

| Type | Host/name | Value |
|---|---|---|
| A | crm (or @ for a separate apex domain) | 147.93.110.111 |

Do not change ATS's A record or replace existing root/www records. Do not create an AAAA record unless IPv6 ingress is configured and tested. For Cloudflare, use DNS-only for initial certificate setup; enable proxy later with Full (strict) TLS after direct HTTPS works. Check existing CAA records permit Let's Encrypt.

On the VPS:

```bash
dig +short A crm.mindhootlabs.cloud
```

Expected IPv4: `147.93.110.111`. Ports 80/443 must be reachable through both host and provider firewalls. Keep the actual existing SSH port allowed; screenshots/memory cannot establish whether it is 22 or 2212 now. Do not reset the firewall. There is no need to open 18080 or CRM PostgreSQL publicly.

## 3. Merge the deployment PR and publish the first images

Review and merge the PR containing these files. The new `CRM production release` workflow runs after successful **push-to-main** `CRM verification`. It checks out the exact tested commit, excludes PR/fork events, builds the backend/web images on GitHub and tags both `sha-<full commit SHA>`. A newer main commit prevents an outdated queued release from publishing.

Initially leave repository variable `CRM_DEPLOY_ENABLED` unset: this publishes images while keeping server deployment disabled. After CI succeeds, watch Actions → CRM production release. Record the **tested release SHA** used in the image tags (not an arbitrary branch name). If the workflow was newly merged and no release ran, re-run the successful main push `CRM verification` run.

Expected packages:

- `ghcr.io/naveensabapathi/telite_crm-backend`
- `ghcr.io/naveensabapathi/telite_crm-web`

For the simplest VPS pull setup, make both packages public in GitHub profile → Packages → package settings → visibility. Repository public visibility does not automatically make a new package public. If packages remain private, configure root's GHCR login on VPS with a read:packages credential; never use a GitHub password or place that token in app containers. Workflow publishing uses its own short-lived GITHUB_TOKEN with packages:write.

## 4. Install only the CRM deployment configuration

Check Docker Compose v2 already exists:

```bash
docker compose version
```

Do not reinstall/restart Docker over the running ATS service. Clone the public repository into its own source folder:

```bash
install -d -m 700 /opt/telite-crm /etc/telite-crm
git clone https://github.com/NaveenSabapathi/telite_crm.git /opt/telite-crm/source
cd /opt/telite-crm/source
install -m 600 infra/production/compose.yaml /opt/telite-crm/compose.yaml
install -m 755 scripts/production/deploy.sh /usr/local/sbin/telite-crm-deploy
install -m 755 scripts/production/backup.sh /usr/local/sbin/telite-crm-backup
install -m 755 scripts/production/ssh-entrypoint.sh /usr/local/bin/telite-crm-ssh
```

Pin the PostgreSQL 17 base image for this installation. The deployer does not automatically upgrade the DB image on every app release:

```bash
docker pull postgres:17-alpine
CRM_PG_IMAGE=$(docker image inspect postgres:17-alpine --format '{{index .RepoDigests 0}}')
python3 scripts/production/generate_env.py \
  --domain crm.mindhootlabs.cloud \
  --postgres-image "$CRM_PG_IMAGE"
```

The generator creates `/etc/telite-crm/prod.env` mode 600, with random DB/signing/encryption secrets, and prompts for a real verified SMTP sender and STARTTLS credentials. It refuses to overwrite an existing file. Use port 587 for a provider supporting STARTTLS; port 465 implicit-TLS-only SMTP is not supported by this app's sender. Use provider SMTP/app credentials, not a normal mailbox password where the provider disallows it. Compose-quoted values handle special characters in SMTP secrets. Do not `source` this dotenv file into shell.

Keep an encrypted off-server copy of this env file. Losing DB credentials/encryption keys can block recovery. Do not regenerate secrets on every deployment or put the file in GitHub/Git.

Resource caps in the production Compose are initial guardrails, approximately 1.5 GiB total steady-state memory caps plus migration overhead, not a capacity guarantee. Confirm actual VPS RAM with `free -h`. Deployer requires 5 GiB free disk and at least about 1.66 GiB MemAvailable on first install. Load-test ATS and CRM together; upgrade VPS if memory/latency becomes constrained.

## 5. Deploy the first tested release manually

Replace the value below with the **40-character tested SHA published by Actions**:

```bash
/usr/local/sbin/telite-crm-deploy YOUR_40_CHARACTER_RELEASE_SHA
```

The command pulls already-built images, starts only CRM's DB, pauses only CRM processes, makes and validates a pre-migration dump, runs migrations/role grants, starts CRM and checks both API routes. The first database dump is an empty pre-migration database and cannot substitute for later data backups. PostgreSQL and APIs are internal; only `127.0.0.1:18080` is bound on the host. Database migrations involve short CRM maintenance; this is not a zero-downtime CRM release mechanism. ATS is not deliberately restarted by these commands.

```bash
cd /opt/telite-crm
docker compose -p telitecrm --env-file /etc/telite-crm/prod.env --env-file current.env -f compose.yaml ps
curl -I -H 'Host: crm.mindhootlabs.cloud' http://127.0.0.1:18080/
```

Check ATS still loads. Log inspection stays scoped to CRM:

```bash
docker compose -p telitecrm --env-file /etc/telite-crm/prod.env --env-file current.env -f compose.yaml logs --tail=60 api control auth-mail
```

## 6. Add one Nginx host and HTTPS

If Certbot is absent, install it using your Ubuntu-supported method after checking package changes; do not restart or replace the current web server. The following uses an already-installed `certbot` with webroot, which does not rewrite existing sites.

```bash
install -d -m 755 /var/www/telite-crm-acme
sed 's/CRM_DOMAIN/crm.mindhootlabs.cloud/g' /opt/telite-crm/source/infra/production/nginx-http.conf.example > /etc/nginx/sites-available/telite-crm
ln -s /etc/nginx/sites-available/telite-crm /etc/nginx/sites-enabled/telite-crm
nginx -t && systemctl reload nginx
certbot certonly --webroot -w /var/www/telite-crm-acme -d crm.mindhootlabs.cloud
```

If `telite-crm` site files/links already exist, inspect them rather than overwrite blindly. Keep existing ATS sites/defaults. After the certificate succeeds:

```bash
sed 's/CRM_DOMAIN/crm.mindhootlabs.cloud/g' /opt/telite-crm/source/infra/production/nginx-https.conf.example >> /etc/nginx/sites-available/telite-crm
nginx -t && systemctl reload nginx
curl -I https://crm.mindhootlabs.cloud/
certbot renew --dry-run
```

Configure a renewal deploy hook so Nginx rereads renewed certificates (skip if one already exists):

```bash
install -d /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/telite-nginx-reload <<'SH'
#!/bin/sh
nginx -t && systemctl reload nginx
SH
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/telite-nginx-reload
```

Host Nginx forwards the original hostname to the loopback gateway; PUBLIC_WEB_URL and ALLOWED_HOSTS must match the public hostname exactly. The current container gateway overwrites forwarded IPs with its peer address, so rate limits can aggregate clients behind that gateway; configure trusted real-IP forwarding separately before high-traffic production rollout. Do not trust arbitrary public X-Forwarded-For headers.

## 7. Create the SaaS owner account

```bash
cd /opt/telite-crm
docker compose -p telitecrm --env-file /etc/telite-crm/prod.env --env-file current.env -f compose.yaml \
  --profile tools run --rm --no-deps migrate \
  python -m app.provision admin --email YOUR_ADMIN_EMAIL
```

Follow password/authenticator prompts. Open the HTTPS domain → Platform admin → create your first company → confirm invite arrives → accept → company login. Verify tenant/employee administration and currently implemented workflows. No production default credentials exist.

## 8. Configure GitHub-to-VPS SSH once

Create a separate deploy key **on your own computer**, without a passphrase for this machine-only CI key:

```bash
ssh-keygen -t ed25519 -f crm-actions -C telite-crm-actions
```

Keep `crm-actions` private; `crm-actions.pub` is public. On the VPS as root:

```bash
adduser --disabled-password --gecos '' crmdeploy
install -d -m 700 -o crmdeploy -g crmdeploy /home/crmdeploy/.ssh
cat > /etc/sudoers.d/telite-crm-deploy <<'SUDO'
crmdeploy ALL=(root) NOPASSWD: /usr/local/sbin/telite-crm-deploy
SUDO
chmod 440 /etc/sudoers.d/telite-crm-deploy
visudo -cf /etc/sudoers.d/telite-crm-deploy
nano /home/crmdeploy/.ssh/authorized_keys
```

Put one line in authorized_keys, replacing the key text:

```text
restrict,command="/usr/local/bin/telite-crm-ssh" ssh-ed25519 YOUR_PUBLIC_KEY telite-crm-actions
```

```bash
chown crmdeploy:crmdeploy /home/crmdeploy/.ssh/authorized_keys
chmod 600 /home/crmdeploy/.ssh/authorized_keys
```

Do not add crmdeploy to docker or give it general sudo. The wrapper accepts only `deploy <40-lowercase-hex SHA>`; root-owned deployer uses one fixed Compose file/project. Keep `/opt/telite-crm`, `/etc/telite-crm`, scripts and sudoers root-owned; GitHub cannot upload arbitrary Compose files through this key. Someone with Docker/general sudo could affect the entire shared VPS, so repo production access and this key still need protection.

From your PC, get the SSH host public key with `ssh-keyscan -p YOUR_ACTUAL_SSH_PORT 147.93.110.111`, then compare its fingerprint to `/etc/ssh/ssh_host_ed25519_key.pub` in the Hostinger console using `ssh-keygen -lf`. Do not trust scan output until fingerprints match. Preserve the verified known_hosts line (including `[host]:port` for a nondefault port).

Repository → Settings → Environments → create **production**. Add environment secrets:

| Secret | Value |
|---|---|
| CRM_DEPLOY_HOST | 147.93.110.111 |
| CRM_DEPLOY_PORT | Actual working SSH port, verified now |
| CRM_DEPLOY_SSH_KEY | Complete private `crm-actions` key |
| CRM_SSH_KNOWN_HOSTS | Verified known_hosts line for that host/port |

Optionally add required reviewers to the production environment for a deployment approval gate, if your GitHub plan supports it. Repository Settings → Secrets and variables → Actions → Variables: set `CRM_DEPLOY_ENABLED=true` **only after manual deployment and HTTPS are working**. Protect main with required `CRM verification` and production smoke checks; production credentials must never be used in PR CI.

## 9. Normal future releases

Push feature branch → PR CI → merge main → successful main CI → GitHub builds/publishes exact-SHA images → optional production-environment approval → forced SSH command → CRM backup/migration/restart/health check.

The server does not compile frontend/backend on its 1-vCPU VPS. GitHub does not get ATS paths, DB credentials or arbitrary deploy commands. Container tags are per commit; retain previous release images for rollback. They are not cryptographically immutable tags: restrict package write access; use digest-pinned artifacts/signing if stronger supply-chain guarantees are required.

Root-owned host scripts/Compose are installed separately. When a release changes them, review and reinstall those files manually; ordinary app deployment deliberately cannot overwrite them. After enabling CD, re-run a successful main push CI run to deploy the current main release, or merge your next tested change. Never re-run an older main CI run to force an old deployment; stale release detection will reject it.

## 10. Backups and failed release recovery

Enable the scoped daily dump job:

```bash
install -m 644 /opt/telite-crm/source/infra/production/telite-crm-backup.service /etc/systemd/system/
install -m 644 /opt/telite-crm/source/infra/production/telite-crm-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now telite-crm-backup.timer
/usr/local/sbin/telite-crm-backup
systemctl list-timers telite-crm-backup.timer
```

Local backups: `/opt/telite-crm/backups`, mode restricted, retained 14 days. They contain sensitive company data; add encrypted off-server copies and alert on failed backups. A second directory on the same VPS is not disaster recovery. Protect env/encryption keys separately. Perform a real restore test into an isolated database before a production pilot.

On failure: inspect only the `telitecrm` logs. Migration failure leaves CRM stopped and preserves dump; do not automatically restore over newer data. `previous.env` holds the prior successfully deployed image SHA. Code rollback may use that SHA **only after confirming the new schema remains compatible with the old code**. Use the same deploy command with the prior full SHA for a compatible code rollback; it also makes a backup and does not downgrade DB. If schema is incompatible, perform a reviewed restore into an isolated database, validate it, then plan CRM-only cutover. Never restore the full VPS just to undo a CRM code change, because that can roll ATS back as well.

This is a shared-host deployment with scoped operations and brief CRM maintenance, not a guarantee that resource exhaustion, host failure or malicious root access cannot affect ATS. Docker/SMTP/DNS/TLS must be validated on the actual server; none were changed by preparing this guide.
