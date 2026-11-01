import { useEffect, useRef, useState } from "react";

import { ApiError, del, getJson, postJson } from "../api/client";
import type { SummaryStatus, SummaryTask } from "../api/types";
import { Icon } from "./Icon";
import { MarkdownText } from "./MarkdownText";

const POLL_INTERVAL_MS = 1500;

/**
 * Local summary with Ollama. Hidden unless Ollama runs or a summary already exists.
 *
 * The server summarises in the background (it can take many minutes on a CPU), so
 * the panel starts the work and then follows its progress.
 */
export function SummaryPanel({
  jobId,
  summary,
  outdated,
  onSummary,
}: {
  jobId: string;
  summary: string | null | undefined;
  outdated: boolean;
  onSummary: (markdown: string) => void;
}) {
  const [status, setStatus] = useState<SummaryStatus | null>(null);
  const [task, setTask] = useState<SummaryTask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const running = task?.state === "running";
  // The parent passes a new callback on every render (several times a second while
  // the audio plays); keeping it in a ref stops that from resetting the poll timer.
  const onSummaryRef = useRef(onSummary);
  useEffect(() => {
    onSummaryRef.current = onSummary;
  });

  useEffect(() => {
    const controller = new AbortController();
    getJson<SummaryStatus>("/api/summary/status", controller.signal)
      .then(setStatus)
      .catch(() => setStatus({ available: false, model: null }));
    return () => controller.abort();
  }, []);

  // Pick up a summary that is still running, for example after reloading the page.
  useEffect(() => {
    const controller = new AbortController();
    setTask(null);
    setError(null);
    getJson<SummaryTask>(`/api/jobs/${jobId}/summary`, controller.signal)
      .then((current) => {
        if (current.state === "running") setTask(current);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [jobId]);

  useEffect(() => {
    if (!running) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      getJson<SummaryTask>(`/api/jobs/${jobId}/summary`, controller.signal)
        .then((current) => {
          setTask(current);
          if (current.state === "done" && current.markdown) {
            onSummaryRef.current(current.markdown);
          }
          if (current.state === "failed") {
            setError(current.error?.message ?? "No se pudo generar el resumen");
          }
        })
        .catch((err) => {
          // A lost connection is retried on the next tick; anything else stops here.
          if (err instanceof ApiError && err.code === "aborted") return;
          setTask((current) => (current ? { ...current } : current));
        });
    }, POLL_INTERVAL_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [running, task, jobId]);

  if (!summary && !status?.available && !running) return null;

  const generate = async () => {
    setError(null);
    try {
      setTask(await postJson<SummaryTask>(`/api/jobs/${jobId}/summary`, {}));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo generar el resumen");
    }
  };

  const cancel = async () => {
    try {
      await del(`/api/jobs/${jobId}/summary`);
      setTask((current) =>
        current ? { ...current, message: "Cancelando el resumen..." } : current,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cancelar el resumen");
    }
  };

  return (
    <div className="summary-panel">
      <div className="summary-heading">
        <span>
          <Icon name="sparkle" size={14} /> RESUMEN LOCAL
        </span>
        {running ? (
          <button type="button" className="secondary-button" onClick={cancel}>
            <Icon name="close" size={12} />
            Cancelar resumen
          </button>
        ) : (
          status?.available && (
            <button
              type="button"
              className="secondary-button"
              onClick={generate}
              title={`Se genera en tu ordenador con ${status.model}`}
            >
              {summary ? "Volver a resumir" : `Resumir con ${status.model}`}
            </button>
          )
        )}
      </div>
      {running && (
        <p className="message" role="status" aria-live="polite">
          {task?.message || "Resumiendo... puede tardar unos minutos"}
        </p>
      )}
      {task?.state === "cancelled" && (
        <p className="message" role="status">
          Resumen cancelado.
        </p>
      )}
      {error && (
        <p role="alert" className="message error">
          {error}
        </p>
      )}
      {summary && outdated && !running && (
        <p className="message warning" role="status">
          Corregiste la transcripción después de crear este resumen. Vuelve a
          resumir para actualizarlo.
        </p>
      )}
      {summary && (
        <div className="summary-text">
          <MarkdownText source={summary} />
        </div>
      )}
    </div>
  );
}
