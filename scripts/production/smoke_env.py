"""Generate disposable CI-only settings. Does not produce production credentials."""
import base64
import os
from pathlib import Path
import secrets
import sys

image, sha, output = sys.argv[1:]
values = {'PUBLIC_WEB_URL':'https://crm.example.com','ALLOWED_HOSTS':'crm.example.com',
          'CRM_POSTGRES_IMAGE':image,'IMAGE_TAG':sha,'FIELD_ENCRYPTION_KEY':base64.urlsafe_b64encode(os.urandom(32)).decode(),
          'SMTP_HOST':'smtp.invalid','SMTP_FROM_ADDRESS':'ci@example.com','SMTP_PORT':'587'}
for key in ('JWT_SECRET','PLATFORM_JWT_SECRET','POSTGRES_PASSWORD','API_DB_PASSWORD','CONTROL_DB_PASSWORD','MAIL_DB_PASSWORD','OPERATIONS_DB_PASSWORD'):
    values[key]=secrets.token_urlsafe(48)
fd=os.open(output, os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as file:
    file.write('\n'.join(f'{k}={v}' for k,v in values.items())+'\n')
