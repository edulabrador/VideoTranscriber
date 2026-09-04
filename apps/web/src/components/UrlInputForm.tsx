import { useState } from "react";

import { postJson } from "../api/client";
import { useJobContext } from "../context/JobContext";
import { isInstagramUrl } from "../lib/validateInstagramUrl";
import type { JobResponse } from "../api/types";

export function UrlInputForm() {
  const { state, dispatch } = useJobContext();
  const [url, setUrl] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const jobActive = Boolean(
    state.status && !["completed", "failed", "cancelled"].includes(state.status),
  );

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      setUrl(text);
      setValidationError(null);
    } catch {
      setValidationError("No se pudo acceder al portapapeles. Pega el enlace manualmente.");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isInstagramUrl(url)) {
      setValidationError("Introduce un enlace válido de Instagram, TikTok o Twitter (X)");
      return;
    }
    setValidationError(null);
    setSubmitting(true);
    try {
      const job = await postJson<JobResponse>("/api/jobs", { url });
      dispatch({ type: "START_JOB", jobId: job.id });
    } catch (err) {
      setValidationError(err instanceof Error ? err.message : "No se pudo iniciar la transcripción");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div>
        <label htmlFor="video-url" className="text-sm font-bold text-stone-800 dark:text-stone-100">Enlace del vídeo</label>
        <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">Pega el enlace de una publicación que contenga vídeo.</p>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative min-w-0 flex-1">
          <svg viewBox="0 0 24 24" className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-stone-400" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M10.5 13.5a4 4 0 0 0 5.66 0l2.34-2.34a4 4 0 0 0-5.66-5.66l-1.34 1.34" />
            <path d="M13.5 10.5a4 4 0 0 0-5.66 0L5.5 12.84a4 4 0 0 0 5.66 5.66l1.34-1.34" />
          </svg>
          <input
            id="video-url"
            type="url"
            inputMode="url"
            autoComplete="off"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              if (validationError) setValidationError(null);
            }}
            placeholder="https://instagram.com/reel/..."
            aria-invalid={Boolean(validationError)}
            className="w-full rounded-2xl border border-stone-200 bg-stone-50 py-3.5 pl-11 pr-4 text-sm shadow-inner transition placeholder:text-stone-400 focus:border-brand-500 dark:border-stone-700 dark:bg-stone-950/60 dark:text-stone-100"
          />
        </div>
        <button
          type="button"
          onClick={handlePaste}
          className="rounded-2xl border border-stone-200 bg-white px-5 py-3.5 text-sm font-semibold text-stone-700 shadow-sm transition hover:-translate-y-0.5 hover:border-brand-300 hover:text-brand-600 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-200 dark:hover:border-brand-700 dark:hover:text-brand-400"
        >
          Pegar
        </button>
      </div>
      {validationError && <p role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-950/30 dark:text-red-400">{validationError}</p>}
      <button
        type="submit"
        disabled={submitting || jobActive || !url}
        className="group flex items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-brand-700 via-brand-500 to-cyan-400 px-5 py-3.5 text-sm font-bold text-white shadow-glow transition hover:-translate-y-0.5 hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
      >
        {jobActive ? "Transcripción en curso..." : submitting ? "Preparando..." : "Transcribir vídeo"}
        {!submitting && !jobActive && (
          <svg viewBox="0 0 24 24" className="h-4 w-4 transition-transform group-hover:translate-x-0.5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="m9 18 6-6-6-6" />
          </svg>
        )}
      </button>
    </form>
  );
}
