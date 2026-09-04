import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";

import { postForm } from "../api/client";
import { useJobContext } from "../context/JobContext";
import type { JobResponse, TranscriptionProfile } from "../api/types";

export function FileDropZone({ profile }: { profile: TranscriptionProfile }) {
  const { state, dispatch } = useJobContext();
  const [error, setError] = useState<string | null>(null);
  const jobActive = Boolean(
    state.status && !["completed", "failed", "cancelled"].includes(state.status),
  );

  const onDrop = useCallback(
    async (accepted: File[]) => {
      const file = accepted[0];
      if (!file) return;
      setError(null);
      const form = new FormData();
      form.append("file", file);
      form.append("profile", profile);
      try {
        const job = await postForm<JobResponse>("/api/jobs/upload", form);
        dispatch({ type: "START_JOB", jobId: job.id });
      } catch (err) {
        setError(err instanceof Error ? err.message : "No se pudo subir el archivo");
      }
    },
    [dispatch, profile],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "audio/*": [], "video/*": [] },
    multiple: false,
    disabled: jobActive,
  });

  return (
    <div className="flex flex-col gap-3">
      <div
        {...getRootProps()}
        className={`rounded-2xl border-2 border-dashed px-4 py-8 text-center text-sm transition sm:py-10 ${
          jobActive ? "cursor-not-allowed opacity-60" : "cursor-pointer"
        } ${
          isDragActive
            ? "border-brand-400 bg-brand-50 dark:bg-brand-900/20"
            : "border-stone-200 bg-stone-50/70 text-stone-500 hover:border-brand-300 hover:bg-brand-50/40 dark:border-stone-700 dark:bg-stone-950/40 dark:text-stone-400 dark:hover:border-brand-700"
        }`}
      >
        <input {...getInputProps()} />
        <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-white text-brand-600 shadow-sm dark:bg-stone-800 dark:text-brand-400">
          <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            <path d="M12 16V4m0 0L8 8m4-4 4 4" />
            <path d="M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" />
          </svg>
        </div>
        <p className="font-bold text-stone-800 dark:text-stone-100">
          {jobActive ? "Ya hay una transcripción en curso" : "Suelta aquí tu archivo"}
        </p>
        {!jobActive && <p className="mt-1 text-xs">o haz clic para seleccionarlo · audio o vídeo</p>}
      </div>
      {error && <p role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-950/30 dark:text-red-400">{error}</p>}
    </div>
  );
}
