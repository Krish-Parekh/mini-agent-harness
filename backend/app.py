from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend import models  # noqa: F401 — register ORM tables on Base.metadata
from backend.api.conversations import router
from backend.api.github import router as github_router
from backend.core.db import Base, make_engine, make_sessionmaker
from backend.repository import ConversationRepository
from backend.runtime import ConversationManager, GitHubAuth
from backend.service import ConversationService
from miniagent.config import Settings

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    app.state.github = GitHubAuth()

    engine = make_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS plan JSONB")
        )
        await conn.execute(
            text(
                "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS "
                "implementing_plan BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS pr_number INTEGER")
        )
        await conn.execute(
            text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS pr_url TEXT")
        )
    sessionmaker = make_sessionmaker(engine)

    repository = ConversationRepository(sessionmaker)
    manager = ConversationManager(settings)
    service = ConversationService(manager, repository)
    service.start()
    app.state.service = service

    yield
    await engine.dispose()


app = FastAPI(title="MiniAgent Server", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(github_router)
