import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { EditorialPrivatePage, type PrivatePageAccess } from "../components/EditorialPrivatePage";
import { EditorialPager } from "../components/EditorialPager";
import { EditorialVersionContent } from "../components/EditorialVersionContent";
import { Button } from "../components/ui/button";
import { useEditorialTask } from "../hooks/useEditorialTask";
import { checkedHead, checkedSummaries, checkedVersion } from "../lib/editorialWorkflow";
import { EditorialApiError } from "../services/editorialApi";
import type { EditorialVersion, EditorialVersionSummary } from "../types/editorial";
export function EditorialHistoryPage() {
  const { storyId = "" } = useParams();
  return <EditorialPrivatePage storyId={storyId} title="Istorija verzija">{access => <History storyId={storyId} {...access} />}</EditorialPrivatePage>;
}
function History({ storyId, client, onDenied }: PrivatePageAccess & { storyId: string }) {
  const task = useEditorialTask(onDenied);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [rows, setRows] = useState<EditorialVersionSummary[]>([]);
  const [page, setPage] = useState({ offset: 0, limit: 20 });
  const [selected, setSelected] = useState<EditorialVersionSummary | null>(null);
  const [detail, setDetail] = useState<EditorialVersion | null>(null);
  async function load(offset = 0, limit = 20) {
    const ticket = task.begin(); if (!ticket) return;
    setDetail(null); setSelected(null);
    try {
      const id = draftId ?? checkedHead(await client.find(storyId, ticket.signal), storyId).id;
      const summaries = checkedSummaries(await client.versions(id, limit, offset, ticket.signal), limit);
      if (task.owns(ticket)) { setDraftId(id); setRows(summaries); setPage({ offset, limit }); setMissing(false); }
    } catch (reason) { if (task.owns(ticket)) { if (reason instanceof EditorialApiError && reason.status === 404) setMissing(true); else task.report(reason); } }
    finally { task.finish(ticket); }
  }
  useEffect(() => { void load(); }, [client, storyId]);
  async function inspect(row: EditorialVersionSummary) {
    if (!draftId) return; const ticket = task.begin(); if (!ticket) return;
    setSelected(row); setDetail(null);
    try { const value = checkedVersion(await client.version(draftId, row.version_number, ticket.signal), row); if (task.owns(ticket)) setDetail(value); }
    catch (reason) { if (task.owns(ticket)) task.report(reason); } finally { task.finish(ticket); }
  }
  return <div className="space-y-5">
    <p>Lista prikazuje samo metapodatke. Sadržaj i zamrznuti izvori učitavaju se izborom verzije. Arhivski prikaz nije potvrda aktuelnog odobrenja.</p>
    {task.busy ? <p role="status">Učitavanje istorije…</p> : null}{task.error ? <p role="alert" className="text-rose-200">{task.error} Za preveliku listu izaberite manju stranicu.</p> : null}
    {missing ? <p>Za ovu priču još nema sačuvanog nacrta.</p> : <>
      <EditorialPager {...page} count={rows.length} busy={task.busy} onPage={(offset, limit) => void load(offset, limit)} label="Verzija po stranici" />
      <ul className="space-y-3">{rows.map(row => <li key={row.id} className="space-y-2 rounded-xl border border-white/20 p-4">
        <p className="font-bold">Verzija {row.version_number} · {row.source_count} izvora</p><p className="break-words text-sm">{row.actor_subject} · {row.actor_issuer} · <time dateTime={row.created_at}>{row.created_at}</time> · {row.origin} · šema {row.payload_schema_version}</p>
        <p className="break-all text-xs text-[#c2d3f5]">ID: {row.id}<br />SHA-256: {row.content_hash}</p>
        <Button type="button" variant="secondary" disabled={task.busy} aria-pressed={selected?.id === row.id} onClick={() => void inspect(row)}>Prikaži verziju {row.version_number}</Button>
      </li>)}</ul>
      <Button type="button" variant="secondary" disabled={task.busy} onClick={() => void load(page.offset, page.limit)}>Osveži istoriju</Button>
    </>}
    {detail ? <EditorialVersionContent version={detail} label="Arhivski pregled" /> : selected && !task.busy ? <p>Detalj verzije nije učitan. Pokušajte ponovo izborom verzije.</p> : null}
  </div>;
}
