import { downloadFileUrl } from "../api/client";
import type { ExportFormat } from "../api/types";
import { Icon } from "./Icon";

const FORMATS: { fmt: ExportFormat; label: string }[] = [
  { fmt: "txt", label: "Descargar TXT" },
  { fmt: "srt", label: "Descargar SRT" },
  { fmt: "json", label: "Descargar JSON" },
];

export function ExportMenu({ jobId }: { jobId: string }) {
  return (
    <div className="export-actions" aria-label="Descargar transcripción">
      {FORMATS.map(({ fmt, label }) => (
        <a
          key={fmt}
          href={downloadFileUrl(`/api/jobs/${jobId}/download/${fmt}`)}
          download
          className="secondary-button"
          aria-label={label}
          title={label}
        >
          <Icon name="download" size={13} />
          {fmt.toUpperCase()}
        </a>
      ))}
    </div>
  );
}
