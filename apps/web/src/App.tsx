import { useState } from "react";

import { FileDropZone } from "./components/FileDropZone";
import { HistoryList } from "./components/HistoryList";
import { Icon } from "./components/Icon";
import { ProgressIndicator } from "./components/ProgressIndicator";
import { TranscriptView } from "./components/TranscriptView";
import { UrlInputForm } from "./components/UrlInputForm";
import { JobProvider, useJobContext } from "./context/JobContext";
import { useJobPolling } from "./hooks/useJobPolling";
import type { AudioQuality, TranscriptionProfile } from "./api/types";

type InputMode = "url" | "file";

function DarkModeToggle() {
  const [dark, setDark] = useState(() =>
    document.documentElement.classList.contains("dark"),
  );
  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {
      /* Optional preference. */
    }
  };
  return (
    <button
      type="button"
      onClick={toggle}
      className="icon-button theme-toggle"
      aria-label={dark ? "Activar tema claro" : "Activar tema oscuro"}
      title={dark ? "Activar tema claro" : "Activar tema oscuro"}
    >
      <Icon name={dark ? "sun" : "moon"} size={19} />
    </button>
  );
}

function TranscriberPanel() {
  const { state } = useJobContext();
  const [mode, setMode] = useState<InputMode>("url");
  const [profile, setProfile] = useState<TranscriptionProfile>(() => {
    const saved = localStorage.getItem("transcription-profile");
    return saved === "fast" || saved === "precise" ? saved : "balanced";
  });
  const [audioQuality, setAudioQuality] = useState<AudioQuality>(() => {
    const saved = localStorage.getItem("audio-quality");
    return saved === "compact" || saved === "best" ? saved : "balanced";
  });
  useJobPolling();

  const preferences = (
    <div className={`preferences-grid ${mode === "file" ? "single" : ""}`}>
      <label className="field-label">
        Perfil de transcripción
        <select
          value={profile}
          onChange={(event) => {
            const value = event.target.value as TranscriptionProfile;
            setProfile(value);
            localStorage.setItem("transcription-profile", value);
          }}
        >
          <option value="fast">Rápido</option>
          <option value="balanced">Equilibrado</option>
          <option value="precise">Preciso</option>
        </select>
        <span className="field-hint">
          {profile === "fast"
            ? "Menos espera, más agilidad."
            : profile === "precise"
              ? "Más detalle, algo más de tiempo."
              : "El punto justo entre calidad y tiempo."}
        </span>
      </label>
      {mode === "url" && (
        <label className="field-label">
          Calidad del audio
          <select
            value={audioQuality}
            onChange={(event) => {
              const value = event.target.value as AudioQuality;
              setAudioQuality(value);
              localStorage.setItem("audio-quality", value);
            }}
          >
            <option value="compact">Compacta</option>
            <option value="balanced">Equilibrada</option>
            <option value="best">Máxima</option>
          </select>
          <span className="field-hint">
            {audioQuality === "compact"
              ? "Un archivo más ligero."
              : audioQuality === "best"
                ? "La mejor fuente disponible."
                : "Buena calidad, descarga moderada."}
          </span>
        </label>
      )}
    </div>
  );

  return (
    <div className="studio-grid">
      <div className="studio-main">
        <section
          className="panel composer"
          id="studio"
          aria-labelledby="composer-title"
        >
          <div className="panel-heading">
            <div>
              <p className="eyebrow">DA EL PRIMER PASO</p>
              <h2 id="composer-title">¿Qué quieres transcribir?</h2>
            </div>
            <span className="section-number" aria-hidden="true">
              01
            </span>
          </div>
          <div
            className="source-tabs"
            role="tablist"
            aria-label="Origen del audio"
            onKeyDown={(event) => {
              if (
                !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
              )
                return;
              event.preventDefault();
              const next =
                event.key === "Home"
                  ? "url"
                  : event.key === "End"
                    ? "file"
                    : mode === "url"
                      ? "file"
                      : "url";
              setMode(next);
              document.getElementById(`source-${next}`)?.focus();
            }}
          >
            {(["url", "file"] as const).map((source) => (
              <button
                key={source}
                id={`source-${source}`}
                type="button"
                role="tab"
                aria-selected={mode === source}
                aria-controls="source-panel"
                tabIndex={mode === source ? 0 : -1}
                onClick={() => setMode(source)}
                className={mode === source ? "selected" : ""}
              >
                <Icon name={source === "url" ? "link" : "upload"} size={17} />
                {source === "url" ? "Pegar enlace" : "Subir archivo"}
              </button>
            ))}
          </div>
          <div
            id="source-panel"
            role="tabpanel"
            aria-labelledby={`source-${mode}`}
          >
            {mode === "url" ? (
              <UrlInputForm profile={profile} audioQuality={audioQuality}>
                {preferences}
              </UrlInputForm>
            ) : (
              <div className="file-source">
                {preferences}
                <FileDropZone profile={profile} />
              </div>
            )}
          </div>
          <div className="source-support">
            <span>Compatible con</span>
            <div aria-label="Plataformas compatibles">
              <span>YouTube</span>
              <span>Instagram</span>
              <span>TikTok</span>
              <span>X / Twitter</span>
            </div>
          </div>
        </section>
        <ProgressIndicator />
        {state.result && state.jobId ? (
          <TranscriptView jobId={state.jobId} result={state.result} />
        ) : (
          !state.jobId && (
            <section
              className="result-placeholder"
              aria-label="Espacio para el resultado"
            >
              <div className="placeholder-document" aria-hidden="true">
                <Icon name="file" size={24} />
                <i />
                <i />
                <i />
              </div>
              <div>
                <p className="eyebrow">DE ESCUCHAR A CREAR</p>
                <h3>El texto aparece aquí.</h3>
                <p>Transcribe, copia y llévatelo a donde lo necesites.</p>
                <div className="format-tags">
                  <span>TXT</span>
                  <span>SRT</span>
                  <span>JSON</span>
                </div>
              </div>
            </section>
          )
        )}
        <p className="workspace-note">
          <Icon name="shield" size={15} />
          Transcripción local. Los archivos temporales se eliminan al terminar.
        </p>
      </div>
      <aside
        className="library-column"
        id="library"
        aria-label="Biblioteca de transcripciones"
      >
        <HistoryList />
      </aside>
    </div>
  );
}

