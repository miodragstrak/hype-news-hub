const env = import.meta.env;

export const API_BASE_URL = (env.VITE_API_URL?.trim() || env.VITE_API_BASE_URL?.trim() || "").replace(/\/+$/, "");
export const DEMO_MODE = env.VITE_DEMO_MODE === "true";

export async function requestJson<T>(path: string, errorMessage: string, init?: RequestInit): Promise<T> {
  if (!API_BASE_URL) {
    throw new Error("Backend connection is not configured.");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new Error(`${errorMessage}: backend is unavailable.`);
  }
  if (!response.ok) {
    throw new Error(`${errorMessage} (status ${response.status}).`);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new Error(`${errorMessage}: backend returned invalid JSON.`);
  }
}
