from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MINIAGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    model: str = "gpt-4o-mini"
    policy_model: str = "gpt-4o-mini"
    max_tokens: int = 4096
    temperature: float = 0.0
    workspace_dir: str = "./workspace"

    # GitHub OAuth App (read without the MINIAGENT_ prefix, like OPENAI_API_KEY).
    github_client_id: str = Field(
        "", validation_alias=AliasChoices("GITHUB_CLIENT_ID")
    )
    github_client_secret: str = Field(
        "", validation_alias=AliasChoices("GITHUB_CLIENT_SECRET")
    )
    public_base_url: str = "http://127.0.0.1:8000"
    frontend_url: str = "http://localhost:3000"

    database_url: str = Field(
        "postgresql+psycopg://miniagent:miniagent@localhost:5432/miniagent",
        validation_alias=AliasChoices("DATABASE_URL"),
    )
