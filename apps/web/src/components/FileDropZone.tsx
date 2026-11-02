import { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";

import { getJson, postForm } from "../api/client";
import { formatBytes } from "../lib/apiErrors";
import { isTerminalStatus } from "../api/types";
import { useJobContext } from "../context/JobContext";
import type {
  HealthResponse,
  JobResponse,
  TranscriptionOptions,
  TranscriptionProfile,
} from "../api/types";
import { Icon } from "./Icon";

// Browsers do not always know the MIME type of these, so accept them by extension too.
// Same list as the server accepts (backend/api/routes.py).
const MEDIA_EXTENSIONS = [
  ".aac",
  ".aiff",
  ".amr",
  ".avi",
  ".flac",
  ".flv",
  ".m4a",
  ".m4v",
  ".mka",
  ".mkv",
  ".mov",
  ".mp3",
  ".mp4",
  ".mpeg",
  ".mpg",
  ".oga",
  ".ogg",
  ".opus",
  ".ts",
  ".wav",
  ".weba",
  ".webm",
  ".wma",
  ".wmv",
  ".3gp",
];

export function FileDropZone({
  profile,
  options,
  onQueued,
}: {
  profile: TranscriptionProfile;
  options: TranscriptionOptions;
  onQueued: () => void;
}) {
  const { state, dispatch } = useJobContext();
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const jobActive = Boolean(state.status && !isTerminalStatus(state.status));
  const disabled = uploading;
  const [maxBytes, setMaxBytes] = useState<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getJson<HealthResponse>("/api/health", controller.signal)
      .then((health) => setMaxBytes(health.max_upload_bytes || null))
      .catch(() => undefined); // The server still enforces the limit.
    return () => controller.abort();
  }, []);

  const onDrop = useCallback(
    async (accepted: File[]) => {
      if (!accepted.length) return;
      setError(null);
      const failures: string[] = [];
      // Refuse oversized files before sending them: the server would only stop
      // the upload once the browser had already pushed the whole file.
      const files = accepted.filter((file) => {
        if (maxBytes && file.size > maxBytes) {
          failures.push(
            `${file.name}: supera el tamaño máximo de ${formatBytes(maxBytes)}`,
          );
          return false;
        }
        return true;
      });
      setUploading(files.length > 0);
      let first: string | null = null;
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        form.append("profile", profile);
        form.append("task", options.task);
        form.append("word_timestamps", String(options.word_timestamps));
        form.append("diarize", String(options.diarize));
        if (options.diarize && options.num_speakers) {
          form.append("num_speakers", String(options.num_speakers));
        }
        if (options.language) form.append("language", options.language);
        if (options.initial_prompt)
          form.append("initial_prompt", options.initial_prompt);
        try {
          const job = await postForm<JobResponse>("/api/jobs/upload", form);
          first ??= job.id;
        } catch (err) {
          failures.push(
            `${file.name}: ${err instanceof Error ? err.message : "no se pudo subir"}`,
          );
        }
      }
      setUploading(false);
      if (files.length) onQueued();
      if (first && !jobActive) dispatch({ type: "START_JOB", jobId: first });
      if (failures.length) setError(failures.join("\n"));
    },
    [dispatch, profile, options, onQueued, jobActive, maxBytes],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "audio/*": MEDIA_EXTENSIONS, "video/*": MEDIA_EXTENSIONS },
    multiple: true,
    disabled,
    onDropRejected: () => setError("Selecciona archivos de audio o vídeo."),
  });

  return (
    <div>
      <div
        {...getRootProps({
          role: "button",
          "aria-label": "Seleccionar archivo de audio o vídeo",
          "aria-disabled": disabled,
        })}
        className={`drop-zone ${isDragActive ? "drag-active" : ""} ${disabled ? "disabled" : ""}`}
      >
        <input {...getInputProps()} />
        <span className="drop-icon">
          <Icon name="upload" size={22} />
        </span>
        <h3>
          {uploading
            ? "Subiendo archivo..."
            : jobActive
              ? "Arrastra más archivos para añadirlos a la cola"
              : isDragActive
                ? "Suéltalo. Nosotros nos encargamos."
                : "Arrastra tu archivo hasta aquí"}
        </h3>
        <p>
          {uploading ? (
            "Tu archivo está en buenas manos."
          ) : (
            <>
              o <span className="text-accent">elige uno de tu ordenador</span>
            </>
          )}
        </p>
        <small>Audio y vídeo · procesamiento local</small>
      </div>
      {error && (
        <p
          role="alert"
          className="message error"
          style={{ marginTop: 12, whiteSpace: "pre-line" }}
        >
          {error}
        </p>
      )}
    </div>
  );
}
