import { useJobContext } from "../context/JobContext";
import { CancelButton } from "./CancelButton";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

export function ProgressIndicator() {
  const { state } = useJobContext();
  if (!state.jobId || !state.status) return null;

  const isTerminal = TERMINAL_STATUSES.has(state.status);
  const isError = state.status === "failed";
  const isTranscribing = state.status === "transcribing";
  const isIndeterminate = isTranscribing && !state.stageMessage.includes("%");

  return (
    <div className={`flex flex-col gap-3 rounded-2xl border bg-white/85 p-5 shadow-soft backdrop-blur dark:bg-stone-900/85 ${isError ? "border-red-200 dark:border-red-900" : "border-stone-200/80 dark:border-stone-800"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${isError ? "bg-red-500" : "animate-pulse bg-brand-500"}`} />
          <div>
            <p className={`text-sm font-semibold ${isError ? "text-red-600 dark:text-red-400" : "text-stone-700 dark:text-stone-200"}`}>
              {isError && state.error ? state.error.message : state.stageMessage}
            </p>
            {!isTerminal && (
              <p className="mt-1 text-xs text-stone-400">
                {isTranscribing
                  ? isIndeterminate
                    ? "Calculando un progreso real..."
                    : "Progreso basado en los segundos de audio ya procesados."
                  : `${Math.round(state.progressPercent)} % completado`}
              </p>
            )}
          </div>
        </div>
        {!isTerminal && <CancelButton />}
      </div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-stone-100 dark:bg-stone-800"
        role="progressbar"
        aria-label="Progreso de la transcripción"
        aria-valuenow={isIndeterminate ? undefined : Math.round(state.progressPercent)}
      >
        <div
          className={`h-full rounded-full ${
            isIndeterminate ? "w-1/3 animate-loading" : "transition-all duration-500"
          } ${
            isError ? "bg-red-400" : "bg-gradient-to-r from-brand-700 via-brand-500 to-cyan-400"
          }`}
          style={isIndeterminate ? undefined : { width: `${state.progressPercent}%` }}
        />
      </div>
    </div>
  );
}
