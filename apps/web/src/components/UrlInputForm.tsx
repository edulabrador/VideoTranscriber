import { useState, type ReactNode } from "react";

import { postJson } from "../api/client";
import { isTerminalStatus } from "../api/types";
import { useJobContext } from "../context/JobContext";
import { parseUrlList } from "../lib/videoUrls";
import type {
  AudioQuality,
  JobResponse,
  TranscriptionOptions,
  TranscriptionProfile,
} from "../api/types";
import { Icon } from "./Icon";

export function UrlInputForm({
  profile,
  audioQuality,
  options,
  onQueued,
  children,
}: {
  profile: TranscriptionProfile;
  audioQuality: AudioQuality;
  options: TranscriptionOptions;
  onQueued: () => void;
  children?: ReactNode;
}) {
  const { state, dispatch } = useJobContext();
  const [text, setText] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [force, setForce] = useState(false);
  const jobActive = Boolean(state.status && !isTerminalStatus(state.status));
  const { urls } = parseUrlList(text);

  const handlePaste = async () => {
    try {
      const pasted = await navigator.clipboard.readText();
      setText((current) =>
        current.trim() ? `${current.trim()}\n${pasted}` : pasted,
      );
      setValidationError(null);
    } catch {
      setValidationError(
        "No se pudo acceder al portapapeles. Pega el enlace manualmente.",
      );
    }
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const { urls: links, invalid } = parseUrlList(text);
    if (!links.length || invalid.length) {
      setValidationError(
        invalid.length
          ? `No parece un enlace: ${invalid.slice(0, 3).join(", ")}`
          : "Introduce al menos un enlace de vídeo",
      );
      return;
    }
    setValidationError(null);
    setNotice(null);
    setSubmitting(true);
    const failures: string[] = [];
    let first: string | null = null;
    for (const url of links) {
      try {
        const job = await postJson<JobResponse>("/api/jobs", {
          url,
          profile,
          audio_quality: audioQuality,
          force,
          ...options,
        });
        first ??= job.id;
      } catch (error) {
        failures.push(
          `${url}: ${error instanceof Error ? error.message : "no se pudo iniciar"}`,
        );
      }
    }
    setSubmitting(false);
    onQueued();
    // Keep the job on screen if one is running; new ones wait in the queue.
    if (first && !jobActive) dispatch({ type: "START_JOB", jobId: first });
    if (failures.length) {
      setValidationError(failures.join("\n"));
    } else {
      setText("");
      if (links.length > 1 || jobActive) {
        setNotice(
          links.length > 1
            ? `${links.length} enlaces añadidos a la cola.`
            : "Añadido a la cola.",
        );
      }
    }
  };

  return (
    <form onSubmit={handleSubmit} className="url-form">
      <div className="field-label">
        <label htmlFor="video-url">Enlace del vídeo</label>
        <div className="url-input-wrap">
          <Icon name="link" size={17} />
          <textarea
            id="video-url"
            rows={urls.length > 1 ? Math.min(urls.length, 6) : 1}
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              if (validationError) setValidationError(null);
              if (notice) setNotice(null);
            }}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                urls.length <= 1
              ) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Pega aquí el enlace de tu vídeo. Para varios, uno por línea..."
            aria-invalid={Boolean(validationError)}
            aria-describedby={validationError ? "url-error" : "url-hint"}
          />
          <button type="button" onClick={handlePaste} className="paste-button">
            Pegar
          </button>
        </div>
        <span id="url-hint" className="field-hint">
          YouTube, Instagram, TikTok, X y cientos de sitios más. Mayús+Intro
          añade otra línea.
        </span>
      </div>
      {validationError && (
        <p
          id="url-error"
          role="alert"
          className="message error"
          style={{ whiteSpace: "pre-line" }}
        >
          {validationError}
        </p>
      )}
      {notice && (
        <p role="status" className="message">
          {notice}
        </p>
      )}
      {children}
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={force}
          onChange={(event) => setForce(event.target.checked)}
          disabled={submitting}
        />
        Volver a transcribir, aunque exista un resultado guardado
      </label>
      <button
        type="submit"
        disabled={submitting || !urls.length}
        className="primary-button"
      >
        <span>
          {submitting
            ? "Preparando..."
            : urls.length > 1
              ? `Transcribir ${urls.length} vídeos`
              : jobActive
                ? "Añadir a la cola"
                : "Transcribir vídeo"}
        </span>
        <Icon name="arrow" size={18} />
      </button>
    </form>
  );
}
