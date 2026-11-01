import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { EditorialPrivatePage, type PrivatePageAccess } from "../components/EditorialPrivatePage";
import { EditorialVersionContent } from "../components/EditorialVersionContent";
import { Button } from "../components/ui/button";
import { useEditorialTask } from "../hooks/useEditorialTask";
import { checkedEvents, checkedHead, checkedVersion, matchingApproval, sameApprovedPin } from "../lib/editorialWorkflow";
import { EditorialApiError } from "../services/editorialApi";
import type { EditorialDraft, EditorialEvent, EditorialVersion } from "../types/editorial";

type ApprovedSnapshot = { head: EditorialDraft; version: EditorialVersion; decision: EditorialEvent | undefined; checkedAt: string };
export function EditorialApprovedPage() {
  const { storyId = "" } = useParams();
  return <EditorialPrivatePage storyId={storyId} title="Odobreni pregled">{access => <Approved storyId={storyId} {...access} />}</EditorialPrivatePage>;
}
function Approved({ storyId, client, onDenied }: PrivatePageAccess & { storyId: string }) {
  const task = useEditorialTask(onDenied);
  const cached = useRef<ApprovedSnapshot | null>(null);
  const [snapshot, setSnapshot] = useState<ApprovedSnapshot | null>(null);
  const [verified, setVerified] = useState(false);
  const [notice, setNotice] = useState("Provera aktuelnog odobrenja…");
  async function check(resolveVersion: boolean) {
    if (!resolveVersion && !cached.current) return;
    const ticket = task.begin(); if (!ticket) return;
    setVerified(false);
    const clear = (message: string) => { cached.current = null; setSnapshot(null); setNotice(message); };
    try {
      let value: ApprovedSnapshot;
      if (!resolveVersion && cached.current) {
        const pin = cached.current;
        const current = checkedHead(await client.draft(pin.head.id, ticket.signal), storyId);
        if (!task.owns(ticket)) return;
        if (!sameApprovedPin(current, pin.head)) { clear("Aktuelno odobrenje se promenilo ili više ne važi. Učitajte novu potvrdu pre pregleda."); return; }
        value = { ...pin, checkedAt: new Date().toISOString() };
      } else {
        const head = checkedHead(await client.find(storyId, ticket.signal), storyId);
        if (!task.owns(ticket)) return;
        if (head.status !== "approved" || !head.effective_approval || !head.current_version) { clear("Nema efektivno odobrene trenutne verzije. Ranija odluka ili nesnimljeni tekst nisu odobreni sadržaj."); return; }
        const version = checkedVersion(await client.version(head.id, head.current_version.version_number, ticket.signal), head.current_version);
        let events: EditorialEvent[] = [];
        try { events = checkedEvents(await client.events(head.id, 50, 0, ticket.signal), 50); }
        catch (error) { if (error instanceof EditorialApiError && [401, 403].includes(error.status)) throw error; }
        const finalHead = checkedHead(await client.draft(head.id, ticket.signal), storyId);
        if (!task.owns(ticket)) return;
        if (!sameApprovedPin(finalHead, head)) { clear("Odobrenje se promenilo tokom učitavanja. Pregled nije prikazan; proverite ponovo."); return; }
        value = { head: finalHead, version, decision: matchingApproval(events, finalHead), checkedAt: new Date().toISOString() };
      }
      if (task.owns(ticket)) { cached.current = value; setSnapshot(value); setVerified(!document.hidden); setNotice(""); }
    } catch (error) { if (task.owns(ticket)) { setNotice("Odobrenje trenutno nije potvrđeno. Odobreni sadržaj je sakriven."); task.report(error); } }
    finally { task.finish(ticket); }
  }
  useEffect(() => {
    void check(true);
    const onFocus = () => { void check(false); };
    const onVisibility = () => { if (document.hidden) setVerified(false); else void check(false); };
    const timer = setInterval(() => { if (!document.hidden) void check(false); }, 30_000);
    window.addEventListener("focus", onFocus); document.addEventListener("visibilitychange", onVisibility);
    return () => { clearInterval(timer); window.removeEventListener("focus", onFocus); document.removeEventListener("visibilitychange", onVisibility); };
  }, [client, storyId]);
  return <div className="space-y-5">
    <p>Pregled je vezan za tačnu nepromenljivu verziju i efektivno odobrenje servera. Poslednja provera je vremenski presek; ponavlja se pri povratku na stranicu i svakih 30 sekundi dok je vidljiva.</p>
    <div className="rounded-xl border border-amber-300 p-4"><p className="font-bold">WordPress objavljivanje još nije povezano.</p><Button type="button" disabled className="mt-3">Objavljivanje nije dostupno</Button></div>
    <Button type="button" variant="secondary" disabled={task.busy} onClick={() => void check(true)}>Učitaj trenutno odobrenu verziju</Button>
    {task.busy ? <p role="status">Provera odobrenja…</p> : null}{task.error ? <p role="alert" className="text-rose-200">{task.error}</p> : null}{notice ? <p role="status">{notice}</p> : null}
    {verified && snapshot ? <>
      <div className="space-y-2 rounded-xl border border-emerald-300 p-4"><p className="font-bold">Efektivno odobreno · verzija {snapshot.version.version_number} · revizija {snapshot.head.revision}</p><p className="break-all text-xs">ID: {snapshot.version.id}<br />SHA-256: {snapshot.version.content_hash}</p><p>Poslednja provera: <time dateTime={snapshot.checkedAt}>{snapshot.checkedAt}</time></p>
        {snapshot.decision ? <p className="break-words">Odobrio: {snapshot.decision.actor_subject} · {snapshot.decision.actor_issuer}<br /><time dateTime={snapshot.decision.occurred_at}>{snapshot.decision.occurred_at}</time><br />Komanda: {snapshot.decision.command_id}</p> : <p>Metapodaci odluke nisu pronađeni u prvih 50 događaja. Važenje odobrenja je provereno kroz trenutno stanje servera.</p>}
        <Link className="text-[#f5c518] underline" to={`/review/${storyId}/decisions`}>Otvori dnevnik odluka</Link>
      </div>
      <EditorialVersionContent version={snapshot.version} label="Odobreni pregled — nepromenljiva verzija" />
    </> : null}
  </div>;
}
