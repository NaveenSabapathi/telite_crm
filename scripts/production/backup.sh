#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || exit 1
exec 9>/var/lock/telite-crm-deploy.lock
flock -w 300 9
cd /opt/telite-crm
[[ -f current.env ]] || { echo 'No successful CRM deployment yet.' >&2; exit 1; }
mkdir -p backups
backup="backups/daily-$(date -u +%Y%m%dT%H%M%SZ).dump"
compose() {
 docker compose -p telitecrm --env-file /etc/telite-crm/prod.env --env-file /opt/telite-crm/current.env -f /opt/telite-crm/compose.yaml "$@"
}
trap 'rm -f "$backup.tmp"' EXIT
compose exec -T db pg_dump -U migrator -d telite -Fc > "$backup.tmp"
[[ -s "$backup.tmp" ]]
compose exec -T db pg_restore --list < "$backup.tmp" >/dev/null
mv "$backup.tmp" "$backup"
# Retain 14 days locally. Add encrypted off-server copies before production use.
find /opt/telite-crm/backups -maxdepth 1 -type f -name '*.dump' -mtime +14 -delete
