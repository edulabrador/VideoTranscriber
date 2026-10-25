import type { JobStatus } from "../api/types";
import { isTerminalStatus } from "../api/types";
import { useJobContext } from "../context/JobContext";
import { CancelButton } from "./CancelButton";
import { Icon } from "./Icon";

const LABELS: Record<JobStatus, string> = {
  queued: "Esperando tu turno",
  downloading: "Preparando tu audio",
  extracting_audio: "Preparando el archivo",
  loading_model: "Preparando el modelo",
  transcribing: "Dando forma al texto",
  diarizing: "Reconociendo las voces",
  exporting: "Últimos detalles",
  completed: "Tu texto está listo",
  failed: "No hemos podido terminar",
  cancelling: "Cancelando la transcripción",
  cancelled: "Transcripción cancelada",
};

export function ProgressIndicator() {
  const { state } = useJobContext();
  if (!state.jobId || !state.status) return null;
  const isTerminal = isTerminalStatus(state.status);
  const isError = state.status === "failed";
  const isIndeterminate =
    !isTerminal &&
    (state.status === "loading_model" ||
      state.status === "queued" ||
      (state.status === "downloading" && state.progressPercent <= 1) ||
      (state.status === "transcribing" && !state.stageMessage.includes("%")));
  const percent =
    state.status === "completed" ? 100 : Math.round(state.progressPercent);

  return (
    <section
      className={`panel progress-panel ${isError ? "error-state" : ""}`}
      aria-label="Estado de la transcripción"
    >
      {state.connectionMessage && (
        <p role="alert" className="message warning">
          {state.connectionMessage}
        </p>
      )}
      <div className="progress-head">
        <div className="progress-heading">
          <span className={`status-orb ${isTerminal ? "" : "working"}`}>
            {isTerminal && (
              <Icon
                name={state.status === "completed" ? "check" : "close"}
                size={15}
              />
            )}
          </span>
          <h2>{LABELS[state.status]}</h2>
        </div>
        {!isTerminal && <CancelButton />}
      </div>
      <p className="progress-detail" aria-live="polite">
        {isError && state.error ? state.error.message : state.stageMessage}
      </p>
      <div className="progress-meta">
        <span>
          {state.status === "completed"
            ? "Una idea más en tu biblioteca."
            : isTerminal
              ? "Puedes iniciar una nueva transcripción."
              : isIndeterminate
                ? "Preparando todo para empezar."
                : "Progreso de tu transcripción"}
        </span>
        <strong>{isIndeterminate ? "En curso" : `${percent} %`}</strong>
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-label="Progreso de la transcripción"
        aria-valuenow={isIndeterminate ? undefined : percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={`progress-fill ${isIndeterminate ? "indeterminate" : ""}`}
          style={isIndeterminate ? undefined : { width: `${percent}%` }}
        />
      </div>
    </section>
  );
}
