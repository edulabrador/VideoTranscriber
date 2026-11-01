# Development Guide

## Repo layout

```
apps/web/                  React + TS + Vite + Tailwind frontend
backend/backend/
  config.py                 Settings (env-driven), single instance
  cli.py                    `transcriber` entry point
  api/                       FastAPI app, routes, Pydantic schemas
  core/
    errors.py                Typed exception hierarchy
    validators.py             Known platforms + any single-video yt-dlp extractor
    downloader.py             yt-dlp wrapper, Cobalt as fallback for TikTok/X
    audio.py                  ffmpeg wrapper (normalize, probe, availability)
    model_manager.py          hardware detection + ModelCache (parks models in RAM)
    transcriber.py            faster-whisper wrapper
    diarizer.py               speaker diarization (sherpa-onnx) + speaker assignment
    summarizer.py             optional summaries through a local Ollama server
    exporter.py                txt/md/srt/vtt/json writers (single source of formatting)
    history.py                 recent-history JSON store
    job_manager.py             in-memory job registry + cancellation
    pipeline.py                 shared orchestration, FIFO transcription turns,
                                idle model release; used by both API and CLI
models/  output/  temp/       gitignored runtime data
```

## Running services independently

Backend only:

```bash
uv run --project backend uvicorn backend.api.app:app --reload --port 8000
```

Frontend only:

```bash
pnpm --filter web dev
```

Both together: `pnpm dev` (uses `concurrently`, see root `package.json`).

## Job status state machine

```
queued → downloading → extracting_audio → transcribing → exporting → completed
                                                                     ↘ failed
   (any state) --cancel--> cancelling → cancelled
```

Cancellation is cooperative: `POST /api/jobs/{id}/cancel` sets a
`threading.Event` on the job record. `downloader.py`, `audio.py`, and
`transcriber.py` all check that event at natural iteration boundaries
(progress hook, subprocess poll loop, per-segment) and raise
`JobCancelledError`, which `pipeline.py` propagates and the job manager
records as `cancelled`.

## Adding a new export format

Add a writer function to `backend/backend/core/exporter.py` (mirroring
`write_txt`/`write_srt`/`write_json`), call it from `write_all` in the same
file, add the extension to `_ALLOWED_EXPORT_FORMATS` in
`backend/backend/api/routes.py`, and add an entry to the `FORMATS` array in
`apps/web/src/components/ExportMenu.tsx`. Do not duplicate formatting logic
in the frontend — it only downloads what the backend already wrote.

## Transcription options and the cache

`TranscriptionOptions` (language, task, initial prompt, word timestamps) travels
from the API or CLI through `pipeline.py` to faster-whisper and is stored in
`transcript.json`. `HistoryStore.find_cached` only reuses a result whose options,
model and beam size match; add any new option to `cache_fields()` so it becomes
part of that comparison. `resolve_job_model` is shared by the transcriber and the
cache lookup, so both always agree on the model a job uses.

## Queue and models

Jobs download in parallel but transcribe one at a time. `TranscriptionTurns`
grants the slot in arrival order and reports how many jobs are ahead.
`ModelCache` keeps up to `MAX_CACHED_MODELS`; on CUDA the inactive ones are moved
to RAM with CTranslate2's `unload_model(to_cpu=True)`. A background task in
`app.py` calls `release_idle_models()` every 30 s, which frees them after
`MODEL_IDLE_UNLOAD_SECONDS` only when no job holds or waits for the slot.

## Speaker diarization

`diarizer.diarize` downloads two ONNX models on first use (pinned SHA-256, only the
model file is read from the tarball), decodes the audio at 16 kHz and returns speaker
turns. Cancellation raises from the sherpa-onnx progress callback, which aborts the
native loop. `assign_speakers` gives each segment the speaker it overlaps most; with
word timestamps it labels each word and splits segments where the speaker changes.
The pipeline runs it inside the transcription turn, after Whisper, as the
`diarizing` stage. Set `VIDEO_TRANSCRIBER_LIVE_TEST=1` to run the test that
downloads the models and a real four-speaker recording.

## Editing, playback and summaries

`PATCH /api/jobs/{id}/transcript` applies text corrections and speaker names through
`HistoryStore.update_transcript`, which rewrites every export with `write_all`, so the
files on disk never disagree with what the UI shows. The pipeline keeps `audio.m4a`
(mono AAC, ~20 MB/h) unless `KEEP_AUDIO=false`; `GET /api/jobs/{id}/audio` serves it
with Range support. `summarizer.py` talks to Ollama over its HTTP API and splits long
transcripts into chunks of `CHUNK_CHARS`. Summaries run in the background:
`POST /api/jobs/{id}/summary` starts one (202, never two at once for the same job),
`GET` reports its state and progress message and `DELETE` cancels it between chunks.
The result carries `summary_outdated` when the transcript was edited after the summary.
The UI renders the Markdown with React elements only (`MarkdownText.tsx`), never as HTML.

## Concurrency and storage

Transcription jobs run on their own thread pool (`routes._JOB_EXECUTOR`), not on
asyncio's default one, so a long queue cannot starve `asyncio.to_thread` callers.
Routes that touch the disk or locks are plain `def` functions, which FastAPI runs in
its thread pool instead of on the event loop. `pipeline.PreparationSlots` limits
concurrent downloads and conversions (`MAX_CONCURRENT_DOWNLOADS`). On the CPU, speaker
identification keeps the transcription slot; after a GPU transcription it takes a
separate slot so the GPU is free for the next job.

`core/fileio.py` provides atomic writes (temporary file, `fsync`, rename) and an
inter-process file lock. `HistoryStore` uses both, so the server and the CLI can write
the history at the same time. A damaged history is backed up and rebuilt from the
`transcript.json` files instead of being overwritten. Deleting renames the folder to
`.deleting-*` first, so it is all or nothing; leftovers are removed at startup.

## Browser and model tests

`pnpm --dir apps/web e2e` starts `scripts/e2e_server.py` (the real API with Whisper,
diarization and Ollama simulated) and `vite preview`, then drives Chromium through
upload, speakers, playback, search, editing, summary and the phone layout. Set
`PLAYWRIGHT_CHROMIUM` to use a browser binary other than Playwright's, and
`E2E_SCREENSHOTS=<dir>` to save screenshots. `VIDEO_TRANSCRIBER_MODEL_TEST=1` enables
the tests that download Whisper tiny and the diarization models.

## Lint / typecheck

```bash
# backend
uv run --project backend ruff check backend
uv run --project backend mypy backend

# frontend
pnpm --filter web lint
pnpm --filter web build   # runs tsc --noEmit + vite build
```

## Debugging yt-dlp / ffmpeg issues

- yt-dlp errors surface as `DownloadError` or `PrivateContentError` (see
  `backend/backend/core/downloader.py`) — check the wrapped message for the
  underlying yt-dlp reason.
- ffmpeg failures capture the last 500 chars of stderr in
  `AudioExtractionError` — usually enough to diagnose a codec or corrupt-file
  issue.
- `GET /api/health` reports whether ffmpeg/ffprobe are on `PATH` and which
  device/compute_type will be used.
