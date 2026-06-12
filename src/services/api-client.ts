const envApiUrl = import.meta.env.VITE_API_BASE_URL;
const envWsUrl = import.meta.env.VITE_WS_BASE_URL;

// .env (dev) または .env.production (prod) からポートを取得
const SERVER_PORT = import.meta.env.VITE_SERVER_PORT || "8001";

export const API_BASE_URL = envApiUrl || `http://127.0.0.1:${SERVER_PORT}/api`;
export const WS_BASE_URL = envWsUrl || `ws://127.0.0.1:${SERVER_PORT}/ws`;

// LLM 呼び出しを含むリクエストがあるため長めに設定
const REQUEST_TIMEOUT_MS = 120_000;

/**
 * FastAPI の detail を保持する API エラー。
 * UI 側で e.detail をそのままトースト表示できる。
 */
export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`API Error: ${status} ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** エラーから UI 表示用のメッセージを取り出すヘルパー */
export function getErrorDetail(e: unknown): string {
  if (e instanceof ApiError) return e.detail;
  if (e instanceof Error) return e.message;
  return String(e);
}

async function buildApiError(response: Response): Promise<ApiError> {
  let detail = response.statusText || `HTTP ${response.status}`;
  try {
    const body = await response.json();
    if (body?.detail) {
      detail =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail);
    }
  } catch {
    // JSON でないレスポンスボディは無視
  }
  return new ApiError(response.status, detail);
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private resolveUrl(path: string): string {
    const base = this.baseUrl.endsWith("/")
      ? this.baseUrl.slice(0, -1)
      : this.baseUrl;
    const endpoint = path.startsWith("/") ? path : `/${path}`;
    return `${base}${endpoint}`;
  }

  private async request<T>(url: string, init: RequestInit): Promise<T> {
    const response = await fetch(url, {
      ...init,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw await buildApiError(response);
    }
    return response.json();
  }

  async get<T>(
    path: string,
    params?: Record<string, string | number | boolean | null | undefined | string[]>
  ): Promise<T> {
    const url = new URL(this.resolveUrl(path));
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          if (Array.isArray(value)) {
            value.forEach((v) => url.searchParams.append(key, v));
          } else {
            url.searchParams.append(key, value.toString());
          }
        }
      });
    }

    return this.request<T>(url.toString(), { method: "GET" });
  }

  async post<T>(path: string, body: any): Promise<T> {
    return this.request<T>(this.resolveUrl(path), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  async put<T>(path: string, body: any): Promise<T> {
    return this.request<T>(this.resolveUrl(path), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  async delete(path: string): Promise<void> {
    const response = await fetch(this.resolveUrl(path), {
      method: "DELETE",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });

    if (!response.ok) {
      throw await buildApiError(response);
    }
  }

  async patch<T>(path: string, body: any): Promise<T> {
    return this.request<T>(this.resolveUrl(path), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }
}

export const apiClient = new ApiClient(API_BASE_URL);
