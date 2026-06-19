from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend import models  # noqa: F401 — register ORM tables on Base.metadata
from backend.api.conversations import router
from backend.api.github import router as github_router
from backend.api.skills import router as skills_router
from backend.core.db import Base, make_engine, make_sessionmaker
from backend.repository import ConversationRepository
from backend.runtime import ConversationManager, GitHubAuth
from backend.service import ConversationService
from miniagent.config import Settings
from miniagent.skills import SkillLibrary

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    app.state.github = GitHubAuth()
    skills = SkillLibrary(settings.skills_dir)
    app.state.skills = skills

    engine = make_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Live run-elapsed for the sidebar; NULL means not currently running.
        # Same naive TIMESTAMP type as created_at/updated_at so the frontend
        # parses them all consistently.
        await conn.execute(
            text(
                "ALTER TABLE conversations "
                "ADD COLUMN IF NOT EXISTS run_started_at TIMESTAMP"
            )
        )
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
    manager = ConversationManager(settings, skills=skills)
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
app.include_router(skills_router)
