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

    supabase_url: str = Field("", validation_alias=AliasChoices("SUPABASE_URL"))

    frontend_url: str = Field(
        "http://localhost:3000",
        validation_alias=AliasChoices("FRONTEND_URL"),
    )

    database_url: str = Field(
        "postgresql+psycopg://miniagent:miniagent@localhost:5432/miniagent",
        validation_alias=AliasChoices("DATABASE_URL"),
    )

    tavily_api_key: str = Field("", validation_alias=AliasChoices("TAVILY_API_KEY"))

    langfuse_base_url: str = Field(
        "", validation_alias=AliasChoices("LANGFUSE_BASE_URL")
    )
    langfuse_public_key: str = Field(
        "", validation_alias=AliasChoices("LANGFUSE_PUBLIC_KEY")
    )
    langfuse_secret_key: str = Field(
        "", validation_alias=AliasChoices("LANGFUSE_SECRET_KEY")
    )
