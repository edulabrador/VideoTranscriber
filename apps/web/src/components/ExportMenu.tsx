import { downloadFileUrl } from "../api/client";
import type { ExportFormat } from "../api/types";
import { Icon } from "./Icon";

const FORMATS: { fmt: ExportFormat; label: string }[] = [
  { fmt: "txt", label: "Descargar TXT" },
  { fmt: "md", label: "Descargar Markdown con tiempos" },
  { fmt: "srt", label: "Descargar subtítulos SRT" },
  { fmt: "vtt", label: "Descargar subtítulos VTT" },
  { fmt: "json", label: "Descargar JSON" },
];

export function ExportMenu({
  jobId,
  hasSummary = false,
}: {
  jobId: string;
  hasSummary?: boolean;
}) {
  const formats = hasSummary
    ? [
        ...FORMATS,
        { fmt: "summary" as ExportFormat, label: "Descargar el resumen" },
      ]
    : FORMATS;
  return (
    <div className="export-actions" aria-label="Descargar transcripción">
      {formats.map(({ fmt, label }) => (
        <a
          key={fmt}
          href={downloadFileUrl(`/api/jobs/${jobId}/download/${fmt}`)}
          download
          className="secondary-button"
          aria-label={label}
          title={label}
        >
          <Icon name="download" size={13} />
          {fmt === "summary" ? "RESUMEN" : fmt.toUpperCase()}
        </a>
      ))}
    </div>
  );
}
