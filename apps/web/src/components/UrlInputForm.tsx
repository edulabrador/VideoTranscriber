import { useState, type ReactNode } from "react";

import { postJson } from "../api/client";
import { useJobContext } from "../context/JobContext";
import { isInstagramUrl } from "../lib/validateInstagramUrl";
import type {
  AudioQuality,
  JobResponse,
  TranscriptionProfile,
} from "../api/types";
import { Icon } from "./Icon";

export function UrlInputForm({
  profile,
  audioQuality,
  children,
}: {
  profile: TranscriptionProfile;
  audioQuality: AudioQuality;
  children?: ReactNode;
}) {
  const { state, dispatch } = useJobContext();
  const [url, setUrl] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [force, setForce] = useState(false);
  const jobActive = Boolean(
    state.status &&
    !["completed", "failed", "cancelled"].includes(state.status),
  );

  const handlePaste = async () => {
    try {
      setUrl(await navigator.clipboard.readText());
      setValidationError(null);
    } catch {
      setValidationError(
        "No se pudo acceder al portapapeles. Pega el enlace manualmente.",
      );
    }
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!isInstagramUrl(url)) {
      setValidationError(
        "Introduce un enlace válido de YouTube, Instagram, TikTok o Twitter (X)",
      );
      return;
    }
    setValidationError(null);
    setSubmitting(true);
    try {
      const job = await postJson<JobResponse>("/api/jobs", {
        url,
        profile,
        audio_quality: audioQuality,
        force,
      });
      dispatch({ type: "START_JOB", jobId: job.id });
    } catch (error) {
      setValidationError(
        error instanceof Error
          ? error.message
          : "No se pudo iniciar la transcripción",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="url-form">
      <div className="field-label">
        <label htmlFor="video-url">Enlace del vídeo</label>
        <div className="url-input-wrap">
          <Icon name="link" size={17} />
          <input
            id="video-url"
            type="url"
            inputMode="url"
            autoComplete="off"
            value={url}
            onChange={(event) => {
              setUrl(event.target.value);
              if (validationError) setValidationError(null);
            }}
            placeholder="Pega aquí el enlace de tu vídeo..."
            aria-invalid={Boolean(validationError)}
            aria-describedby={validationError ? "url-error" : undefined}
          />
          <button type="button" onClick={handlePaste} className="paste-button">
            Pegar
          </button>
        </div>
      </div>
      {validationError && (
        <p id="url-error" role="alert" className="message error">
          {validationError}
        </p>
      )}
      {children}
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={force}
          onChange={(event) => setForce(event.target.checked)}
          disabled={jobActive || submitting}
        />
        Volver a transcribir, aunque exista un resultado guardado
      </label>
      <button
        type="submit"
        disabled={submitting || jobActive || !url}
        className="primary-button"
      >
        <span>
          {jobActive
            ? "Transcripción en curso..."
            : submitting
              ? "Preparando..."
              : "Transcribir vídeo"}
        </span>
        <Icon name="arrow" size={18} />
      </button>
    </form>
  );
}
