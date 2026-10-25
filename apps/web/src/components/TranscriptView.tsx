import { useEffect, useMemo, useRef, useState } from "react";

import { downloadFileUrl, patchJson } from "../api/client";
import type { TranscriptResult } from "../api/types";
import { useJobContext } from "../context/JobContext";
import {
  copyableText,
  highlightParts,
  segmentAt,
  speakers,
  transcriptEdits,
} from "../lib/transcript";
import { timestampLink } from "../lib/videoUrls";
import { CopyButton } from "./CopyButton";
import { ExportMenu } from "./ExportMenu";
import { Icon } from "./Icon";
import { HISTORY_CHANGED_EVENT } from "./JobQueue";
import { SummaryPanel } from "./SummaryPanel";

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
  audio_copy: "Copia del audio",
  processing_total: "Total de procesamiento",
};

function formatTimestamp(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function Highlighted({ text, query }: { text: string; query: string }) {
  return (
    <>
      {highlightParts(text, query).map((part, index) =>
        part.match ? <mark key={index}>{part.text}</mark> : part.text,
      )}
    </>
  );
}

export function TranscriptView({
  jobId,
  result,
}: {
  jobId: string;
  result: TranscriptResult;
}) {
  const { dispatch } = useJobContext();
  const [showTimestamps, setShowTimestamps] = useState(true);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState(false);
  const [texts, setTexts] = useState<Record<number, string>>({});
  const [names, setNames] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(-1);
  const audio = useRef<HTMLAudioElement>(null);
  const textBox = useRef<HTMLDivElement>(null);
  const speakerNames = speakers(result);

  const matches = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("es");
    if (!needle) return [];
    return result.segments
      .map((segment, index) =>
        segment.text.toLocaleLowerCase("es").includes(needle) ? index : -1,
      )
      .filter((index) => index !== -1);
  }, [query, result.segments]);
  const [matchCursor, setMatchCursor] = useState(0);

  useEffect(() => setMatchCursor(0), [query]);
  useEffect(() => {
    if (!matches.length) return;
    textBox.current
      ?.querySelector(
        `[data-segment="${matches[matchCursor % matches.length]}"]`,
      )
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [matches, matchCursor]);

  // Leaving edit mode or opening another transcript discards drafts.
  useEffect(() => {
    setEditing(false);
    setPlaying(-1);
  }, [jobId]);

  useEffect(() => {
    if (playing < 0 || audio.current?.paused) return;
    textBox.current
      ?.querySelector(`[data-segment="${playing}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [playing]);

  const startEditing = () => {
    setTexts(
      Object.fromEntries(
        result.segments.map((segment, index) => [index, segment.text]),
      ),
    );
    setNames(Object.fromEntries(speakerNames.map((name) => [name, name])));
    setEditError(null);
    setEditing(true);
  };

  const save = async () => {
    const changes = transcriptEdits(result, texts, names);
    if (!changes.segments.length && !Object.keys(changes.speakers).length) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setEditError(null);
    try {
      const updated = await patchJson<TranscriptResult>(
        `/api/jobs/${jobId}/transcript`,
        changes,
      );
      dispatch({ type: "SET_RESULT", result: updated });
      // The library preview and word count come from the files just rewritten.
      window.dispatchEvent(new Event(HISTORY_CHANGED_EVENT));
      setEditing(false);
    } catch (err) {
      setEditError(
        err instanceof Error
          ? err.message
          : "No se pudieron guardar los cambios",
      );
    } finally {
      setSaving(false);
    }
  };

  const seek = (seconds: number) => {
    if (!audio.current) return;
    audio.current.currentTime = seconds;
    void audio.current.play().catch(() => undefined);
  };

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
          {result.edited ? "Corregida" : "Lista para usar"}
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
      {result.has_audio && !editing && (
        <audio
          ref={audio}
          className="transcript-audio"
          controls
          preload="metadata"
          src={downloadFileUrl(`/api/jobs/${jobId}/audio`)}
          onTimeUpdate={(event) =>
            setPlaying(
              segmentAt(result.segments, event.currentTarget.currentTime),
            )
          }
          aria-label="Audio de la transcripción"
        />
      )}
      <div className="transcript-toolbar">
        {editing ? (
          <span>EDITANDO</span>
        ) : (
          <div className="transcript-search">
            <Icon name="search" size={14} />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && matches.length) {
                  event.preventDefault();
                  setMatchCursor(
                    (value) =>
                      value + (event.shiftKey ? matches.length - 1 : 1),
                  );
                }
              }}
              placeholder="Buscar en el texto..."
              aria-label="Buscar en la transcripción"
            />
            {query.trim() && (
              <span className="match-count" aria-live="polite">
                {matches.length
                  ? `${(matchCursor % matches.length) + 1} de ${matches.length}`
                  : "Sin resultados"}
              </span>
            )}
          </div>
        )}
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={showTimestamps}
            onChange={(event) => setShowTimestamps(event.target.checked)}
          />
          Mostrar tiempos
        </label>
      </div>
      {editing && speakerNames.length > 0 && (
        <div className="speaker-names">
          <span className="field-label">Nombres de los hablantes</span>
          {speakerNames.map((name, index) => (
            <label
              key={name}
              className={`speaker-name-field speaker-${index % 6}`}
            >
              <span className="speaker-label">{name}</span>
              <input
                className="text-field"
                value={names[name] ?? name}
                maxLength={60}
                onChange={(event) =>
                  setNames({ ...names, [name]: event.target.value })
                }
                aria-label={`Nombre para ${name}`}
              />
            </label>
          ))}
        </div>
      )}
      <div className="transcript-text" ref={textBox}>
        {result.segments.length ? (
          result.segments.map((segment, index) => {
            const link = timestampLink(result.source, segment.start);
            const newSpeaker =
              segment.speaker &&
              segment.speaker !== result.segments[index - 1]?.speaker;
            const label = segment.speaker
              ? editing
                ? names[segment.speaker] || segment.speaker
                : segment.speaker
              : null;
            const time = formatTimestamp(segment.start);
            return (
              <div
                key={index}
                data-segment={index}
                className={[
                  "segment",
                  newSpeaker ? "speaker-turn" : "",
                  index === playing ? "playing" : "",
                  matches[matchCursor % matches.length] === index
                    ? "current-match"
                    : "",
                ].join(" ")}
              >
                {newSpeaker && (
                  <span
                    className={`speaker-label speaker-${speakerNames.indexOf(segment.speaker ?? "") % 6}`}
                  >
                    {label}
                  </span>
                )}
                {showTimestamps &&
                  (result.has_audio && !editing ? (
                    <button
                      type="button"
                      className="timestamp"
                      onClick={() => seek(segment.start)}
                      title="Escuchar desde aquí"
                    >
                      {time}
                    </button>
                  ) : link && !editing ? (
                    <a
                      className="timestamp"
                      href={link}
                      target="_blank"
                      rel="noreferrer"
                      title="Abrir el vídeo en este momento"
                    >
                      {time}
                    </a>
                  ) : (
                    <span className="timestamp">{time}</span>
                  ))}
                {editing ? (
                  <textarea
                    className="segment-editor"
                    value={texts[index] ?? segment.text}
                    rows={Math.max(
                      1,
                      Math.ceil((texts[index] ?? segment.text).length / 70),
                    )}
                    onChange={(event) =>
                      setTexts({ ...texts, [index]: event.target.value })
                    }
                    aria-label={`Texto en ${time}`}
                  />
                ) : (
                  <span>
                    <Highlighted text={segment.text} query={query} />
                  </span>
                )}
              </div>
            );
          })
        ) : (
          <p>{result.text || "No se detectó voz en este archivo."}</p>
        )}
      </div>
      {editError && (
        <p role="alert" className="message error">
          {editError}
        </p>
      )}
      <div className="transcript-actions">
        {editing ? (
          <div className="edit-actions">
            <button
              type="button"
              className="primary-button"
              onClick={save}
              disabled={saving}
            >
              <span>{saving ? "Guardando..." : "Guardar cambios"}</span>
              <Icon name="check" size={16} />
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => setEditing(false)}
              disabled={saving}
            >
              Cancelar
            </button>
          </div>
        ) : (
          <>
            <div className="edit-actions">
              <CopyButton text={copyableText(result)} />
              {result.segments.length > 0 && (
                <button
                  type="button"
                  className="secondary-button"
                  onClick={startEditing}
                >
                  <Icon name="edit" size={14} />
                  {speakerNames.length
                    ? "Corregir texto y nombres"
                    : "Corregir texto"}
                </button>
              )}
            </div>
            <ExportMenu jobId={jobId} hasSummary={Boolean(result.summary)} />
          </>
        )}
      </div>
      {!editing && (
        <SummaryPanel
          jobId={jobId}
          summary={result.summary}
          onSummary={(markdown) =>
            dispatch({
              type: "SET_RESULT",
              result: { ...result, summary: markdown },
            })
          }
        />
      )}
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
          {result.edited ? " · Corregida a mano" : ""}
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
