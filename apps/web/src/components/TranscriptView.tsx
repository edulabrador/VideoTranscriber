import { useState } from "react";

import type { TranscriptResult } from "../api/types";
import { CopyButton } from "./CopyButton";
import { ExportMenu } from "./ExportMenu";
import { Icon } from "./Icon";

const PROFILE_LABELS = {
  fast: "Rápido",
  balanced: "Equilibrado",
  precise: "Preciso",
};

function formatTimestamp(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function TranscriptView({
  jobId,
  result,
}: {
  jobId: string;
  result: TranscriptResult;
}) {
  const [showTimestamps, setShowTimestamps] = useState(true);
  return (
    <section
      className="panel transcript-panel"
      id="transcript"
      aria-labelledby="transcript-title"
    >
      <div className="transcript-header">
        <div>
          <p className="eyebrow">LO QUE MERECE QUEDARSE</p>
          <h2 id="transcript-title">Tu transcripción</h2>
        </div>
        <span className="ready-label">
          <Icon name="check" size={12} />
          Lista para usar
        </span>
      </div>
      <div className="transcript-metadata">
        <span>
          <Icon name="clock" size={13} />
          {formatTimestamp(result.duration)}
        </span>
        <span>{result.word_count} palabras</span>
        <span>Idioma: {result.language.toUpperCase()}</span>
        {result.audio_selection && (
          <span>
            {result.audio_selection === "original"
              ? `Audio: ${result.audio_language ?? "?"} (original)`
              : "Audio: pista por defecto, no identificada"}
          </span>
        )}
      </div>
      <div className="transcript-toolbar">
        <span>TEXTO COMPLETO</span>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={showTimestamps}
            onChange={(event) => setShowTimestamps(event.target.checked)}
          />
          Mostrar tiempos
        </label>
      </div>
      <div className="transcript-text">
        {result.segments.length ? (
          result.segments.map((segment, index) => (
            <p key={index}>
              {showTimestamps && (
                <span className="timestamp">
                  {formatTimestamp(segment.start)}
                </span>
              )}
              {segment.text}
            </p>
          ))
        ) : (
          <p>{result.text || "No se detectó voz en este archivo."}</p>
        )}
      </div>
      <div className="transcript-actions">
        <CopyButton text={result.text} />
        <ExportMenu jobId={jobId} />
      </div>
      <details className="transcript-tech">
        <summary>Detalles de transcripción</summary>
        <p>
          Perfil {PROFILE_LABELS[result.profile]} · Modelo {result.model_size} ·{" "}
          {result.device} · Lote {result.batch_size} · Idioma detectado con{" "}
          {Math.round(result.language_probability * 100)} % de confianza
          {result.audio_format_id
            ? ` · Formato de audio ${result.audio_format_id}`
            : ""}
        </p>
      </details>
    </section>
  );
}
