import { downloadFileUrl } from "../api/client";
import type { ExportFormat } from "../api/types";

const FORMATS: { fmt: ExportFormat; label: string }[] = [
  { fmt: "txt", label: "Descargar TXT" },
  { fmt: "srt", label: "Descargar SRT" },
  { fmt: "json", label: "Descargar JSON" },
];

export function ExportMenu({ jobId }: { jobId: string }) {
  return (
    <div className="flex flex-wrap gap-2">
      {FORMATS.map(({ fmt, label }) => (
        <a
          key={fmt}
          href={downloadFileUrl(`/api/jobs/${jobId}/download/${fmt}`)}
          download
          className="rounded-xl border border-stone-200 bg-white px-4 py-2 text-sm font-semibold text-stone-600 shadow-sm transition hover:border-brand-300 hover:text-brand-600 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-300 dark:hover:border-brand-700 dark:hover:text-brand-400"
        >
          {label}
        </a>
      ))}
    </div>
  );
}
