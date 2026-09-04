import { useState } from "react";

import { FileDropZone } from "./components/FileDropZone";
import { HistoryList } from "./components/HistoryList";
import { ProgressIndicator } from "./components/ProgressIndicator";
import { TranscriptView } from "./components/TranscriptView";
import { UrlInputForm } from "./components/UrlInputForm";
import { JobProvider, useJobContext } from "./context/JobContext";
import { useJobPolling } from "./hooks/useJobPolling";
import type { AudioQuality, TranscriptionProfile } from "./api/types";

type InputMode = "url" | "file";

function DarkModeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));

  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  };

  return (
    <button
      type="button"
      onClick={toggle}
      className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl border border-stone-200/80 bg-white/80 text-stone-600 shadow-sm backdrop-blur transition hover:-translate-y-0.5 hover:text-brand-600 dark:border-stone-700 dark:bg-stone-900/80 dark:text-stone-300 dark:hover:text-brand-400"
      aria-label={dark ? "Activar tema claro" : "Activar tema oscuro"}
      title={dark ? "Activar tema claro" : "Activar tema oscuro"}
    >
      {dark ? (
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7Z" />
        </svg>
      )}
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

  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-[1.75rem] border border-white/80 bg-white/85 p-3 shadow-soft backdrop-blur-xl dark:border-stone-800 dark:bg-stone-900/85 sm:p-5">
        <div className="grid grid-cols-2 gap-1 rounded-2xl bg-stone-100 p-1 dark:bg-stone-800">
          {(["url", "file"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded-xl px-4 py-2.5 text-sm font-semibold transition ${
                mode === m
                  ? "bg-white text-stone-900 shadow-sm dark:bg-stone-700 dark:text-white"
                  : "text-stone-500 hover:text-stone-900 dark:text-stone-400 dark:hover:text-white"
              }`}
            >
              {m === "url" ? "Pegar enlace" : "Subir archivo"}
            </button>
          ))}
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-bold text-stone-600 dark:text-stone-300">
            Perfil de transcripción
            <select
              value={profile}
              onChange={(event) => {
                const value = event.target.value as TranscriptionProfile;
                setProfile(value);
                localStorage.setItem("transcription-profile", value);
              }}
              className="mt-1.5 w-full rounded-xl border border-stone-200 bg-white px-3 py-2.5 text-sm font-medium text-stone-800 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-100"
            >
              <option value="fast">Rápido. Menor espera</option>
              <option value="balanced">Equilibrado. Recomendado</option>
              <option value="precise">Preciso. Más lento</option>
            </select>
          </label>

          {mode === "url" && (
            <label className="text-xs font-bold text-stone-600 dark:text-stone-300">
              Calidad de descarga
              <select
                value={audioQuality}
                onChange={(event) => {
                  const value = event.target.value as AudioQuality;
                  setAudioQuality(value);
                  localStorage.setItem("audio-quality", value);
                }}
                className="mt-1.5 w-full rounded-xl border border-stone-200 bg-white px-3 py-2.5 text-sm font-medium text-stone-800 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-100"
              >
                <option value="compact">Compacta. Descarga rápida</option>
                <option value="balanced">Equilibrada. Recomendada</option>
                <option value="best">Máxima. Archivo mayor</option>
              </select>
            </label>
          )}
        </div>

        <div className="mt-5">
          {mode === "url" ? (
            <UrlInputForm profile={profile} audioQuality={audioQuality} />
          ) : (
            <FileDropZone profile={profile} />
          )}
        </div>
      </section>

      <ProgressIndicator />

      {state.result && state.jobId && <TranscriptView jobId={state.jobId} result={state.result} />}

      <HistoryList />
    </div>
  );
}

export default function App() {
  return (
    <div className="relative min-h-screen overflow-hidden bg-[#f5fbff] text-stone-900 transition-colors dark:bg-[#08111f] dark:text-stone-100">
      <div aria-hidden="true" className="pointer-events-none absolute -left-32 -top-40 h-96 w-96 rounded-full bg-sky-300/30 blur-3xl dark:bg-sky-700/10" />
      <div aria-hidden="true" className="pointer-events-none absolute -right-40 top-40 h-[28rem] w-[28rem] rounded-full bg-cyan-200/35 blur-3xl dark:bg-cyan-700/10" />

      <main className="relative mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-14">
        <header className="mb-8">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-brand-600 to-cyan-400 text-white shadow-glow">
                <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                  <path d="M4 12h2l2.2-5 3.3 10 2.6-7 2 4H20" />
                </svg>
              </div>
              <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">VideoTranscriber</h1>
            </div>
            <DarkModeToggle />
          </div>

          <div className="mt-7 max-w-2xl">
            <h2 className="text-3xl font-extrabold leading-tight tracking-tight sm:text-5xl">
              Tus vídeos, convertidos en <span className="bg-gradient-to-r from-brand-600 to-cyan-500 bg-clip-text text-transparent">texto claro.</span>
            </h2>
            <p className="mt-4 text-base leading-7 text-stone-600 dark:text-stone-300 sm:text-lg">
              Convierte vídeos de Instagram, TikTok y Twitter (X) en texto desde tu ordenador.
            </p>
            <div className="mt-5 flex flex-wrap gap-2" aria-label="Plataformas compatibles">
              {["Instagram", "TikTok", "Twitter (X)"].map((platform) => (
                <span key={platform} className="rounded-full border border-stone-200 bg-white/70 px-3 py-1 text-xs font-semibold text-stone-600 shadow-sm backdrop-blur dark:border-stone-700 dark:bg-stone-900/60 dark:text-stone-300">
                  {platform}
                </span>
              ))}
            </div>
          </div>
        </header>

        <JobProvider>
          <TranscriberPanel />
        </JobProvider>

        <footer className="mt-8 text-center text-xs leading-5 text-stone-500">
          Los archivos temporales se eliminan automáticamente al terminar.
        </footer>
      </main>
    </div>
  );
}
