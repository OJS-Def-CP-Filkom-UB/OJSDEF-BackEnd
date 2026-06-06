from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    plugin_hmac_secret: str
    plugin_api_key_secret: str  # 32-byte hex for AES-256-GCM

    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str = "ojsdef-reports"
    minio_use_ssl: bool = False

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = "noreply@ojsdef.com"

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_bot_username: str = ""
    frontend_base_url: str = "http://localhost:3000"
    cve_api_key: str = ""
    sentry_dsn: str = ""

    environment: str = "development"
    allowed_origins: str = "http://localhost:3000"
    app_base_url: str = "http://localhost:8000"

    seed_admin_email: str = "admin@ojsdef.com"
    seed_admin_password: str = ""

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
