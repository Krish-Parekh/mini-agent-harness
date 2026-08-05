from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import models  # noqa: F401
from backend.api.auth import router as auth_router
from backend.api.conversations import router
from backend.api.github import router as github_router
from backend.core.db import make_engine, make_sessionmaker
from backend.core.jwt import SupabaseJWTVerifier
from backend.repository import (
    ConversationRepository,
    GitHubConnectionRepository,
    UserRepository,
)
from backend.runtime import ConversationManager
from backend.service import AuthService, ConversationService
from miniagent.config import Settings

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    app.state.verifier = SupabaseJWTVerifier(supabase_url=settings.supabase_url)

    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)

    repository = ConversationRepository(sessionmaker)
    users = UserRepository(sessionmaker)
    connections = GitHubConnectionRepository(sessionmaker)
    manager = ConversationManager(settings)
    service = ConversationService(manager, repository, connections)
    service.start()

    app.state.users = users
    app.state.connections = connections
    app.state.service = service
    app.state.auth_service = AuthService(users, connections)

    yield
    await engine.dispose()


app = FastAPI(title="MiniAgent Server", lifespan=lifespan)
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
