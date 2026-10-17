"""Run with one worker: uvicorn app.main:app --host 127.0.0.1 --port 8000."""
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .contract import load_item_sequences
from .engine import InferenceEngine
from .middleware import RequestGuard
from .routes import router
from .service import PredictionEngine, PredictionService


def create_app(
    settings: Settings | None = None,
    engine_factory: Callable[[Settings], PredictionEngine] = InferenceEngine,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings.validate_key()
        await run_in_threadpool(lambda: settings.limits)
        item_sequences = await run_in_threadpool(load_item_sequences, settings)
        engine = await run_in_threadpool(engine_factory, settings)
        service = PredictionService(engine, item_sequences, settings)
        del engine
        application.state.inference = service
        try:
            yield
        finally:
            application.state.inference = None
            await run_in_threadpool(service.close)

    application = FastAPI(
        title='PillGuide Model H', version='2.0.0', lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    application.state.settings = settings
    application.state.inference = None
    application.add_middleware(RequestGuard, settings=settings)
    application.include_router(router)
    return application


app = create_app()
