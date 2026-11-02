/** Readable messages from the error bodies the API returns. */

interface ValidationItem {
  loc?: unknown[];
  msg?: unknown;
  type?: unknown;
}

const FIELD_NAMES: Record<string, string> = {
  speakers: "El nombre de un hablante",
  segments: "El texto de un fragmento",
  initial_prompt: "El vocabulario",
  language: "El idioma",
  url: "El enlace",
  num_speakers: "El número de hablantes",
};

const PROBLEMS: Record<string, string> = {
  string_pattern_mismatch: "contiene caracteres no permitidos (< > o saltos de línea)",
  string_too_long: "es demasiado largo",
  string_too_short: "no puede estar vacío",
  too_long: "tiene demasiados elementos",
  missing: "es obligatorio",
};

function validationMessage(item: ValidationItem): string {
  const location = Array.isArray(item.loc) ? item.loc.map(String) : [];
  const field = location.find((part) => part in FIELD_NAMES);
  const problem = typeof item.type === "string" ? PROBLEMS[item.type] : undefined;
  if (field && problem) return `${FIELD_NAMES[field]} ${problem}.`;
  if (field) return `${FIELD_NAMES[field]} no es válido.`;
  return typeof item.msg === "string" ? item.msg : "";
}

/**
 * FastAPI sends ``detail`` as a string, as ``{code, message}`` or, for invalid
 * input, as a list of problems. Turn any of them into one sentence for the user.
 */
export function errorDetail(
  detail: unknown,
  fallback: string,
): { code?: string; message: string } {
  if (typeof detail === "string" && detail.trim()) return { message: detail };
  if (Array.isArray(detail)) {
    const messages = [
      ...new Set(
        detail
          .map((item) => validationMessage((item ?? {}) as ValidationItem))
          .filter(Boolean),
      ),
    ];
    return {
      code: "invalid_request",
      message: messages.length ? messages.join(" ") : fallback,
    };
  }
  if (detail && typeof detail === "object") {
    const { code, message } = detail as { code?: unknown; message?: unknown };
    if (typeof message === "string" && message.trim()) {
      return { code: typeof code === "string" ? code : undefined, message };
    }
  }
  return { message: fallback };
}

export function fallbackMessage(status: number): string {
  if (status === 413) return "El archivo supera el tamaño permitido.";
  if (status === 404) return "No se encontró el elemento solicitado.";
  if (status === 409) return "La operación no es posible en este momento.";
  return "No se pudo completar la solicitud";
}

/** Size in MB or GB, Spanish style. */
export function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) {
    return `${(bytes / 1024 ** 3).toLocaleString("es", { maximumFractionDigits: 1 })} GB`;
  }
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}
