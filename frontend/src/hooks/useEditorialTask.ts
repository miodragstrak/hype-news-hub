import { useCallback, useEffect, useRef, useState } from "react";
import { EditorialApiError } from "../services/editorialApi";
import { privateError } from "../lib/editorialWorkflow";
export type EditorialTicket = { signal: AbortSignal };
/** One private operation at a time; an unmounted/denied page never accepts its response. */
export function useEditorialTask(onDenied: (message: string) => void) {
  const controller = useRef<AbortController>();
  const current = useRef<EditorialTicket | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { const next = new AbortController(); controller.current = next; return () => { next.abort(); current.current = null; }; }, []);
  const begin = useCallback(() => {
    const signal = controller.current?.signal;
    if (!signal || signal.aborted || current.current) return null;
    const ticket = { signal }; current.current = ticket; setBusy(true); setError(null); return ticket;
  }, []);
  const owns = useCallback((ticket: EditorialTicket) => current.current === ticket && !ticket.signal.aborted, []);
  const isRunning = useCallback(() => current.current !== null, []);
  const finish = useCallback((ticket: EditorialTicket) => { if (current.current === ticket) { current.current = null; if (!ticket.signal.aborted) setBusy(false); } }, []);
  const report = useCallback((reason: unknown) => {
    const message = privateError(reason);
    if (reason instanceof EditorialApiError && [401, 403].includes(reason.status)) { controller.current?.abort(); current.current = null; onDenied(message); }
    else setError(message);
  }, [onDenied]);
  return { busy, error, begin, owns, finish, report, setError, isRunning };
}
