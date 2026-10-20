import { useEffect, useState } from "react";

import { del, getJson } from "../api/client";
import type { HistoryItem, TranscriptResult } from "../api/types";
import { useJobContext } from "../context/JobContext";
import { useHistory } from "../hooks/useHistory";

export function HistoryList() {
  const [query, setQuery] = useState("");
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { entries, refresh, error } = useHistory(query);
  const { state, dispatch } = useJobContext();
  const jobActive = Boolean(state.status && !["completed", "failed", "cancelled"].includes(state.status));

  const open = async (id: string) => {
    setBusy(true);
    setActionError(null);
    try {
      const result = await getJson<TranscriptResult>(`/api/jobs/${id}/result`);
      dispatch({ type: "START_JOB", jobId: id });
      dispatch({ type: "SET_RESULT", result });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "No se pudo abrir la transcripción");
    } finally { setBusy(false); }
  };

  const remove = async (entry: HistoryItem) => {
    if (!window.confirm(`¿Eliminar «${entry.title}» del historial?${deleteFiles ? " También se borrarán sus archivos guardados." : " Se conservarán los archivos guardados."}`)) return;
    setBusy(true);
    setActionError(null);
    try {
      await del(`/api/history/${entry.id}?delete_files=${deleteFiles}`);
      if (state.jobId === entry.id) dispatch({ type: "RESET" });
      refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "No se pudo eliminar la transcripción");
    } finally { setBusy(false); }
  };

  useEffect(() => {
    if (state.status === "completed") refresh();
  }, [state.status, refresh]);

  return (
    <section className="flex flex-col gap-3 pt-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold text-stone-800 dark:text-stone-100">Transcripciones recientes</h2>
        <span className="text-xs text-stone-400">{entries.length}</span>
      </div>
      <input type="search" aria-label="Buscar en el historial" placeholder="Buscar por título, enlace o texto..." value={query} onChange={(event) => setQuery(event.target.value)} className="rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm dark:border-stone-700 dark:bg-stone-900" />
      <label className="flex items-center gap-2 text-xs text-stone-500">
        <input type="checkbox" checked={deleteFiles} onChange={(event) => setDeleteFiles(event.target.checked)} />
        Al eliminar, borrar también los archivos guardados
      </label>
      {(actionError || error) && <p role="alert" className="text-sm text-red-600">{actionError || error}</p>}
      {!entries.length && <p className="text-sm text-stone-500">{query ? "No se encontraron transcripciones." : "Todavía no hay transcripciones guardadas."}</p>}
      <ul className="flex flex-col gap-2">
        {entries.map((entry) => (
          <li
            key={entry.id}
            className="group flex items-center justify-between rounded-2xl border border-stone-200/80 bg-white/80 px-4 py-3.5 text-sm shadow-sm backdrop-blur transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-soft dark:border-stone-800 dark:bg-stone-900/75 dark:hover:border-brand-800"
          >
            <div className="flex min-w-0 items-center gap-3">
              <div className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-950/40 dark:text-brand-400">
                <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                  <path d="M5 5h14v14H5z" /><path d="M8 9h8M8 12h8M8 15h5" />
                </svg>
              </div>
              <div className="min-w-0">
                <p className="truncate font-semibold text-stone-700 dark:text-stone-200">{entry.title}</p>
                {entry.text ? (
                  <>
                    <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-stone-500 dark:text-stone-400">
                      {entry.text}
                    </p>
                    <details className="mt-2 text-xs text-brand-700 dark:text-brand-400">
                      <summary className="cursor-pointer font-medium">Leer transcripción completa</summary>
                      <p className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap pr-2 leading-relaxed text-stone-600 dark:text-stone-300">
                        {entry.text}
                      </p>
                    </details>
                  </>
                ) : (
                  <p className="truncate text-xs text-stone-400">{entry.source}</p>
                )}
              </div>
            </div>
            <div className="ml-3 flex shrink-0 flex-col gap-2 text-xs">
              <span className="text-stone-500">{entry.word_count} palabras</span>
              <button type="button" disabled={busy || jobActive} onClick={() => open(entry.id)} className="font-semibold text-brand-600 disabled:opacity-50">Abrir</button>
              <button type="button" disabled={busy || jobActive} onClick={() => remove(entry)} className="text-red-600 disabled:opacity-50">Eliminar</button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
