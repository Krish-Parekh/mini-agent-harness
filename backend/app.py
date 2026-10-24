from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import logfire
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import models  # noqa: F401
from backend.api.auth import router as auth_router
from backend.api.conversations import router
from backend.api.extensions import router as extensions_router
from backend.api.memories import router as memories_router
from backend.api.sandbox import router as sandbox_router
from backend.api.github import router as github_router
from backend.core import observability
from backend.core.db import make_engine, make_sessionmaker
from backend.core.jwt import SupabaseJWTVerifier
from backend.repository import (
    ConversationRepository,
    GitHubConnectionRepository,
    McpConnectionRepository,
    MemoryRepository,
    SkillRepository,
    UserRepository,
)
from backend.runtime import ConversationManager
from backend.runtime.attachments import Storage
from backend.runtime.mcp import load_config
from backend.service import AuthService, ConversationService
from miniagent.config import Settings, export_provider_keys
from miniagent.sandbox.factory import check_provider

# Provider SDKs read their credentials from the process environment, not
# from Settings, so .env has to reach os.environ before the startup check.
load_dotenv(override=False)
settings = Settings()
export_provider_keys(settings)
observability.configure(settings)
check_provider(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    app.state.verifier = SupabaseJWTVerifier(supabase_url=settings.supabase_url)

    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)

    repository = ConversationRepository(sessionmaker)
    users = UserRepository(sessionmaker)
    connections = GitHubConnectionRepository(sessionmaker)
    skills = SkillRepository(sessionmaker)
    mcp_connections = McpConnectionRepository(sessionmaker)
    memories = MemoryRepository(sessionmaker)
    manager = ConversationManager(settings, memories=memories)
    storage = (
        Storage(settings.supabase_url, settings.supabase_publishable_key)
        if settings.supabase_url and settings.supabase_publishable_key
        else None
    )
    service = ConversationService(
        manager,
        repository,
        connections,
        skills,
        mcp_connections,
        storage,
        load_config(Path(settings.mcp_config)),
    )
    service.start()
    await service.settle_interrupted_runs()
    await service.reconcile_sandboxes()

    app.state.users = users
    app.state.connections = connections
    app.state.skills = skills
    app.state.mcp_connections = mcp_connections
    app.state.memories = memories
    app.state.service = service
    app.state.auth_service = AuthService(users, connections)

    yield
    await engine.dispose()


app = FastAPI(title="MiniAgent Server", lifespan=lifespan)
logfire.instrument_fastapi(app, capture_headers=False)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(auth_router)
app.include_router(github_router)
app.include_router(extensions_router)
app.include_router(memories_router)
app.include_router(sandbox_router)
