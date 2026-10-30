import re
from functools import lru_cache

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    app_name: str = "Hype News Hub"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    backend_cors_origins: str = (
        "http://localhost:5173,http://localhost:3000,"
        "https://hype-news-hub.vercel.app"
    )
    backend_cors_origin_regex: str | None = (
        r"^https://hype-news-hub-(?:git-[a-z0-9-]+|[a-z0-9]{9})"
        r"-miodrag-straks-projects\.vercel\.app$"
    )
    discovery_timeout_seconds: float = 8.0
    story_merge_threshold: int = 72
    story_match_max_gap_hours: float = Field(default=48, gt=0, allow_inf_nan=False)
    news_storage_backend: Literal["memory", "postgres"] = "memory"

    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "hype_news_hub"
    postgres_user: str = "hype_news_hub"
    postgres_password: SecretStr = SecretStr("")
    postgres_sslmode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = "prefer"
    postgres_connect_timeout_seconds: int = Field(default=5, ge=1)
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=5, ge=0)
    database_pool_timeout_seconds: int = Field(default=30, ge=1)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    @field_validator("backend_cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        if "*" in {origin.strip() for origin in value.split(",")}:
            raise ValueError("CORS origins must be explicit; '*' is not allowed.")
        return value

    @field_validator("backend_cors_origin_regex")
    @classmethod
    def validate_cors_origin_regex(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError("CORS origin regex must be a valid regular expression.") from exc
        return value

    @property
    def database_url(self) -> URL:
        if not self.postgres_password.get_secret_value():
            raise ValueError("POSTGRES_PASSWORD is required for database access.")
        return URL.create(
            "postgresql+psycopg", username=self.postgres_user,
            password=self.postgres_password.get_secret_value(), host=self.postgres_host,
            port=self.postgres_port, database=self.postgres_db,
            query={"sslmode": self.postgres_sslmode, "connect_timeout": str(self.postgres_connect_timeout_seconds)},
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
