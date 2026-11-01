import { useCallback, useEffect, useState } from "react";
import { Link, useBeforeUnload, useBlocker, useParams } from "react-router-dom";
import { ConfirmDiscardDialog } from "../components/ConfirmDiscardDialog";
import { EditorialAuditTimeline } from "../components/EditorialAuditTimeline";
import { EditorialPrivatePage, type PrivatePageAccess } from "../components/EditorialPrivatePage";
import { EditorialVersionContent } from "../components/EditorialVersionContent";
import { Button } from "../components/ui/button";
import { useEditorialTask } from "../hooks/useEditorialTask";
import { isUuid, newCommandId, readPublishingPayload } from "../lib/editorialForm";
import { actionText, allowedActions, checkedHead, reasonError, statusText, targetStatus } from "../lib/editorialWorkflow";
import { EditorialApiError } from "../services/editorialApi";
import type { DecisionCommand, EditorialAction, EditorialDraft, EditorialReceipt, NegativeDecisionCommand, VersionCommand } from "../types/editorial";

type DecisionIntent = { action: EditorialAction; draftId: string; command: VersionCommand | DecisionCommand | NegativeDecisionCommand; receipt: EditorialReceipt | null };
export function EditorialDecisionsPage() {
  const { storyId = "" } = useParams();
  return <EditorialPrivatePage storyId={storyId} title="Pregled nacrta i uredničke odluke">{access => <Decisions storyId={storyId} {...access} />}</EditorialPrivatePage>;
}
function Decisions({ storyId, client, capabilities, onDenied }: PrivatePageAccess & { storyId: string }) {
  const task = useEditorialTask(onDenied);
  const [head, setHead] = useState<EditorialDraft | null>(null);
  const [reason, setReason] = useState(""); const [validation, setValidation] = useState<string | null>(null);
  const [intent, setIntent] = useState<DecisionIntent | null>(null);
  const [confirmation, setConfirmation] = useState<DecisionIntent | null>(null);
  const [reloadConfirm, setReloadConfirm] = useState(false);
  const [conflict, setConflict] = useState(false); const [latest, setLatest] = useState<EditorialDraft | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const guarded = Boolean(reason.length || intent);
  const blocker = useBlocker(guarded);
  useBeforeUnload(useCallback((event: BeforeUnloadEvent) => { if (guarded) { event.preventDefault(); event.returnValue = ""; } }, [guarded]));
  async function load() {
    const ticket = task.begin(); if (!ticket) return;
    setReloadConfirm(false); setConfirmation(null); setMessage(null);
    try {
      const value = checkedHead(await client.find(storyId, ticket.signal), storyId);
      if (task.owns(ticket)) { setHead(value); setConflict(false); setLatest(null); setIntent(null); }
    } catch (error) { if (task.owns(ticket)) task.report(error); } finally { task.finish(ticket); }
  }
  useEffect(() => { void load(); }, [client, storyId]);
  function prepare(action: EditorialAction) {
    if (!head?.current_version || intent || confirmation || conflict || task.isRunning() || !allowedActions(head, capabilities).includes(action)) return;
    const problem = action === "submit" ? null : reasonError(reason, action !== "approve"); setValidation(problem); if (problem) return;
    try {
      const base: VersionCommand = { command_id: newCommandId(), expected_revision: head.revision, version_number: head.current_version.version_number, content_hash: head.current_version.content_hash };
      const command = action === "submit" ? base : { ...base, reason: action === "approve" ? reason.trim() || null : reason.trim() };
      setConfirmation({ action, draftId: head.id, command, receipt: null });
    } catch (error) { task.report(error); }
  }
  async function execute(plan: DecisionIntent) {
    const ticket = task.begin(); if (!ticket) return;
    setConfirmation(null); setIntent(plan); setMessage(null); setValidation(null);
    let pending = plan;
    try {
      if (!pending.receipt) {
        const { action, draftId, command } = pending;
        const receipt = action === "submit" ? await client.submit(draftId, command, ticket.signal) : action === "approve" ? await client.approve(draftId, command as DecisionCommand, ticket.signal) : action === "request-changes" ? await client.requestChanges(draftId, command as NegativeDecisionCommand, ticket.signal) : action === "reject" ? await client.reject(draftId, command as NegativeDecisionCommand, ticket.signal) : await client.reopen(draftId, command as NegativeDecisionCommand, ticket.signal);
        if (!task.owns(ticket)) return;
        if (!receipt || receipt.command_id !== command.command_id || !isUuid(receipt.draft_id) || receipt.draft_id !== draftId || receipt.revision !== command.expected_revision + 1 || receipt.version_number !== command.version_number || receipt.content_hash !== command.content_hash || receipt.status !== targetStatus[action]) throw new EditorialApiError(502, "Unconfirmed decision receipt.");
        pending = { ...pending, receipt }; setIntent(pending);
      }
      const current = checkedHead(await client.draft(pending.draftId, ticket.signal), storyId);
      if (!task.owns(ticket)) return;
      const receipt = pending.receipt!;
      if (current.revision < receipt.revision) throw new EditorialApiError(502, "Unconfirmed state.");
      const exact = current.revision === receipt.revision && current.status === receipt.status && current.current_version?.version_number === receipt.version_number && current.current_version.content_hash === receipt.content_hash;
      if (current.revision === receipt.revision && (!exact || (pending.action === "approve" && !current.effective_approval))) throw new EditorialApiError(502, "Unconfirmed current decision.");
      setHead(current); setIntent(null); if (pending.action !== "submit") setReason(""); setConflict(false); setLatest(null);
      setMessage(exact ? `Server je potvrdio stanje: ${statusText[current.status]}. Revizija ${current.revision}.` : `Komanda je zabeležena, a stanje se u međuvremenu promenilo. Trenutno: ${statusText[current.status]}, revizija ${current.revision}.`);
    } catch (error) {
      if (!task.owns(ticket)) return;
      task.report(error);
      if (error instanceof EditorialApiError && error.status === 409) {
        setIntent(null); setConflict(true);
        try { const current = checkedHead(await client.draft(plan.draftId, ticket.signal), storyId); if (task.owns(ticket)) setLatest(current); }
        catch (readError) { if (task.owns(ticket)) task.report(readError); }
      } else if (error instanceof EditorialApiError && [400, 413, 415, 422].includes(error.status)) setIntent(null);
    } finally { task.finish(ticket); }
  }
  const actions = head ? allowedActions(head, capabilities) : [];
  const locked = task.busy || Boolean(intent) || Boolean(confirmation);
  return <div className="space-y-6">
    <p>Odluka važi samo za tačnu sačuvanu verziju i njen hash. Nesnimljeni tekst iz editora nije deo ovog pregleda.</p>
    {task.busy ? <p role="status">Provera sa serverom…</p> : null}{task.error ? <p role="alert" className="text-rose-200">{task.error}</p> : null}{message ? <p role="status" className="text-emerald-200">{message}</p> : null}
    <Button type="button" variant="secondary" disabled={locked} onClick={() => setReloadConfirm(true)}>Učitaj najnovije stanje</Button>
    {intent ? <div className="space-y-3 rounded-xl border border-amber-300 p-4"><p>Ishod komande još nije potvrđen. Čuva se isti identifikator, obrazloženje i očekivana revizija.</p><Button type="button" disabled={task.busy} onClick={() => void execute(intent)}>{intent.receipt ? "Potvrdi stanje čitanjem" : "Ponovi istu komandu"}</Button><Button type="button" variant="secondary" disabled={task.busy} onClick={() => setReloadConfirm(true)}>Proveri stanje bez ponavljanja komande</Button></div> : null}
    {conflict ? <div role="alert" className="space-y-2 rounded-xl border border-amber-300 p-4"><h3 className="font-bold">Sukob revizija</h3><p>Obrazloženje je sačuvano. Odluke su pauzirane dok izričito ne učitate i proverite najnovije stanje.</p>{latest ? <p>Server: {statusText[latest.status]}, revizija {latest.revision}, verzija {latest.current_version?.version_number}.</p> : null}</div> : null}
    {head ? <>
      <p className="font-bold">Sačuvano stanje: {statusText[head.status]} · revizija {head.revision} · verzija {head.current_version?.version_number ?? "—"}</p><p>Aktuelno odobrenje prema serveru: {head.effective_approval ? "Da" : "Ne"}.</p>
      {head.status === "changes_requested" && capabilities.permissions.includes("editorial:edit") ? <Link className="font-semibold text-[#f5c518] underline" to={`/review/${storyId}/edit`}>Nastavi uređivanje traženih izmena</Link> : null}
      <section aria-label="Uredničke odluke" className="space-y-4 rounded-xl border border-white/20 p-5"><h3 className="text-xl font-bold">Odluka o verziji {head.current_version?.version_number ?? "—"}</h3>
        {reason.length > 0 || actions.some(action => action !== "submit") ? <><label className="block">Obrazloženje (obavezno za izmene, odbijanje i ponovno otvaranje)<textarea lang="sr-Latn" className="mt-2 block w-full rounded-xl border border-white/30 bg-[#071d49] p-3" rows={4} maxLength={4000} readOnly={locked || !actions.some(action => action !== "submit")} value={reason} aria-invalid={Boolean(validation)} aria-describedby={validation ? "decision-reason-error" : undefined} onChange={event => { if (!locked && !task.isRunning()) { setReason(event.target.value); setValidation(null); setMessage(null); } }} /></label><p className="text-sm">Slanje na pregled ne uključuje obrazloženje. Lokalni unos se zadržava dok ga ne pošaljete odlukom ili izričito uklonite.</p><Button type="button" variant="secondary" disabled={locked} onClick={() => { if (!task.isRunning()) setReason(""); }}>Obriši lokalno obrazloženje</Button></> : null}
        {validation ? <p id="decision-reason-error" role="alert">{validation}</p> : null}
        <div className="flex flex-wrap gap-3">{actions.map(action => <Button key={action} type="button" disabled={locked || conflict || (action === "submit" && !readPublishingPayload(head.current_version?.payload))} onClick={() => prepare(action)}>{actionText[action]}</Button>)}</div>
        {!actions.length ? <p>Za ovo stanje i vaše dozvole nema dostupnih uredničkih komandi.</p> : null}
      </section>
      {head.current_version ? <EditorialVersionContent version={head.current_version} label="Pregled nacrta — sačuvana verzija" /> : <p>Nacrt nema sačuvanu verziju.</p>}
      <EditorialAuditTimeline key={`${head.id}:${head.revision}`} client={client} draftId={head.id} revision={head.revision} onDenied={onDenied} />
    </> : !task.busy ? <p>Nacrt nije učitan. Sačuvajte ga u editoru ili ponovite proveru.</p> : null}
    {confirmation ? <ConfirmDiscardDialog lang="sr-Latn" title={`Potvrdite: ${actionText[confirmation.action]}`} message={`Verzija ${confirmation.command.version_number}, očekivana revizija ${confirmation.command.expected_revision}. SHA-256: ${confirmation.command.content_hash}${"reason" in confirmation.command && confirmation.command.reason ? ` · Obrazloženje: ${confirmation.command.reason}` : ""}. Odluku će proveriti server.`} confirmLabel="Potvrdi odluku" cancelLabel="Odustani" onCancel={() => setConfirmation(null)} onConfirm={() => void execute(confirmation)} /> : null}
    {reloadConfirm ? <ConfirmDiscardDialog lang="sr-Latn" title="Učitati najnovije stanje?" message="Obrazloženje se zadržava. Prekidate praćenje nepotvrđene komande koja možda već postoji na serveru. Proverite novu verziju pre naredne odluke." confirmLabel="Učitaj i proveri" cancelLabel="Odustani" onCancel={() => setReloadConfirm(false)} onConfirm={() => void load()} /> : null}
    {blocker.state === "blocked" ? <ConfirmDiscardDialog lang="sr-Latn" title="Napustiti nezavršenu odluku?" message="Lokalno obrazloženje i praćenje komande biće uklonjeni. Server možda još završava poslatu komandu." confirmLabel="Napusti stranicu" cancelLabel="Ostani" onCancel={() => blocker.reset()} onConfirm={() => blocker.proceed()} /> : null}
  </div>;
}
