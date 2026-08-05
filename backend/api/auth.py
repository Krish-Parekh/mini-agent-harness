from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import AuthServiceDep, ClaimsDep, CurrentUser
from backend.schemas import AuthState, SyncRequest

router = APIRouter(prefix="/auth")


@router.post("/sync", response_model=AuthState)
async def sync(body: SyncRequest, claims: ClaimsDep, auth: AuthServiceDep):
    return await auth.sync(claims, body.provider_token)


@router.get("/me", response_model=AuthState)
async def me(user: CurrentUser, auth: AuthServiceDep):
    return await auth.state(user)


@router.post("/github/disconnect")
async def disconnect_github(user: CurrentUser, auth: AuthServiceDep):
    await auth.disconnect_github(user.id)
    return {"connected": False}
