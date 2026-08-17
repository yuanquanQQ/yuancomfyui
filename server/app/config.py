from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "YunComfyUI License Service"
    environment: str = "production"
    database_url: str = "mysql+pymysql://license:license@db:3306/license?charset=utf8mb4"
    jwt_secret: str = Field(min_length=32)
    card_hash_pepper: str = Field(min_length=32)
    signing_key_path: Path = Path("/app/secrets/license_ed25519.pem")
    signing_key_id: str = "license-key-2026-01"
    admin_token_minutes: int = 480
    refresh_token_days: int = 3650
    default_offline_grace_hours: int = 72
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = Field(min_length=12)
    trusted_proxy_count: int = 1

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str):
        if value not in {"development", "test", "production"}:
            raise ValueError("environment must be development, test or production")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
