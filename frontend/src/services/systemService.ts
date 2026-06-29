import type { SystemStatus } from "../types/system";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function getSystemStatus(): Promise<SystemStatus> {
  const response = await fetch(`${API_BASE_URL}/`);

  if (!response.ok) {
    throw new Error("Unable to fetch backend status");
  }

  return response.json() as Promise<SystemStatus>;
}
