import { useEffect, useState } from "react";

import { getSystemStatus } from "../services/systemService";
import type { SystemStatus } from "../types/system";

type UseBackendStatusState = {
  data: SystemStatus | null;
  isLoading: boolean;
  error: string | null;
};

export function useBackendStatus(): UseBackendStatusState {
  const [data, setData] = useState<SystemStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadStatus(): Promise<void> {
      try {
        const status = await getSystemStatus();
        if (isMounted) {
          setData(status);
        }
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : "Unknown error");
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    void loadStatus();

    return () => {
      isMounted = false;
    };
  }, []);

  return { data, isLoading, error };
}
