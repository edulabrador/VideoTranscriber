import type { TranscriptionOptions } from "../api/types";

const LANGUAGES: [string, string][] = [
  ["", "Detectar automáticamente"],
  ["es", "Español"],
  ["en", "Inglés"],
  ["ca", "Catalán"],
  ["gl", "Gallego"],
  ["eu", "Euskera"],
  ["pt", "Portugués"],
  ["fr", "Francés"],
  ["it", "Italiano"],
  ["de", "Alemán"],
  ["nl", "Neerlandés"],
  ["ja", "Japonés"],
  ["zh", "Chino"],
  ["ko", "Coreano"],
  ["ru", "Ruso"],
  ["ar", "Árabe"],
];

export function AdvancedOptions({
  options,
  onChange,
}: {
  options: TranscriptionOptions;
  onChange: (options: TranscriptionOptions) => void;
}) {
  const update = (changes: Partial<TranscriptionOptions>) =>
    onChange({ ...options, ...changes });
  const changed =
    options.language !== null ||
    options.task !== "transcribe" ||
    Boolean(options.initial_prompt) ||
    options.word_timestamps;

  return (
    <details className="advanced-options">
      <summary>
        Opciones avanzadas{changed ? " (personalizadas)" : ""}
      </summary>
      <div className="advanced-grid">
        <label className="field-label">
          Idioma del audio
          <select
            value={options.language ?? ""}
            onChange={(event) => update({ language: event.target.value || null })}
          >
            {LANGUAGES.map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
          <span className="field-hint">
            Indicarlo evita errores de detección en clips cortos o con música.
          </span>
        </label>
        <label className="field-label">
          Vocabulario
          <input
            className="text-field"
            type="text"
            maxLength={500}
            value={options.initial_prompt ?? ""}
            onChange={(event) => update({ initial_prompt: event.target.value || null })}
            placeholder="Nombres propios, siglas, jerga..."
          />
          <span className="field-hint">
            Ayuda a escribir bien términos poco comunes.
          </span>
        </label>
      </div>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={options.task === "translate"}
          onChange={(event) =>
            update({ task: event.target.checked ? "translate" : "transcribe" })
          }
        />
        Traducir al inglés
      </label>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={options.word_timestamps}
          onChange={(event) => update({ word_timestamps: event.target.checked })}
        />
        Subtítulos más precisos (marcas por palabra, algo más lento)
      </label>
    </details>
  );
}
