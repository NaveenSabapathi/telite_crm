"""Interactive production env generator. Run on VPS; creates a new file only."""
import argparse
import base64
import getpass
import os
from pathlib import Path
import re
import secrets

parser = argparse.ArgumentParser()
parser.add_argument('--domain', required=True, help='Exact CRM hostname, without scheme/path')
parser.add_argument('--postgres-image', required=True, help='Pinned postgres:17-alpine image digest')
parser.add_argument('--output', default='/etc/telite-crm/prod.env')
args = parser.parse_args()
if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', args.domain) or '.' not in args.domain:
    parser.error('Use a fully qualified domain, without https:// or a path')
if not re.fullmatch(r'postgres@sha256:[0-9a-f]{64}', args.postgres_image):
    parser.error('Use the postgres@sha256 digest from the selected PostgreSQL 17 image')
values = {
    'PUBLIC_WEB_URL': f'https://{args.domain.lower()}',
    'ALLOWED_HOSTS': args.domain.lower(),
    'CRM_POSTGRES_IMAGE': args.postgres_image,
    'FIELD_ENCRYPTION_KEY': base64.urlsafe_b64encode(os.urandom(32)).decode(),
    **{k: secrets.token_urlsafe(48) for k in ('JWT_SECRET', 'PLATFORM_JWT_SECRET', 'POSTGRES_PASSWORD',
        'API_DB_PASSWORD', 'CONTROL_DB_PASSWORD', 'MAIL_DB_PASSWORD', 'OPERATIONS_DB_PASSWORD')},
}
for key, prompt in [('SMTP_HOST','SMTP hostname: '), ('SMTP_PORT','SMTP STARTTLS port [587]: '),
                    ('SMTP_FROM_ADDRESS','Verified sender email: '), ('SMTP_USERNAME','SMTP username: ')]:
    values[key] = input(prompt).strip() or ('587' if key == 'SMTP_PORT' else '')
values['SMTP_PASSWORD'] = getpass.getpass('SMTP password (hidden): ')
if not values['SMTP_HOST'] or not values['SMTP_FROM_ADDRESS'] or not values['SMTP_PORT'].isdigit():
    parser.error('SMTP host, sender and numeric port are required; this app uses SMTP STARTTLS')
# Compose dotenv single quotes prevent $/#/spaces in passwords being expanded.
def quote(value):
    if any(c in value for c in ('\n','\r','\x00')):
        raise ValueError('Multiline env values are not supported')
    return "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"
output = Path(args.output)
output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd,'w') as file:
    for key, value in values.items():
        file.write(f'{key}={quote(value)}\n')
print(f'Created {output}; secrets were not printed. Keep an encrypted off-server copy.')
