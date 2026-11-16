#!/usr/bin/env bash
# Root-owned forced-command wrapper. Deploy user has no Docker group membership.
set -euo pipefail
if [[ ${SSH_ORIGINAL_COMMAND:-} =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
  exec sudo -n /usr/local/sbin/telite-crm-deploy "${BASH_REMATCH[1]}"
fi
echo 'Only deploy <40-character SHA> is accepted.' >&2
exit 2
