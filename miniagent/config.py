from __future__ import annotations

import os
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ReasoningEffort = Literal["low", "medium", "high"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MINIAGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    model: str = "anthropic/claude-sonnet-5-5"
    policy_model: str = "anthropic/claude-haiku-5-5"
    max_tokens: int = 16_384
    temperature: float = 0.0
    workspace_dir: str = "./workspace"
    mcp_config: str = "mcp.json"
    max_iterations: int = 50
    explore_iterations: int = 50
    fork_iterations: int = 150
    reasoning_effort: ReasoningEffort | None = None

    supabase_url: str = Field("", validation_alias=AliasChoices("SUPABASE_URL"))
    supabase_publishable_key: str = Field(
        "", validation_alias=AliasChoices("SUPABASE_PUBLISHABLE_KEY")
    )

    frontend_url: str = Field(
        "http://localhost:3000",
        validation_alias=AliasChoices("FRONTEND_URL"),
    )

    database_url: str = Field(
        "postgresql+psycopg://miniagent:miniagent@localhost:5432/miniagent",
        validation_alias=AliasChoices("DATABASE_URL"),
    )

    tavily_api_key: str = Field("", validation_alias=AliasChoices("TAVILY_API_KEY"))

    anthropic_api_key: str = Field(
        "", validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")
    )

    langfuse_base_url: str = Field(
        "", validation_alias=AliasChoices("LANGFUSE_BASE_URL")
    )
    langfuse_public_key: str = Field(
        "", validation_alias=AliasChoices("LANGFUSE_PUBLIC_KEY")
    )
    langfuse_secret_key: str = Field(
        "", validation_alias=AliasChoices("LANGFUSE_SECRET_KEY")
    )

    sandbox_provider: Literal[
        "local", "docker", "e2b", "daytona", "modal", "vercel", "space"
    ] = "docker"
    sandbox_lifetime_s: int = 3600
    sandbox_idle_stop_s: int = 1800
    sandbox_cpu: float = 2
    sandbox_memory_mb: int = 4096

    docker_image: str = "miniagent-sandbox:latest"

    e2b_template: str = ""
    daytona_image: str = ""
    modal_app: str = "miniagent"

    space_api_url: str = Field(
        "", validation_alias=AliasChoices("MINIAGENT_SPACE_API_URL", "SPACE_API_URL")
    )
    space_data_plane_url: str = Field(
        "",
        validation_alias=AliasChoices(
            "MINIAGENT_SPACE_DATA_PLANE_URL", "SPACE_DATA_PLANE_URL"
        ),
    )
    space_token: str = Field(
        "", validation_alias=AliasChoices("MINIAGENT_SPACE_TOKEN", "SPACE_API_TOKEN")
    )
    space_email: str = ""
    space_password: str = ""
    space_template: str = "code-runtime:latest"
    space_allow_internet: bool = True
    space_egress_profiles: str = ""


def export_provider_keys(settings: Settings) -> None:
    if settings.anthropic_api_key:
        os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)
