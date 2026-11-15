from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    app_env: str = "development"
    database_url: str
    control_database_url: str = ""
    operations_database_url: str = ""
    jwt_secret: str = ""
    platform_jwt_secret: str = ""
    field_encryption_key: str
    public_web_url: str = "http://localhost:8080"
    jwt_issuer: str = "telite-crm"
    cookie_secure: bool = True
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    access_token_ttl_seconds: int = 600
    refresh_token_ttl_seconds: int = 1209600
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""
    smtp_starttls: bool = True

    @model_validator(mode="after")
    def secure_configuration(self):
        from cryptography.fernet import Fernet

        if self.jwt_secret and len(self.jwt_secret) < 48:
            raise ValueError("JWT_SECRET must contain at least 48 random characters")
        Fernet(self.field_encryption_key.encode())
        if not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("PostgreSQL with psycopg is required")
        if self.platform_jwt_secret and (
            len(self.platform_jwt_secret) < 48 or self.platform_jwt_secret == self.jwt_secret
        ):
            raise ValueError("Platform signing secret must be independent and at least 48 characters")
        if self.app_env == "production":
            if not self.cookie_secure or not self.public_web_url.startswith("https://"):
                raise ValueError("Production requires HTTPS and Secure cookies")
            if not self.smtp_host or not self.smtp_starttls:
                raise ValueError("Production requires SMTP with TLS")
        if not 60 <= self.access_token_ttl_seconds <= 900:
            raise ValueError("Access TTL must be 60–900 seconds")
        return self


@lru_cache
def settings():
    return Settings()
