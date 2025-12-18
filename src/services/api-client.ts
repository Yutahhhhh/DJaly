const envApiUrl = import.meta.env.VITE_API_BASE_URL;
const envWsUrl = import.meta.env.VITE_WS_BASE_URL;

export const API_BASE_URL = envApiUrl || "http://127.0.0.1:8001/api";
export const WS_BASE_URL = envWsUrl || "ws://127.0.0.1:8001/ws";

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

    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  async post<T>(path: string, body: any): Promise<T> {
    const url = this.resolveUrl(path);
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  async put<T>(path: string, body: any): Promise<T> {
    const url = this.resolveUrl(path);
    const response = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  async delete(path: string): Promise<void> {
    const url = this.resolveUrl(path);
    const response = await fetch(url, {
      method: "DELETE",
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }
  }

  async patch<T>(path: string, body: any): Promise<T> {
    const url = this.resolveUrl(path);
    const response = await fetch(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }
    return response.json();
  }
}

export const apiClient = new ApiClient(API_BASE_URL);
