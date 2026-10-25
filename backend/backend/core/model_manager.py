import gc
import logging
import os
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path

_NVIDIA_DLL_HANDLES: list[object] = []
if sys.platform == "win32":
    nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    dll_dirs = sorted(nvidia_root.glob("*/bin"))
    os.environ["PATH"] = os.pathsep.join([*(str(path) for path in dll_dirs), os.environ["PATH"]])
    for dll_dir in dll_dirs:
        _NVIDIA_DLL_HANDLES.append(os.add_dll_directory(str(dll_dir)))

import ctranslate2  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402
from faster_whisper.utils import download_model  # noqa: E402

from backend.config import settings  # noqa: E402

logger = logging.getLogger(__name__)

CUDA_DEFAULT_MODEL = "large-v3-turbo"
CPU_DEFAULT_MODEL = "large-v3-turbo"


def select_device(preference: str = "auto") -> str:
    if preference in {"cuda", "cpu"}:
        return preference
    return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"


def resolve_model_size(configured: str, device: str) -> str:
    if configured != "auto":
        return configured
    return CUDA_DEFAULT_MODEL if device == "cuda" else CPU_DEFAULT_MODEL


def resolve_compute_type(configured: str, device: str) -> str:
    if configured != "auto":
        return configured
    if device != "cuda":
        return "int8"

    try:
        supported = ctranslate2.get_supported_compute_types("cuda")
    except Exception:  # noqa: BLE001 - CUDA capability probing is best effort
        supported = {"float16"}

    memory_mb = get_gpu_memory_mb()
    if (memory_mb is None or memory_mb <= 8192) and "int8_float16" in supported:
        return "int8_float16"
    if "float16" in supported:
        return "float16"
    return "int8_float32" if "int8_float32" in supported else "float32"


