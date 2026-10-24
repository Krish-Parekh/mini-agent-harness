from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from miniagent.config import Settings
from miniagent.sandbox.base import Sandbox

HOST_GIT_PROVIDERS = frozenset({"local", "docker"})
FULL_ACCESS_PROVIDERS = frozenset({"docker"})

_SDK = {
    "docker": ("docker", "docker"),
    "e2b": ("e2b", "e2b"),
    "daytona": ("daytona", "daytona"),
    "modal": ("modal", "modal"),
    "vercel": ("vercel.sandbox", "vercel"),
}

_CREDENTIALS: dict[str, list[tuple[str, ...]]] = {
    "e2b": [("E2B_API_KEY",)],
    "daytona": [("DAYTONA_API_KEY", "DAYTONA_JWT_TOKEN")],
    "modal": [("MODAL_TOKEN_ID",), ("MODAL_TOKEN_SECRET",)],
    "vercel": [("VERCEL_OIDC_TOKEN", "VERCEL_TOKEN")],
}


class SandboxConfigError(Exception):
    pass


def is_host_git(provider: str) -> bool:
    return provider in HOST_GIT_PROVIDERS


def allows_full_access(provider: str) -> bool:
    return provider in FULL_ACCESS_PROVIDERS


PROVIDER_LABELS = {
    "local": "Local",
    "docker": "Docker",
    "e2b": "E2B",
    "daytona": "Daytona",
    "modal": "Modal",
    "vercel": "Vercel",
    "space": "SPACE",
}


def provider_problem(settings: Settings, provider: str) -> str | None:
    if provider not in PROVIDER_LABELS:
        return f"unknown sandbox provider {provider!r}"
    try:
        _check(settings, provider)
    except SandboxConfigError as exc:
        return str(exc)
    if provider == "docker":
        from miniagent.sandbox.docker import docker_problem

        return docker_problem(settings.docker_image)
    return None


def default_provider(settings: Settings) -> str:
    if provider_problem(settings, settings.sandbox_provider) is None:
        return settings.sandbox_provider
    return "local"


def check_provider(settings: Settings) -> None:
    _check(settings, settings.sandbox_provider)


def _check(settings: Settings, provider: str) -> None:
    if provider in _SDK:
        module, extra = _SDK[provider]
        try:
            found = importlib.util.find_spec(module) is not None
        except ModuleNotFoundError:
            found = False
        if not found:
            raise SandboxConfigError(
                f"sandbox provider {provider!r} needs its SDK: run `uv sync --extra {extra}`"
            )
    for choices in _CREDENTIALS.get(provider, []):
        if not any(os.environ.get(name) for name in choices):
            raise SandboxConfigError(
                f"sandbox provider {provider!r} needs {' or '.join(choices)} in the environment"
            )
    if provider == "vercel" and os.environ.get("VERCEL_TOKEN") and not os.environ.get("VERCEL_OIDC_TOKEN"):
        for name in ("VERCEL_TEAM_ID", "VERCEL_PROJECT_ID"):
            if not os.environ.get(name):
                raise SandboxConfigError(f"sandbox provider 'vercel' with VERCEL_TOKEN also needs {name}")
    if provider == "space":
        if not settings.space_api_url or not settings.space_data_plane_url:
            raise SandboxConfigError(
                "sandbox provider 'space' needs SPACE_API_URL and SPACE_DATA_PLANE_URL"
            )
        if not settings.space_token and not (settings.space_email and settings.space_password):
            raise SandboxConfigError(
                "sandbox provider 'space' needs SPACE_API_TOKEN, or MINIAGENT_SPACE_EMAIL and MINIAGENT_SPACE_PASSWORD"
            )


def build_sandbox(
    settings: Settings,
    cid: str,
    *,
    provider: str | None = None,
    workspace_dir: str | None = None,
    sandbox_id: str | None = None,
    host_mounts: dict[str, str] | None = None,
) -> Sandbox:
    """Build the sandbox for one Conversation. Remote providers connect
    lazily, so this never blocks on the network."""
    provider = provider or settings.sandbox_provider
    name = f"miniagent-{cid}"
    if provider == "local":
        from miniagent.sandbox.local import LocalSandbox

        return LocalSandbox(workspace_dir or settings.workspace_dir)
    if provider == "docker":
        from miniagent.sandbox.docker import DockerSandbox

        ws = str(Path(workspace_dir or settings.workspace_dir).resolve())
        mounts = {str(Path(p).resolve()): mode for p, mode in (host_mounts or {ws: "rw"}).items()}
        return DockerSandbox(
            workspace_dir=ws,
            image=settings.docker_image,
            mounts=mounts,
            conversation_id=cid,
            sandbox_id=sandbox_id,
            name=None if sandbox_id else name,
            cpus=settings.sandbox_cpu,
            memory_mb=settings.sandbox_memory_mb,
        )
    if provider == "space":
        from miniagent.sandbox.space import SpaceConfig, SpaceSandbox

        config = SpaceConfig(
            api_url=settings.space_api_url,
            data_plane_url=settings.space_data_plane_url,
            template=settings.space_template,
            token=settings.space_token,
            email=settings.space_email,
            password=settings.space_password,
            allow_internet=settings.space_allow_internet,
            egress_profiles=settings.space_egress_profiles,
            vcpu=int(settings.sandbox_cpu) or None,
            memory_mib=settings.sandbox_memory_mb or None,
        )
        kwargs = {"workspace_dir": workspace_dir} if workspace_dir else {}
        return SpaceSandbox(config, sandbox_id=sandbox_id, name=name, **kwargs)
    if provider == "e2b":
        from miniagent.sandbox.e2b import E2BSandbox

        kwargs = {"workspace_dir": workspace_dir} if workspace_dir else {}
        return E2BSandbox(
            template=settings.e2b_template or None,
            lifetime_s=settings.sandbox_lifetime_s,
            sandbox_id=sandbox_id,
            name=name,
            **kwargs,
        )
    if provider == "daytona":
        from miniagent.sandbox.daytona import DaytonaSandbox

        return DaytonaSandbox(
            image=settings.daytona_image or None,
            cpus=settings.sandbox_cpu,
            memory_mb=settings.sandbox_memory_mb,
            sandbox_id=sandbox_id,
            name=name,
            workspace_dir=workspace_dir,
        )
    if provider == "modal":
        from miniagent.sandbox.modal import ModalSandbox

        kwargs = {"workspace_dir": workspace_dir} if workspace_dir else {}
        return ModalSandbox(
            app_name=settings.modal_app,
            lifetime_s=settings.sandbox_lifetime_s,
            cpus=settings.sandbox_cpu,
            memory_mb=settings.sandbox_memory_mb,
            sandbox_id=sandbox_id,
            name=name,
            **kwargs,
        )
    if provider == "vercel":
        from miniagent.sandbox.vercel import VercelSandbox

        kwargs = {"workspace_dir": workspace_dir} if workspace_dir else {}
        return VercelSandbox(
            lifetime_s=settings.sandbox_lifetime_s,
            cpus=settings.sandbox_cpu,
            sandbox_id=sandbox_id,
            name=name,
            **kwargs,
        )
    raise SandboxConfigError(f"unknown sandbox provider {provider!r}")
