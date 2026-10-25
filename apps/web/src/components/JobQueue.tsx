import { useEffect, useRef, useState } from "react";

import { getJson } from "../api/client";
import { isTerminalStatus } from "../api/types";
import type { JobStatusResponse } from "../api/types";
import { useJobContext } from "../context/JobContext";

const POLL_INTERVAL_MS = 2000;
export const HISTORY_CHANGED_EVENT = "videotranscriber:history-changed";

const SHORT_LABELS: Record<JobStatusResponse["status"], string> = {
  queued: "En cola",
  downloading: "Descargando",
  extracting_audio: "Preparando",
  loading_model: "Cargando modelo",
  transcribing: "Transcribiendo",
  diarizing: "Hablantes",
  exporting: "Guardando",
  completed: "Lista",
  failed: "Error",
  cancelling: "Cancelando",
  cancelled: "Cancelada",
};

/** Every job of this server run, so several links can be queued at once. */
export function JobQueue({ revision }: { revision: number }) {
  const { state, dispatch } = useJobContext();
  const [jobs, setJobs] = useState<JobStatusResponse[]>([]);
  const finished = useRef<Set<string> | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const items = await getJson<JobStatusResponse[]>(
          "/api/jobs",
          controller.signal,
        );
        if (cancelled) return;
        setJobs(items);
        // Background jobs finish off screen; tell the library to reload.
        const done = new Set(
          items
            .filter((job) => isTerminalStatus(job.status))
            .map((job) => job.id),
        );
        if (
          finished.current &&
          [...done].some((id) => !finished.current?.has(id))
        ) {
          window.dispatchEvent(new Event(HISTORY_CHANGED_EVENT));
        }
        finished.current = done;
        if (items.some((job) => !isTerminalStatus(job.status))) {
          timer = setTimeout(poll, POLL_INTERVAL_MS);
        }
      } catch {
        if (!cancelled) timer = setTimeout(poll, POLL_INTERVAL_MS * 3);
      }
    };
    poll();
    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [revision, state.status]);

  if (jobs.length < 2) return null;
  const pending = jobs.filter((job) => !isTerminalStatus(job.status)).length;

  return (
    <section className="panel queue-panel" aria-labelledby="queue-title">
      <div className="queue-heading">
        <h2 id="queue-title">Cola de trabajos</h2>
        <span className="count-badge">{pending} pendientes</span>
      </div>
      <ul className="queue-list">
        {jobs.map((job) => (
          <li key={job.id}>
            <button
              type="button"
              className={`queue-item ${state.jobId === job.id ? "selected" : ""}`}
              aria-current={state.jobId === job.id ? "true" : undefined}
              onClick={() => dispatch({ type: "START_JOB", jobId: job.id })}
              title={job.stage_message}
            >
              <span className="queue-source">{job.source}</span>
              <span className={`queue-status status-${job.status}`}>
                {SHORT_LABELS[job.status]}
                {!isTerminalStatus(job.status) && job.progress_percent > 1
                  ? ` · ${job.progress_percent} %`
                  : ""}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