export default function App() {
  const [section, setSection] = useState("studio");
  return (
    <div className="app-shell">
      <a className="skip-link" href="#studio">
        Ir a transcribir
      </a>
      <aside className="sidebar" aria-label="Navegación principal">
        <a
          className="wordmark"
          href="#studio"
          onClick={() => setSection("studio")}
          aria-label="VideoTranscriber, inicio"
        >
          <span className="brand-symbol">
            <Icon name="wave" size={24} />
          </span>
          <span>
            Video<span className="wordmark-light">Transcriber</span>
            <small>ESTUDIO LOCAL</small>
          </span>
        </a>
        <div className="sidebar-navigation">
          <nav>
            <a
              href="#studio"
              className={`nav-item ${section === "studio" ? "active" : ""}`}
              aria-label="Nueva transcripción"
              aria-current={section === "studio" ? "location" : undefined}
              onClick={() => setSection("studio")}
            >
              <Icon name="plus" size={19} />
              <span>Nueva transcripción</span>
            </a>
            <a
              href="#library"
              className={`nav-item ${section === "library" ? "active" : ""}`}
              aria-label="Tu biblioteca"
              aria-current={section === "library" ? "location" : undefined}
              onClick={() => setSection("library")}
            >
              <Icon name="library" size={19} />
              <span>Tu biblioteca</span>
            </a>
          </nav>
        </div>
      </aside>
      <main className="workspace">
        <div className="topbar">
          <p>
            <strong>Estudio de transcripción</strong>
          </p>
          <div className="topbar-actions">
            <span className="local-label">
              <Icon name="shield" size={14} />
              Procesamiento local
            </span>
            <DarkModeToggle />
          </div>
        </div>
        <header className="page-intro">
          <div>
            <p className="eyebrow">ESCUCHA MENOS. APROVECHA MÁS.</p>
            <h1>
              Del vídeo a tu
              <br />
              <em>próxima idea.</em>
            </h1>
            <p className="intro-description">
              Convierte lo que escuchas en texto que puedes usar.
              <br className="desktop-break" /> A tu ritmo, desde tu ordenador.
            </p>
          </div>
          <div className="intro-art" aria-hidden="true">
            <div className="art-caption">
              <span className="art-dot" />
              AUDIO → TEXTO
            </div>
            <div className="art-wave">
              {[
                14, 24, 38, 22, 45, 63, 36, 51, 76, 92, 68, 42, 65, 84, 58, 38,
                66, 48, 30, 55, 72, 46, 32, 49, 28, 40, 20, 30, 16,
              ].map((height, index) => (
                <i key={index} style={{ height: `${height}%` }} />
              ))}
            </div>
            <div className="art-document">
              <span>
                <Icon name="file" size={15} />
                Una idea, por escrito.
              </span>
              <i />
              <i />
              <i />
            </div>
          </div>
        </header>
        <JobProvider>
          <TranscriberPanel />
        </JobProvider>
        <footer className="app-footer">
          <span>VideoTranscriber</span>
          <span>Un poco menos de ruido. Un poco más de claridad.</span>
        </footer>
      </main>
    </div>
  );
}
