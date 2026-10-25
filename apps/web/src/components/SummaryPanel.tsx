import { useEffect, useState } from "react";

import { ApiError, getJson, postLong } from "../api/client";
import type { SummaryStatus } from "../api/types";
import { Icon } from "./Icon";
import { MarkdownText } from "./MarkdownText";

/** Local summary with Ollama. Hidden unless Ollama runs or a summary already exists. */
export function SummaryPanel({
  jobId,
  summary,
  onSummary,
}: {
  jobId: string;
  summary: string | null | undefined;
  onSummary: (markdown: string) => void;
}) {
  const [status, setStatus] = useState<SummaryStatus | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getJson<SummaryStatus>("/api/summary/status", controller.signal)
      .then(setStatus)
      .catch(() => setStatus({ available: false, model: null }));
    return () => controller.abort();
  }, []);

  if (!summary && !status?.available) return null;

  const generate = async () => {
    setWorking(true);
    setError(null);
    try {
      const { markdown } = await postLong<{ markdown: string }>(
        `/api/jobs/${jobId}/summary`,
      );
      onSummary(markdown);
    } catch (err) {
      setError(
        err instanceof ApiError || err instanceof Error
          ? err.message
          : "No se pudo generar el resumen",
      );
    } finally {
      setWorking(false);
    }
  };

  return (
    <div className="summary-panel">
      <div className="summary-heading">
        <span>
          <Icon name="sparkle" size={14} /> RESUMEN LOCAL
        </span>
        {status?.available && (
          <button
            type="button"
            className="secondary-button"
            onClick={generate}
            disabled={working}
            title={`Se genera en tu ordenador con ${status.model}`}
          >
            {working
              ? "Resumiendo... puede tardar unos minutos"
              : summary
                ? "Volver a resumir"
                : `Resumir con ${status.model}`}
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="message error">
          {error}
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
