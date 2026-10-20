import { useEffect, useState } from "react";

import { del, getJson } from "../api/client";
import type { HistoryItem, TranscriptResult } from "../api/types";
import { useJobContext } from "../context/JobContext";
import { useHistory } from "../hooks/useHistory";
import { Icon } from "./Icon";

function savedDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Guardado"
    : new Intl.DateTimeFormat("es", { day: "numeric", month: "short" }).format(
        date,
      );
}

export function HistoryList() {
  const [query, setQuery] = useState("");
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { entries, refresh, error } = useHistory(query);
  const { state, dispatch } = useJobContext();
  const jobActive = Boolean(
    state.status &&
    !["completed", "failed", "cancelled"].includes(state.status),
  );

  const open = async (id: string) => {
    setBusy(true);
    setActionError(null);
    try {
      const result = await getJson<TranscriptResult>(`/api/jobs/${id}/result`);
      dispatch({ type: "START_JOB", jobId: id });
      dispatch({ type: "SET_RESULT", result });
      requestAnimationFrame(() =>
        document
          .getElementById("transcript")
          ?.scrollIntoView({ behavior: "smooth", block: "start" }),
      );
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : "No se pudo abrir la transcripción",
      );
    } finally {
      setBusy(false);
    }
  };

  const remove = async (entry: HistoryItem) => {
    if (
      !window.confirm(
        `¿Eliminar «${entry.title}» del historial?${deleteFiles ? " También se borrarán sus archivos guardados." : " Se conservarán los archivos guardados."}`,
      )
    )
      return;
    setBusy(true);
    setActionError(null);
    try {
      await del(`/api/history/${entry.id}?delete_files=${deleteFiles}`);
      if (state.jobId === entry.id) dispatch({ type: "RESET" });
      refresh();
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : "No se pudo eliminar la transcripción",
      );
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (state.status === "completed") refresh();
  }, [state.status, refresh]);

  return (
    <section className="panel library-panel" aria-labelledby="library-title">
      <div className="library-heading">
        <div>
          <Icon name="library" size={19} />
          <h2 id="library-title">Tu biblioteca</h2>
        </div>
        <span
          className="count-badge"
          aria-label={`${entries.length} resultados`}
        >
          {entries.length}
        </span>
      </div>
      <div className="search-field">
        <Icon name="search" size={15} />
        <input
          type="search"
          aria-label="Buscar en el historial"
          placeholder="Busca entre tus ideas..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <details className="library-options">
        <summary>Opciones del historial</summary>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={deleteFiles}
            onChange={(event) => setDeleteFiles(event.target.checked)}
          />
          Al eliminar, borrar también los archivos guardados
        </label>
      </details>
      {(actionError || error) && (
        <div className="message error" role="alert">
          {actionError || error}
          {error && (
            <button type="button" className="text-button" onClick={refresh}>
              Reintentar <Icon name="arrow" size={12} />
            </button>
          )}
        </div>
      )}
      {!entries.length && !error && (
        <div className="library-empty">
          <div className="empty-library-icon" aria-hidden="true">
            <Icon name={query ? "search" : "file"} size={27} />
          </div>
          <h3>
            {query
              ? "No se encontraron transcripciones."
              : "Tus ideas, en un solo lugar."}
          </h3>
          <p>
            {query
              ? "Prueba con otro título, enlace o palabra del texto."
              : "Todavía no hay transcripciones guardadas. La primera aparecerá aquí."}
          </p>
        </div>
      )}
      {entries.length > 0 && (
        <ul className="library-list">
          {entries.map((entry) => (
            <li key={entry.id} className="library-item">
              <div className="library-item-head">
                <span className="library-file-icon">
                  <Icon name="file" size={17} />
                </span>
                <div className="library-item-main">
                  <h3 title={entry.title}>{entry.title}</h3>
                  <p className="library-item-meta">
                    {savedDate(entry.created_at)} · {entry.word_count} palabras
                  </p>
                </div>
              </div>
              <p className="library-preview">{entry.text || entry.source}</p>
              <div className="library-item-actions">
                <button
                  type="button"
                  disabled={busy || jobActive}
                  onClick={() => open(entry.id)}
                  className="text-button"
                >
                  Abrir <Icon name="arrowUp" size={13} />
                </button>
                <button
                  type="button"
                  disabled={busy || jobActive}
                  onClick={() => remove(entry)}
                  className="text-button delete-button"
                >
                  <Icon name="trash" size={12} />
                  Eliminar
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
