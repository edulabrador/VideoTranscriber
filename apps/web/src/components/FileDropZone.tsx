import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";

import { postForm } from "../api/client";
import { isTerminalStatus } from "../api/types";
import { useJobContext } from "../context/JobContext";
import type {
  JobResponse,
  TranscriptionOptions,
  TranscriptionProfile,
} from "../api/types";
import { Icon } from "./Icon";

// Browsers do not always know the MIME type of these, so accept them by extension too.
const MEDIA_EXTENSIONS = [
  ".aac",
  ".flac",
  ".m4a",
  ".mka",
  ".mkv",
  ".mov",
  ".mp3",
  ".mp4",
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

  const onDrop = useCallback(
    async (accepted: File[]) => {
      if (!accepted.length) return;
      setError(null);
      setUploading(true);
      const failures: string[] = [];
      let first: string | null = null;
      for (const file of accepted) {
        const form = new FormData();
        form.append("file", file);
        form.append("profile", profile);
        form.append("task", options.task);
        form.append("word_timestamps", String(options.word_timestamps));
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
      onQueued();
      if (first && !jobActive) dispatch({ type: "START_JOB", jobId: first });
      if (failures.length) setError(failures.join("\n"));
    },
    [dispatch, profile, options, onQueued, jobActive],
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
