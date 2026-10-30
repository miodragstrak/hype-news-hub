import type { SystemStatus } from "../types/system";
import { DEMO_MODE, requestJson } from "./apiClient";

export async function getSystemStatus(): Promise<SystemStatus> {
  if (DEMO_MODE) {
    throw new Error("Backend status unavailable in demo mode");
  }

  return requestJson<SystemStatus>("/", "Unable to fetch backend status");
}
