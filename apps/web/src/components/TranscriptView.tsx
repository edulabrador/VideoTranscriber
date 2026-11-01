import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { downloadFileUrl, patchJson } from "../api/client";
import type { TranscriptResult, TranscriptSegment } from "../api/types";
import { useJobContext } from "../context/JobContext";
import {
  copyableText,
  highlightParts,
  mergedSpeakerNames,
  segmentAt,
  speakerNameProblem,
  speakers,
  transcriptEdits,
} from "../lib/transcript";
import { youtubeTimestampLink, youtubeVideoId } from "../lib/videoUrls";
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

interface SegmentRowProps {
  segment: TranscriptSegment;
  index: number;
  label: string | null;
  speakerClass: number;
  playing: boolean;
  currentMatch: boolean;
  showTimestamps: boolean;
  canSeek: boolean;
  videoId: string | null;
  editing: boolean;
  draft: string | undefined;
  query: string;
  onSeek: (seconds: number) => void;
  onDraft: (index: number, text: string) => void;
}

/**
 * One segment. Memoised: while the audio plays, the "playing" highlight changes
 * several times a second and only the two affected rows should re-render, not the
 * whole transcript.
 */
const SegmentRow = memo(function SegmentRow({
  segment,
  index,
  label,
  speakerClass,
  playing,
  currentMatch,
  showTimestamps,
  canSeek,
  videoId,
  editing,
  draft,
  query,
  onSeek,
  onDraft,
}: SegmentRowProps) {
  const time = formatTimestamp(segment.start);
  const link = !editing && !canSeek ? youtubeTimestampLink(videoId, segment.start) : null;
  const text = draft ?? segment.text;
  return (
    <div
      data-segment={index}
      className={[
        "segment",
        label ? "speaker-turn" : "",
        playing ? "playing" : "",
        currentMatch ? "current-match" : "",
      ].join(" ")}
    >
      {label && (
        <span className={`speaker-label speaker-${speakerClass % 6}`}>{label}</span>
      )}
      {showTimestamps &&
        (canSeek && !editing ? (
          <button
            type="button"
            className="timestamp"
            onClick={() => onSeek(segment.start)}
            title="Escuchar desde aquí"
          >
            {time}
          </button>
        ) : link ? (
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
          value={text}
          rows={Math.max(1, Math.ceil(text.length / 70))}
          onChange={(event) => onDraft(index, event.target.value)}
          aria-label={`Texto en ${time}`}
        />
      ) : (
        <span>
          <Highlighted text={segment.text} query={query} />
        </span>
      )}
    </div>
  );
});

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
  const speakerNames = useMemo(() => speakers(result), [result]);
  const videoId = useMemo(
    () => (result.source ? youtubeVideoId(result.source) : null),
    [result.source],
  );

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
    const problem = Object.values(names).map(speakerNameProblem).find(Boolean);
    if (problem) {
      setEditError(problem);
      return;
    }
    const changes = transcriptEdits(result, texts, names);
    if (!changes.segments.length && !Object.keys(changes.speakers).length) {
      setEditing(false);
      return;
    }
    const merged = mergedSpeakerNames(speakerNames, names);
    if (
      merged.length &&
      !window.confirm(
        `Varios hablantes se llamarán ${merged.map((name) => `«${name}»`).join(", ")}. ` +
          "Sus intervenciones se unirán y no se podrán volver a separar. ¿Guardar igualmente?",
      )
    ) {
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

  const seek = useCallback((seconds: number) => {
    if (!audio.current) return;
    audio.current.currentTime = seconds;
    void audio.current.play().catch(() => undefined);
  }, []);

  const updateDraft = useCallback((index: number, text: string) => {
    setTexts((current) => ({ ...current, [index]: text }));
  }, []);

  const currentMatch = matches.length ? matches[matchCursor % matches.length] : -1;

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
            const newSpeaker =
              Boolean(segment.speaker) &&
              segment.speaker !== result.segments[index - 1]?.speaker;
            const label =
              newSpeaker && segment.speaker
                ? editing
                  ? names[segment.speaker] || segment.speaker
                  : segment.speaker
                : null;
            return (
              <SegmentRow
                key={index}
                segment={segment}
                index={index}
                label={label}
                speakerClass={speakerNames.indexOf(segment.speaker ?? "")}
                playing={index === playing}
                currentMatch={index === currentMatch}
                showTimestamps={showTimestamps}
                canSeek={Boolean(result.has_audio)}
                videoId={videoId}
                editing={editing}
                draft={editing ? texts[index] : undefined}
                query={editing ? "" : query}
                onSeek={seek}
                onDraft={updateDraft}
              />
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
          outdated={Boolean(result.summary_outdated)}
          onSummary={(markdown) =>
            dispatch({
              type: "SET_RESULT",
              result: { ...result, summary: markdown, summary_outdated: false },
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
