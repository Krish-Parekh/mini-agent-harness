from __future__ import annotations

import asyncio

from fastapi import APIRouter

from backend.api.deps import CurrentUser, SettingsDep
from backend.schemas.conversation import SandboxProviderOut
from miniagent.sandbox.factory import PROVIDER_LABELS, provider_problem

router = APIRouter()


@router.get("/sandbox/providers", response_model=list[SandboxProviderOut])
async def sandbox_providers(user: CurrentUser, settings: SettingsDep):
    problems = await asyncio.to_thread(
        lambda: {provider: provider_problem(settings, provider) for provider in PROVIDER_LABELS}
    )
    default = settings.sandbox_provider if problems.get(settings.sandbox_provider) is None else "local"
    return [
        SandboxProviderOut(
            id=provider,
            label=label,
            available=problems[provider] is None,
            default=provider == default,
            reason=problems[provider],
        )
        for provider, label in PROVIDER_LABELS.items()
    ]
