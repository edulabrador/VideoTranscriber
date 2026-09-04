const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let code = "request_failed";
    let message = "No se pudo completar la solicitud";
    try {
      const body = await res.json();
      message = body.detail?.message ?? body.detail ?? message;
      code = body.detail?.code ?? code;
    } catch {
      // response body wasn't JSON — fall back to statusText
    }
    throw new ApiError(code, message);
  }
  return (await res.json()) as T;
}

async function fetchApi(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${BASE_URL}${path}`, init);
  } catch {
    throw new ApiError("network_error", "No se pudo conectar con el servidor local.");
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetchApi(path);
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

export async function postForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetchApi(path, { method: "POST", body: form });
  return handleResponse<T>(res);
}

export async function del(path: string): Promise<void> {
  const res = await fetchApi(path, { method: "DELETE" });
  if (!res.ok) throw new ApiError("request_failed", "No se pudo eliminar el elemento");
}

export function downloadFileUrl(path: string): string {
  return `${BASE_URL}${path}`;
}