@lru_cache(maxsize=1)
def get_gpu_memory_mb() -> int | None:
    if os.name != "nt" and ctranslate2.get_cuda_device_count() == 0:
        return None
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        first_line = completed.stdout.strip().splitlines()[0]
        return int(first_line)
    except (FileNotFoundError, OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def recommended_batch_size(memory_mb: int | None, profile: str) -> int:
    if memory_mb is None:
        batch_size = 4
    elif memory_mb < 4096:
        batch_size = 2
    elif memory_mb < 7168:
        batch_size = 4
    elif memory_mb < 12288:
        batch_size = 8
    else:
        batch_size = 16
    return min(batch_size, 4) if profile == "precise" else batch_size


def resolve_batch_size(configured: int, device: str, profile: str) -> int:
    if device != "cuda":
        return 1
    if configured > 0:
        return min(configured, 4) if profile == "precise" else configured
    return recommended_batch_size(get_gpu_memory_mb(), profile)


class ModelCache:
    """Keeps recently used Whisper models so switching profiles does not reload from disk.

    On CUDA only the active model stays in VRAM; the others are parked in system
    RAM with CTranslate2's ``unload_model(to_cpu=True)`` and moved back on demand.
    """

    def __init__(self, max_models: int) -> None:
        self._max_models = max(1, max_models)
        self._models: OrderedDict[tuple[str, str, str], WhisperModel] = OrderedDict()
        self._active: tuple[str, str, str] | None = None
        self._last_used = time.monotonic()
        self._lock = threading.RLock()

    def get(self, model_size: str, device: str, compute_type: str) -> WhisperModel:
        key = (model_size, device, compute_type)
        with self._lock:
            self._last_used = time.monotonic()
            model = self._models.get(key)
            if model is not None and key == self._active:
                self._models.move_to_end(key)
                return model
            self._park_active()
            if model is not None:
                if not _resume(model):
                    self._models.pop(key, None)
                    model = None
            if model is None:
                model = self._load(model_size, device, compute_type)
                self._models[key] = model
            self._models.move_to_end(key)
            self._active = key
            while len(self._models) > self._max_models:
                self._models.popitem(last=False)
            self._last_used = time.monotonic()
            return model

    def touch(self) -> None:
        with self._lock:
            self._last_used = time.monotonic()

    def idle_seconds(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_used

    def loaded(self) -> list[str]:
        with self._lock:
            return [key[0] for key in self._models]

    def clear(self) -> bool:
        with self._lock:
            had_models = bool(self._models)
            self._models.clear()
            self._active = None
        if had_models:
            gc.collect()
        return had_models

    def _park_active(self) -> None:
        if self._active is None:
            return
        model = self._models.get(self._active)
        self._active = None
        if model is None or self._max_models == 1:
            self._models.clear()
            return
        if model.model.device == "cuda":
            try:
                model.model.unload_model(to_cpu=True)
            except Exception:  # noqa: BLE001 - parking is an optimisation, never a failure
                logger.warning("No se pudo mover el modelo a la RAM; se descarta", exc_info=True)
                self._models = OrderedDict(
                    (key, value) for key, value in self._models.items() if value is not model
                )

    @staticmethod
    def _load(model_size: str, device: str, compute_type: str) -> WhisperModel:
        was_cached = is_model_cached(model_size)
        logger.info(
            "Loading whisper model=%s device=%s compute_type=%s (%s)",
            model_size,
            device,
            compute_type,
            "cache hit" if was_cached else "downloading — first run only",
        )
        return WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=str(settings.models_dir),
        )


def _resume(model: WhisperModel) -> bool:
    try:
        if not model.model.model_is_loaded:
            model.model.load_model()
        return True
    except Exception:  # noqa: BLE001 - fall back to a fresh load from disk
        logger.warning("No se pudo reactivar el modelo aparcado; se recarga", exc_info=True)
        return False


model_cache = ModelCache(settings.max_cached_models)


def get_model(model_size: str, device: str, compute_type: str) -> WhisperModel:
    return model_cache.get(model_size, device, compute_type)


# Files faster-whisper downloads for a model (see faster_whisper.utils.download_model).
_MODEL_FILE_PATTERNS = (
    "config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*",
)


def _model_repo(model_size: str) -> str | None:
    from faster_whisper.utils import _MODELS

    if model_size in _MODELS:
        return _MODELS[model_size]
    return model_size if model_size.count("/") == 1 and not Path(model_size).exists() else None


def expected_download_bytes(model_size: str) -> int | None:
    """Total size of the files a first download fetches, or None when unknown."""
    repo = _model_repo(model_size)
    if repo is None:
        return None
    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(repo, files_metadata=True, timeout=10)
        return sum(
            sibling.size or 0
            for sibling in info.siblings or []
            if any(fnmatch(sibling.rfilename, pattern) for pattern in _MODEL_FILE_PATTERNS)
        ) or None
    except Exception:  # noqa: BLE001 - progress is informational only
        return None


def downloaded_bytes(model_size: str) -> int:
    """Bytes already in the Hugging Face cache folder of a model, partial files included."""
    repo = _model_repo(model_size)
    if repo is None:
        return 0
    folder = settings.models_dir / f"models--{repo.replace('/', '--')}" / "blobs"
    try:
        return sum(path.stat().st_size for path in folder.iterdir() if path.is_file())
    except OSError:
        return 0


@contextmanager
def report_download_progress(
    model_size: str, on_progress: Callable[[int, int | None], None], interval: float = 1.0,
) -> Iterator[None]:
    """Call ``on_progress(downloaded, total)`` periodically while a model downloads."""
    stop = threading.Event()
    total_holder: list[int | None] = [None]

    def watch() -> None:
        total_holder[0] = expected_download_bytes(model_size)
        while not stop.wait(interval):
            on_progress(downloaded_bytes(model_size), total_holder[0])

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        yield
    finally:
        stop.set()
        watcher.join(timeout=interval + 1)


def is_model_cached(model_size: str) -> bool:
    if (Path(model_size) / "model.bin").is_file():
        return True
    try:
        path = download_model(model_size, cache_dir=str(settings.models_dir), local_files_only=True)
        return (Path(path) / "model.bin").is_file()
    except Exception:  # Cache lookup is informational and must never prevent transcription.
        return False


def load_model_for_settings() -> tuple[WhisperModel, str, str, str]:
    device = select_device(settings.device)
    model_size = resolve_model_size(settings.model_size, device)
    compute_type = resolve_compute_type(settings.compute_type, device)
    model = get_model(model_size, device, compute_type)
    return model, model_size, device, compute_type
