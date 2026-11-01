import { errorDetail, fallbackMessage } from "../lib/apiErrors";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8187";

export class ApiError extends Error {
  code: string;
  status?: number;

  constructor(code: string, message: string, status?: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // The body wasn't JSON; fall back to a message for the status code.
    }
    const { code, message } = errorDetail(
      (body as { detail?: unknown } | null)?.detail,
      fallbackMessage(res.status),
    );
    throw new ApiError(code ?? "request_failed", message, res.status);
  }
  return (await res.json()) as T;
}

async function fetchApi(
  path: string,
  init?: RequestInit,
  timeoutMs?: number,
): Promise<Response> {
  try {
    const timeout = AbortSignal.timeout(
      timeoutMs ?? (init?.body instanceof FormData ? 300_000 : 15_000),
    );
    const signal = init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout;
    return await fetch(`${BASE_URL}${path}`, { ...init, signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new ApiError(
        "timeout",
        "El servidor local tardó demasiado en responder. Inténtalo de nuevo.",
      );
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("aborted", "Solicitud cancelada.");
    }
    throw new ApiError("network_error", "No se pudo conectar con el servidor local.");
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetchApi(path, { signal });
  return handleResponse<T>(res);
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchApi(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<T>(res);
}

export async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchApi(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<T>(res);
}

export async function postForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetchApi(path, { method: "POST", body: form });
  return handleResponse<T>(res);
}

export async function del(path: string): Promise<void> {
  const res = await fetchApi(path, { method: "DELETE" });
  // Reuse the server's explanation, for example a file that is still in use.
  if (!res.ok) await handleResponse<never>(res);
}

export function downloadFileUrl(path: string): string {
  return `${BASE_URL}${path}`;
}
