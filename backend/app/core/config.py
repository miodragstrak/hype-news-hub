import re
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "hype_news_hub"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"

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
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
