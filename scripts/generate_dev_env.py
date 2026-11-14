"""Create local-development secrets once. Never overwrite an existing .env."""
import base64
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
values = {
    'APP_ENV': 'development',
    'PUBLIC_WEB_URL': 'http://localhost:8080',
    'ALLOWED_HOSTS': 'localhost,127.0.0.1',
    'COOKIE_SECURE': 'false',
    'JWT_SECRET': secrets.token_urlsafe(64),
    'PLATFORM_JWT_SECRET': secrets.token_urlsafe(64),
    'FIELD_ENCRYPTION_KEY': base64.urlsafe_b64encode(os.urandom(32)).decode(),
    'POSTGRES_PASSWORD': secrets.token_urlsafe(36),
    'API_DB_PASSWORD': secrets.token_urlsafe(36),
    'CONTROL_DB_PASSWORD': secrets.token_urlsafe(36),
    'MAIL_DB_PASSWORD': secrets.token_urlsafe(36),
    'SMTP_HOST': 'mailpit',
    'SMTP_PORT': '1025',
    'SMTP_STARTTLS': 'false',
    'SMTP_FROM_ADDRESS': 'noreply@example.com',
}
path=root / '.env'
with path.open('x') as file:
    os.chmod(path,0o600)
    file.write('\n'.join(f'{key}={value}' for key,value in values.items())+'\n')
print('Created local .env with random development credentials. Keep this file out of Git.')
