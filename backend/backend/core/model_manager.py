import logging
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

_NVIDIA_DLL_HANDLES: list[object] = []
if os.name == "nt":
    nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    dll_dirs = sorted(nvidia_root.glob("*/bin"))
    os.environ["PATH"] = os.pathsep.join([*(str(path) for path in dll_dirs), os.environ["PATH"]])
    for dll_dir in dll_dirs:
        _NVIDIA_DLL_HANDLES.append(os.add_dll_directory(str(dll_dir)))

import ctranslate2  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

from backend.config import settings  # noqa: E402

logger = logging.getLogger(__name__)

CUDA_DEFAULT_MODEL = "large-v3-turbo"
CPU_DEFAULT_MODEL = "large-v3-turbo"


def select_device_and_compute_type(preference: str = "auto") -> tuple[str, str]:
    if preference == "cuda":
        return "cuda", "float16"
    if preference == "cpu":
        return "cpu", "int8"

    if ctranslate2.get_cuda_device_count() > 0:
        return "cuda", "float16"
    # CPU covers Apple Silicon too — CTranslate2 has no Metal/MPS backend, so
    # there is no GPU acceleration path on Apple Silicon, only CPU int8.
    return "cpu", "int8"


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


@lru_cache(maxsize=1)
def get_model(model_size: str, device: str, compute_type: str) -> WhisperModel:
    cache_dir = settings.models_dir / model_size
    was_cached = cache_dir.exists() and any(cache_dir.iterdir())
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


def load_model_for_settings() -> tuple[WhisperModel, str, str, str]:
    device, _ = select_device_and_compute_type(settings.device)
    model_size = resolve_model_size(settings.model_size, device)
    compute_type = resolve_compute_type(settings.compute_type, device)
    model = get_model(model_size, device, compute_type)
    return model, model_size, device, compute_type
