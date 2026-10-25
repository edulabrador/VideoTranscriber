import { useState } from "react";

import type { TranscriptResult } from "../api/types";
import { copyableText, speakers } from "../lib/transcript";
import { timestampLink } from "../lib/videoUrls";
import { CopyButton } from "./CopyButton";
import { ExportMenu } from "./ExportMenu";
import { Icon } from "./Icon";

const PROFILE_LABELS = {
  fast: "Rápido",
  balanced: "Equilibrado",
  precise: "Preciso",
};

const TIMING_LABELS: Record<string, string> = {
  download: "Descarga",
  audio_preparation: "Preparación del archivo",
  queue: "Espera en cola",
  model_loading: "Carga del modelo",
  audio_analysis: "Análisis del audio",
  transcription: "Transcripción",
  diarization: "Identificación de hablantes",
  processing_total: "Total de procesamiento",
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
  const speakerNames = speakers(result);
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
        {speakerNames.length > 0 && (
          <span>
            {speakerNames.length === 1
              ? "1 hablante"
              : `${speakerNames.length} hablantes`}
          </span>
        )}
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
          result.segments.map((segment, index) => {
            const link = timestampLink(result.source, segment.start);
            const newSpeaker =
              segment.speaker &&
              segment.speaker !== result.segments[index - 1]?.speaker;
            return (
              <p
                key={index}
                className={newSpeaker ? "speaker-turn" : undefined}
              >
                {newSpeaker && (
                  <span
                    className={`speaker-label speaker-${speakerNames.indexOf(segment.speaker ?? "") % 6}`}
                  >
                    {segment.speaker}
                  </span>
                )}
                {showTimestamps &&
                  (link ? (
                    <a
                      className="timestamp"
                      href={link}
                      target="_blank"
                      rel="noreferrer"
                      title="Abrir el vídeo en este momento"
                    >
                      {formatTimestamp(segment.start)}
                    </a>
                  ) : (
                    <span className="timestamp">
                      {formatTimestamp(segment.start)}
                    </span>
                  ))}
                {segment.text}
              </p>
            );
          })
        ) : (
          <p>{result.text || "No se detectó voz en este archivo."}</p>
        )}
      </div>
      <div className="transcript-actions">
        <CopyButton text={copyableText(result)} />
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
          {result.requested_language
            ? ` · Idioma indicado: ${result.requested_language}`
            : ""}
          {result.task === "translate" ? " · Traducido al inglés" : ""}
          {result.word_timestamps ? " · Marcas por palabra" : ""}
          {result.diarize
            ? ` · Hablantes ${result.num_speakers ? `indicados: ${result.num_speakers}` : "detectados automáticamente"}`
            : ""}
          {result.initial_prompt
            ? ` · Vocabulario: ${result.initial_prompt}`
            : ""}
        </p>
        {Object.keys(result.timings ?? {}).length > 0 && (
          <p>
            {Object.entries(result.timings ?? {})
              .map(
                ([stage, seconds]) =>
                  `${TIMING_LABELS[stage] ?? stage}: ${seconds.toLocaleString("es", { maximumFractionDigits: 2 })} s`,
              )
              .join(" · ")}
          </p>
        )}
      </details>
    </section>
  );
}
