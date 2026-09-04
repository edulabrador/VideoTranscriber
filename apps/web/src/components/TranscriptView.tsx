import { useState, type ReactNode } from "react";

import type { TranscriptResult } from "../api/types";
import { CopyButton } from "./CopyButton";
import { ExportMenu } from "./ExportMenu";

function formatTimestamp(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function TranscriptView({ jobId, result }: { jobId: string; result: TranscriptResult }) {
  const [showTimestamps, setShowTimestamps] = useState(true);

  return (
    <section className="flex flex-col gap-4 rounded-[1.75rem] border border-stone-200/80 bg-white/90 p-4 shadow-soft backdrop-blur dark:border-stone-800 dark:bg-stone-900/90 sm:p-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-brand-600 dark:text-brand-400">Resultado</p>
          <h2 className="mt-1 text-xl font-extrabold">Transcripción</h2>
        </div>
        <label className="flex items-center gap-2 text-xs font-medium text-stone-500 dark:text-stone-400">
          <input
            type="checkbox"
            checked={showTimestamps}
            onChange={(e) => setShowTimestamps(e.target.checked)}
            className="accent-brand-500"
          />
          Tiempos
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge>Idioma: {result.language.toUpperCase()} ({Math.round(result.language_probability * 100)} %)</Badge>
        <Badge>Duración: {formatTimestamp(result.duration)}</Badge>
        <Badge>{result.word_count} palabras</Badge>
        <Badge>Modelo: {result.model_size} · {result.device}</Badge>
      </div>

      <div className="max-h-96 space-y-2 overflow-y-auto rounded-2xl bg-stone-50 p-4 text-sm leading-7 text-stone-700 dark:bg-stone-950/55 dark:text-stone-200 sm:p-5">
        {result.segments.map((seg, i) => (
          <p key={i}>
            {showTimestamps && (
              <span className="mr-2 font-mono text-xs text-brand-500">[{formatTimestamp(seg.start)}]</span>
            )}
            {seg.text}
          </p>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <CopyButton text={result.text} />
        <ExportMenu jobId={jobId} />
      </div>
    </section>
  );
}

function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full bg-stone-100 px-2.5 py-1 font-medium text-stone-600 dark:bg-stone-800 dark:text-stone-300">
      {children}
    </span>
  );
}
