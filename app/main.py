from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents.jobs import ScorecardJobs
from app.agents.runtime import build_agent_runtime
from app.api.agents import agents_router
from app.api.routes import VERSION, router
from app.api.stream import stream_router
from app.config import get_settings
from app.pipeline.runner import build_pipeline

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.pipeline = build_pipeline(get_settings())
    settings = get_settings()
    pipeline = app.state.pipeline
    app.state.agents = build_agent_runtime(settings, pipeline.stt, pipeline.tts)
    app.state.scorecard_jobs = ScorecardJobs(app.state.agents, max_waiting=settings.scorecard_queue_max)
    yield
    app.state.scorecard_jobs.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="voice-agent", version=VERSION, lifespan=lifespan)
    app.include_router(router)
    app.include_router(stream_router)
    app.include_router(agents_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(STATIC_DIR / "home.html", media_type="text/html")

    @app.get("/talk", include_in_schema=False)
    def talk() -> FileResponse:
        return FileResponse(STATIC_DIR / "talk.html", media_type="text/html")

    return app


app = create_app()
