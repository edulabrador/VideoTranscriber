import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.local_access import LocalDataAccess
from backend.api.routes import router
from backend.config import settings
from backend.core.audio import check_ffmpeg_available
from backend.core.pipeline import release_idle_models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_IDLE_CHECK_SECONDS = 30


async def _release_idle_models_periodically() -> None:
    while True:
        await asyncio.sleep(_IDLE_CHECK_SECONDS)
        try:
            await asyncio.to_thread(release_idle_models)
        except Exception:  # noqa: BLE001 - never let housekeeping stop the server
            logger.warning("No se pudo liberar la memoria de los modelos", exc_info=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if not check_ffmpeg_available():
        logger.warning(
            "No se encontraron ffmpeg/ffprobe en PATH. PyAV cubrirá la mayoría de archivos, "
            "pero algunos formatos podrían fallar. Consulta scripts/setup.sh."
        )
    reaper = asyncio.create_task(_release_idle_models_periodically())
    try:
        yield
    finally:
        reaper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reaper


app = FastAPI(title="VideoTranscriber API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(LocalDataAccess)

app.include_router(router)
