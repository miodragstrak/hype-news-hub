import type { SystemStatus } from "../types/system";

const API_BASE_URL = (import.meta.env.VITE_API_URL ?? import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/$/, "");

export async function getSystemStatus(): Promise<SystemStatus> {
  if (!API_BASE_URL) {
    throw new Error("Backend status unavailable in demo mode");
  }

  const response = await fetch(`${API_BASE_URL}/`);

  if (!response.ok) {
    throw new Error("Unable to fetch backend status");
  }

  return response.json() as Promise<SystemStatus>;
}
