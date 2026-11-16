#!/usr/bin/env bash
# Install root-owned as /usr/local/sbin/telite-crm-deploy.
# No arbitrary path, repository, command or Compose project accepted from SSH.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run through the installed root deploy command.' >&2; exit 1; }
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || { echo 'One full lowercase release SHA required.' >&2; exit 2; }
release_sha=$1
exec 9>/var/lock/telite-crm-deploy.lock
flock -n 9 || { echo 'Another CRM deployment or backup is running.' >&2; exit 1; }
cd /opt/telite-crm
[[ -f compose.yaml && -f /etc/telite-crm/prod.env ]] || { echo 'Complete host setup first.' >&2; exit 1; }
mkdir -p backups
if (( $(df -Pk /opt/telite-crm | awk 'NR==2 {print $4}') < 5242880 )); then
  echo "Less than 5 GiB free; aborting before touching CRM." >&2; exit 1
fi
if [[ ! -f current.env ]] && (( $(awk '/MemAvailable:/ {print $2}' /proc/meminfo) < 1740800 )); then
  echo "First deployment needs at least 1.66 GiB available memory; review VPS capacity." >&2; exit 1
fi
release_env=$(mktemp /opt/telite-crm/.release.XXXXXX)
trap 'rm -f "$release_env"' EXIT
printf 'IMAGE_TAG=%s\n' "$release_sha" > "$release_env"
compose() {
  docker compose --project-name telitecrm --env-file /etc/telite-crm/prod.env --env-file "$release_env" -f /opt/telite-crm/compose.yaml "$@"
}
compose config --quiet
# Both images must be available before the current CRM processes are touched.
compose --profile tools pull api control auth-mail web migrate
compose up -d --wait --wait-timeout 120 db
backup="/opt/telite-crm/backups/pre-${release_sha}-$(date -u +%Y%m%dT%H%M%SZ).dump"
# CRM maintenance begins here. Other projects are never stopped or restarted.
compose stop web api control auth-mail
if ! compose exec -T db pg_dump -U migrator -d telite -Fc > "$backup.tmp"; then
  rm -f "$backup.tmp"
  echo 'Backup failed. CRM remains stopped; diagnose and restart the previous release.' >&2
  exit 1
fi
[[ -s "$backup.tmp" ]] || { echo 'Empty backup; aborting.' >&2; exit 1; }
# Verify archive structure before migration; an independent restore drill is still required.
compose exec -T db pg_restore --list < "$backup.tmp" >/dev/null
mv "$backup.tmp" "$backup"
if [[ -f current.env ]]; then cp current.env previous.env; fi
# No automatic DB downgrade or restore. Failed migration requires operator review.
if ! compose --profile tools run --rm --no-deps migrate; then
  echo "Migration failed. CRM remains stopped; backup is $backup. ATS is outside this project." >&2
  exit 1
fi
if ! compose up -d --no-deps --wait --wait-timeout 180 api control auth-mail web; then
  echo "CRM health failed. Inspect CRM logs; backup is $backup. No automatic DB restore performed." >&2
  exit 1
fi
# Test actual gateway -> tenant API and gateway -> platform API, not only static HTML.
crm_host=$(python3 - <<'PY'
from pathlib import Path
for line in Path('/etc/telite-crm/prod.env').read_text().splitlines():
    if line.startswith('ALLOWED_HOSTS='):
        print(line.split('=',1)[1].strip().strip("'\"")); break
PY
)
[[ $crm_host =~ ^[a-zA-Z0-9.-]+$ ]] || { echo 'ALLOWED_HOSTS must contain exactly the CRM hostname.' >&2; exit 1; }
curl --fail --silent --show-error --max-time 15 -H "Host: $crm_host" http://127.0.0.1:18080/ >/dev/null
for endpoint in /api/v1/me /api/v1/platform/me; do
  code=$(curl --silent --show-error --max-time 15 -o /dev/null -w '%{http_code}' -H "Host: $crm_host" "http://127.0.0.1:18080$endpoint")
  [[ $code == 401 ]] || { echo "Gateway check failed: $endpoint returned $code" >&2; exit 1; }
done
cp "$release_env" current.env
printf 'CRM release %s deployed. Pre-deployment backup: %s\n' "$release_sha" "$backup"
