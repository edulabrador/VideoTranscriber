from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    models_dir: Path = REPO_ROOT / "models"
    output_dir: Path = REPO_ROOT / "output"
    temp_dir: Path = REPO_ROOT / "temp"
    history_file: Path = REPO_ROOT / "backend" / "data" / "history.json"

    cookies_file: Path | None = None
    cobalt_api_url: str | None = "http://127.0.0.1:9187"

    @field_validator("cookies_file", "cobalt_api_url", mode="before")
    @classmethod
    def empty_optional_setting_is_none(cls, value):
        return None if value == "" else value

    model_size: str = "auto"
    device: str = "auto"
    compute_type: str = "auto"
    batch_size: int = 0
    beam_size: int = 1

    cors_origins: list[str] = ["http://127.0.0.1:5187"]
    max_history_entries: int = 50
    max_upload_bytes: int = Field(default=512 * 1024 * 1024, gt=0)
    audio_preparation_timeout_seconds: float = Field(default=600, gt=0)
    # Models kept between jobs. On CUDA only the active one uses VRAM; the rest wait in RAM.
    max_cached_models: int = Field(default=2, ge=1)
    # Free every model after this many idle seconds. 0 keeps them loaded forever.
    model_idle_unload_seconds: float = Field(default=900, ge=0)
    # Speaker clustering when the number of speakers is not given. Higher merges more
    # voices into one speaker; lower splits them into more.
    diarization_threshold: float = Field(default=0.5, gt=0, lt=2)

    def ensure_dirs(self) -> None:
        for path in (self.models_dir, self.output_dir, self.temp_dir, self.history_file.parent):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
