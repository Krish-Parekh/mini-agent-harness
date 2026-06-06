from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from backend.github_auth import GitHubAuth, router as github_router
from backend.manager import ConversationManager
from backend.router import router
from miniagent.config import Settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings
    app.state.github = GitHubAuth()
    app.state.manager = ConversationManager(settings, Path("data/events"))
    yield


app = FastAPI(title="MiniAgent Server", lifespan=lifespan)
app.include_router(router)
app.include_router(github_router)
