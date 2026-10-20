import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";

import { postForm } from "../api/client";
import { useJobContext } from "../context/JobContext";
import type { JobResponse, TranscriptionProfile } from "../api/types";
import { Icon } from "./Icon";

export function FileDropZone({ profile }: { profile: TranscriptionProfile }) {
  const { state, dispatch } = useJobContext();
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const jobActive = Boolean(
    state.status &&
    !["completed", "failed", "cancelled"].includes(state.status),
  );
  const disabled = jobActive || uploading;

  const onDrop = useCallback(
    async (accepted: File[]) => {
      const file = accepted[0];
      if (!file) return;
      setError(null);
      setUploading(true);
      const form = new FormData();
      form.append("file", file);
      form.append("profile", profile);
      try {
        const job = await postForm<JobResponse>("/api/jobs/upload", form);
        dispatch({ type: "START_JOB", jobId: job.id });
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "No se pudo subir el archivo",
        );
      } finally {
        setUploading(false);
      }
    },
    [dispatch, profile],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "audio/*": [], "video/*": [] },
    multiple: false,
    disabled,
    onDropRejected: () =>
      setError("Selecciona un único archivo de audio o vídeo."),
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
              ? "Ya hay una transcripción en curso"
              : isDragActive
                ? "Suéltalo. Nosotros nos encargamos."
                : "Arrastra tu archivo hasta aquí"}
        </h3>
        <p>
          {disabled ? (
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
        <p role="alert" className="message error" style={{ marginTop: 12 }}>
          {error}
        </p>
      )}
    </div>
  );
}
