from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import VERSION, router
from app.api.stream import stream_router
from app.config import get_settings
from app.pipeline.runner import build_pipeline

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.pipeline = build_pipeline(get_settings())
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="voice-agent", version=VERSION, lifespan=lifespan)
    app.include_router(router)
    app.include_router(stream_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    return app


app = create_app()
