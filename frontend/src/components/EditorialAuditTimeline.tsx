import { useEffect, useState } from "react";
import { useEditorialTask } from "../hooks/useEditorialTask";
import { checkedEvents, statusText } from "../lib/editorialWorkflow";
import type { EditorialApi } from "../services/editorialApi";
import type { DraftStatus, EditorialEvent } from "../types/editorial";
import { EditorialPager } from "./EditorialPager";
import { Button } from "./ui/button";
export function EditorialAuditTimeline({ client, draftId, revision, onDenied }: { client: EditorialApi; draftId: string; revision: number; onDenied: (message: string) => void }) {
  const task = useEditorialTask(onDenied); const [rows, setRows] = useState<EditorialEvent[]>([]); const [page, setPage] = useState({ offset: 0, limit: 20 });
  async function load(offset = 0, limit = 20) {
    const ticket = task.begin(); if (!ticket) return;
    try { const result = checkedEvents(await client.events(draftId, limit, offset, ticket.signal), limit); if (task.owns(ticket)) { setRows(result); setPage({ offset, limit }); } }
    catch (reason) { if (task.owns(ticket)) task.report(reason); } finally { task.finish(ticket); }
  }
  useEffect(() => { void load(); }, [client, draftId, revision]);
  return <section aria-label="Dnevnik uredničkih događaja" className="space-y-4 rounded-xl border border-white/20 p-4"><h3 className="text-xl font-bold">Dnevnik odluka i događaja</h3>
    <p className="text-sm">Istorijski zapisi ostaju sačuvani. Ranije odobrenje nije dokaz da je trenutna verzija odobrena.</p>
    {task.busy ? <p role="status">Učitavanje dnevnika…</p> : null}{task.error ? <p role="alert">{task.error}</p> : null}
    <EditorialPager {...page} count={rows.length} busy={task.busy} onPage={(offset, limit) => void load(offset, limit)} label="Događaja po stranici" />
    <ol className="space-y-3">{rows.map(event => <li key={event.id} className="space-y-1 rounded-lg border border-white/15 p-3 text-sm"><p className="font-bold">{event.event_type} · v{event.version_number ?? "—"}</p><p>{statusText[event.from_status as DraftStatus] ?? event.from_status ?? "Početak"} → {statusText[event.to_status as DraftStatus] ?? event.to_status ?? "—"}</p><p className="break-words">{event.actor_subject} · {event.actor_issuer}</p><time dateTime={event.occurred_at}>{event.occurred_at}</time>{typeof event.details.reason === "string" ? <p className="whitespace-pre-wrap break-words">Obrazloženje: {event.details.reason}</p> : null}<p className="break-all text-xs">Događaj: {event.id}<br />Komanda: {event.command_id ?? "Nije zabeležena"}</p></li>)}</ol>
    {!rows.length && !task.busy ? <p>Nema događaja na ovoj stranici.</p> : null}<Button type="button" variant="secondary" disabled={task.busy} onClick={() => void load(page.offset, page.limit)}>Osveži dnevnik</Button>
  </section>;
}
