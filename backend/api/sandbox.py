from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import CurrentUser, SettingsDep
from backend.schemas.conversation import SandboxProviderOut
from miniagent.sandbox.factory import PROVIDER_LABELS, provider_problem

router = APIRouter()


@router.get("/sandbox/providers", response_model=list[SandboxProviderOut])
async def sandbox_providers(user: CurrentUser, settings: SettingsDep):
    providers = []
    for provider, label in PROVIDER_LABELS.items():
        problem = provider_problem(settings, provider)
        providers.append(
            SandboxProviderOut(
                id=provider,
                label=label,
                available=problem is None,
                default=provider == settings.sandbox_provider,
                reason=problem,
            )
        )
    return providers
