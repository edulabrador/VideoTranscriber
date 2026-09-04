import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from backend.core.transcriber import TranscriptionResult

JobStatus = Literal[
    "queued",
    "downloading",
    "extracting_audio",
    "transcribing",
    "exporting",
    "completed",
    "failed",
    "cancelling",
    "cancelled",
]

# Coarse, stage-weighted progress — intentionally approximate rather than
# plumbing true byte/frame-level progress from yt-dlp/ffmpeg/whisper to the UI.
_STAGE_PROGRESS: dict[JobStatus, int] = {
    "queued": 0,
    "downloading": 5,
    "extracting_audio": 35,
    "transcribing": 45,
    "exporting": 95,
    "completed": 100,
    "failed": 100,
    "cancelling": 99,
    "cancelled": 100,
}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@dataclass
class JobRecord:
    id: str
    status: JobStatus = "queued"
    stage_message: str = "En espera"
    progress_percent: int = 0
    result: TranscriptionResult | None = None
    error: dict | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class JobManager:
    def __init__(self, max_jobs: int = 20) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()
        self._max_jobs = max_jobs

    def create_job(self, job_id: str | None = None) -> JobRecord:
        with self._lock:
            if job_id and job_id in self._jobs:
                return self._jobs[job_id]
            while len(self._jobs) >= self._max_jobs:
                finished_id = next(
                    (
                        existing_id
                        for existing_id, existing in self._jobs.items()
                        if existing.status in _TERMINAL_STATUSES
                    ),
                    None,
                )
                if finished_id is None:
                    break
                self._jobs.pop(finished_id)
            job = JobRecord(id=job_id or f"job_{uuid.uuid4().hex[:10]}")
            self._jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        message: str,
        progress_percent: int | None = None,
    ) -> None:
        job = self.get_job(job_id)
        if job is not None:
            job.status = status
            job.stage_message = message
            progress = _STAGE_PROGRESS[status] if progress_percent is None else progress_percent
            job.progress_percent = max(0, min(100, progress))

    def set_result(
        self,
        job_id: str,
        result: TranscriptionResult,
        message: str = "Transcripción completada.",
    ) -> None:
        job = self.get_job(job_id)
        if job is not None:
            job.result = result
            job.status = "completed"
            job.stage_message = message
            job.progress_percent = 100

    def set_error(self, job_id: str, code: str, message: str, status: JobStatus = "failed") -> None:
        job = self.get_job(job_id)
        if job is not None:
            job.status = status
            job.error = {"code": code, "message": message}
            job.stage_message = message
            job.progress_percent = 100

    def request_cancel(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if job is None or job.status in ("completed", "failed", "cancelled"):
            return False
        job.cancel_event.set()
        job.status = "cancelling"
        job.progress_percent = 99
        return True


job_manager = JobManager()
