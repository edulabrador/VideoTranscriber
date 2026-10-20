import { useEffect } from "react";

import { ApiError, getJson } from "../api/client";
import { useJobContext } from "../context/JobContext";
import { loadJobUpdate } from "../lib/jobPolling";

const POLL_INTERVAL_MS = 1500;
const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

export function useJobPolling() {
  const { state, dispatch } = useJobContext();
  const { jobId } = state;

  // Keyed only on jobId (not status): re-running this effect on every status
  // change would tear down the in-flight poll() closure right as a job hits
  // "completed", dropping the result fetch that happens later in the same
  // call. The poll loop below decides on its own when to stop.
  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;
    let failures = 0;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      try {
        const { job, result } = await loadJobUpdate(
          jobId, <T,>(path: string) => getJson<T>(path, controller.signal),
        );
        if (cancelled) return;
        failures = 0;
        dispatch({
          type: "UPDATE_STATUS",
          status: job.status,
          stageMessage: job.stage_message,
          progressPercent: job.progress_percent,
          error: job.error,
        });

        if (result) dispatch({ type: "SET_RESULT", result });

        if (!cancelled && !TERMINAL_STATUSES.has(job.status)) {
          timer = setTimeout(poll, POLL_INTERVAL_MS);
        }
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && error.status && error.status < 500) {
          const message = error.status === 404
            ? "El trabajo ya no está disponible. El servidor pudo reiniciarse. Puedes volver a transcribirlo."
            : error.message;
          dispatch({
            type: "UPDATE_STATUS", status: "failed", stageMessage: message,
            progressPercent: 0, error: { code: "job_unavailable", message },
          });
          return;
        }
        failures += 1;
        dispatch({
          type: "CONNECTION_ERROR",
          message: "Se perdió la conexión con el servidor local. Reintentando automáticamente... Comprueba que VideoTranscriber siga abierto.",
        });
        timer = setTimeout(poll, Math.min(15_000, POLL_INTERVAL_MS * 2 ** Math.min(failures, 4)));
      }
    };

    poll();
    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [jobId, dispatch]);
}
