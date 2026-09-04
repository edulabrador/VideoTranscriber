import { useEffect } from "react";

import { useJobContext } from "../context/JobContext";
import { useHistory } from "../hooks/useHistory";

export function HistoryList() {
  const { entries, refresh } = useHistory();
  const { state } = useJobContext();

  useEffect(() => {
    if (state.status === "completed") refresh();
  }, [state.status, refresh]);

  if (entries.length === 0) return null;

  return (
    <section className="flex flex-col gap-3 pt-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold text-stone-800 dark:text-stone-100">Transcripciones recientes</h2>
        <span className="text-xs text-stone-400">{entries.length}</span>
      </div>
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
            <span className="ml-3 shrink-0 rounded-full bg-stone-100 px-2.5 py-1 text-xs text-stone-500 dark:bg-stone-800 dark:text-stone-400">{entry.word_count} palabras</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
