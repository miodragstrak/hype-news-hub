import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useBeforeUnload, useBlocker, useParams } from "react-router-dom";
import { AiSuggestionComparison } from "../components/AiSuggestionComparison";
import { ConfirmDiscardDialog } from "../components/ConfirmDiscardDialog";
import { EditorialFormFields } from "../components/EditorialFormFields";
import { EditorialPrivatePage, type PrivatePageAccess } from "../components/EditorialPrivatePage";
import { EditorialVersionContent } from "../components/EditorialVersionContent";
import { Button } from "../components/ui/button";
import { useEditorialTask } from "../hooks/useEditorialTask";
import { checkedAcceptanceReceipt, checkedAcceptedVersion, editableAiDraft, formFromSuggestion, frozenAttribution, type AcceptanceIntent } from "../lib/aiAcceptance";
import { checkedAiSuggestion } from "../lib/aiSuggestions";
import { canonicalJson, isUuid, newCommandId, validateForm, type EditorialForm, type FormErrors } from "../lib/editorialForm";
import { checkedHead, statusText } from "../lib/editorialWorkflow";
import { EditorialApiError } from "../services/editorialApi";
import type { AiSuggestion } from "../types/ai";
import type { EditorialDraft, EditorialReceipt, EditorialVersion } from "../types/editorial";

export function EditorialAiAcceptPage() {
  const { storyId = "", suggestionId = "" } = useParams();
  return <EditorialPrivatePage storyId={storyId} title="Uredi i prihvati AI predlog">{access => isUuid(suggestionId) ?
    <Acceptance key={`${storyId}:${suggestionId}`} storyId={storyId} suggestionId={suggestionId} {...access} /> : <p role="alert">Potreban je ispravan UUID AI predloga.</p>}</EditorialPrivatePage>;
}
function Acceptance({ storyId, suggestionId, client, capabilities, onDenied }: PrivatePageAccess & { storyId: string; suggestionId: string }) {
  const task = useEditorialTask(onDenied);
  const [suggestion, setSuggestion] = useState<AiSuggestion | null>(null);
  const [head, setHead] = useState<EditorialDraft | null>(null);
  const [ready, setReady] = useState(false);
  const [form, setForm] = useState<EditorialForm | null>(null);
  const [baseline, setBaseline] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});
  const [conflict, setConflict] = useState(false);
  const [confirmation, setConfirmation] = useState<AcceptanceIntent | null>(null);
  const [intent, setIntent] = useState<AcceptanceIntent | null>(null);
  const [result, setResult] = useState<{ receipt: EditorialReceipt; version: EditorialVersion; head: EditorialDraft } | null>(null);
  const errorSummary = useRef<HTMLDivElement>(null);
  const confirmationTrigger = useRef<HTMLButtonElement>(null);
  const canEdit = capabilities.commands_enabled && capabilities.permissions.includes("editorial:edit");
  const dirty = Boolean(form && canonicalJson(form) !== baseline);
  const guarded = !result && (dirty || Boolean(intent) || Boolean(confirmation));
  const blocker = useBlocker(guarded);
  useBeforeUnload(useCallback((event: BeforeUnloadEvent) => { if (guarded) { event.preventDefault(); event.returnValue = ""; } }, [guarded]));

  async function find(signal: AbortSignal) {
    try { return checkedHead(await client.find(storyId, signal), storyId); }
    catch (error) { if (error instanceof EditorialApiError && error.status === 404) return null; throw error; }
  }
  async function load() {
    if (!canEdit) return;
    const ticket = task.begin(); if (!ticket) return;
    setReady(false);
    try {
      const [value, current] = await Promise.all([client.aiSuggestion(suggestionId, ticket.signal).then(raw => {
        const value = checkedAiSuggestion(raw, storyId);
        if (value.id !== suggestionId || (suggestion && (value.input_hash !== suggestion.input_hash || value.output_hash !== suggestion.output_hash))) throw new EditorialApiError(502, "Invalid suggestion identity.");
        return value;
      }), find(ticket.signal)]);
      if (!task.owns(ticket)) return;
      // Refreshing concurrency context never applies server content to local input.
      if (!form && value.status === "succeeded") { const next = formFromSuggestion(value, current); setForm(next); setBaseline(canonicalJson(next)); }
      setSuggestion(value); setHead(current); setReady(true); setConflict(false);
    } catch (error) { if (task.owns(ticket)) task.report(error); }
    finally { task.finish(ticket); }
  }
  useEffect(() => { void load(); }, [client, storyId, suggestionId, canEdit]);

  function prepare() {
    if (!canEdit || !ready || !form || suggestion?.status !== "succeeded" || !editableAiDraft(head) || conflict || intent || confirmation || task.isRunning()) return;
    const validation = validateForm({ ...form, sources: frozenAttribution(suggestion.input.source) }); setErrors(validation.errors);
    if (Object.keys(validation.errors).length) { errorSummary.current?.focus(); return; }
    try { setConfirmation({ draftId: head?.id ?? null, versionNumber: (head?.current_version?.version_number ?? 0) + 1, receipt: null,
      command: { command_id: newCommandId(), story_id: storyId, expected_revision: head?.revision ?? 0, payload: validation.payload, confirm_acceptance: true } }); }
    catch (error) { task.report(error); }
  }
  async function execute(plan: AcceptanceIntent) {
    if (!canEdit) return;
    const ticket = task.begin(); if (!ticket) return;
    setConfirmation(null); setIntent(plan);
    let pending = plan;
    try {
      if (!pending.receipt) {
        const receipt = checkedAcceptanceReceipt(await client.acceptAiSuggestion(suggestionId, pending.command, ticket.signal), pending);
        if (!task.owns(ticket)) return;
        pending = { ...pending, receipt }; setIntent(pending);
      }
      const receipt = pending.receipt!;
      const [version, current, acceptedRun] = await Promise.all([
        client.version(receipt.draft_id, receipt.version_number, ticket.signal).then(raw => checkedAcceptedVersion(raw, pending, suggestion!.input.source)),
        client.draft(receipt.draft_id, ticket.signal).then(raw => checkedHead(raw, storyId)),
        client.aiSuggestion(suggestionId, ticket.signal).then(raw => checkedAiSuggestion(raw, storyId, suggestion!)),
      ]);
      if (!task.owns(ticket)) return;
      if (acceptedRun.status !== "accepted" || acceptedRun.output_hash !== suggestion!.output_hash || current.id !== receipt.draft_id || current.revision < receipt.revision || (current.revision === receipt.revision &&
        (current.status !== "editing" || current.effective_approval || current.current_version?.id !== version.id || current.current_version.content_hash !== receipt.content_hash))) throw new EditorialApiError(502, "Unconfirmed editorial state.");
      setSuggestion(acceptedRun); setResult({ receipt, version, head: current }); setIntent(null); setErrors({});
    } catch (error) {
      if (!task.owns(ticket)) return;
      task.report(error);
      // Only a definite rejection of the POST releases the original command.
      // A failed read after its receipt must keep read-only recovery available.
      if (!pending.receipt && error instanceof EditorialApiError && [400, 404, 409, 413, 415, 422].includes(error.status)) {
        setIntent(null); if ([404, 409].includes(error.status)) { setConflict(true); setReady(false); }
      }
    } finally { task.finish(ticket); }
  }
  const locked = task.busy || Boolean(intent) || Boolean(confirmation) || !ready || !canEdit || conflict || !editableAiDraft(head) || suggestion?.status !== "succeeded";
  return <div className="min-w-0 space-y-5 [overflow-wrap:anywhere]">
    <p>Ručno proverite i uredite ceo sadržaj. Prihvatanje stvara novu nepromenljivu verziju u stanju Uređivanje. Ne odobrava i ne objavljuje sadržaj; WordPress objavljivanje nije povezano.</p>
    {!canEdit ? <p role="alert">Prihvatanje zahteva Editor dozvolu i uključen PostgreSQL urednički servis.</p> : null}
    {task.busy ? <p role="status">Provera sa serverom…</p> : null}{task.error ? <p role="alert" className="text-rose-200">{task.error}</p> : null}
    {!ready && !intent && canEdit ? <Button type="button" variant="secondary" disabled={task.busy} onClick={() => void load()}>Proveri najnoviju reviziju</Button> : null}
    {suggestion ? <AiSuggestionComparison suggestion={suggestion} article={null} /> : null}
    {result ? <section aria-label="Potvrđeno AI prihvatanje" className="space-y-4">
      <p role="status">Server je potvrdio prihvatanje: verzija {result.receipt.version_number}, revizija {result.receipt.revision}. Prihvatanje nije dalo odobrenje.</p>
      <p>Trenutno sačuvano stanje: {statusText[result.head.status]}, revizija {result.head.revision}. Stanje pri poslednjem čitanju.</p>
      {result.head.revision > result.receipt.revision ? <p>Druga komanda je naknadno promenila nacrt. Ispod je tačna verzija ovog prihvatanja.</p> : null}
      <EditorialVersionContent version={result.version} label="Prihvaćena AI urednička verzija" />
      <Link className="inline-block font-semibold text-[#f5c518] underline" to={`/review/${storyId}/edit`}>Otvori sačuvani nacrt</Link>
    </section> : <>
      {suggestion && suggestion.status !== "succeeded" ? <p role="alert">Ovaj predlog nije dostupan za prihvatanje. Prihvaćene verzije proverite u istoriji nacrta.</p> : null}
      {ready ? <p>Očekivana revizija: {head?.revision ?? 0} · {head ? statusText[head.status] : "Novi nacrt"}. Prihvatanje koristi zamrznuti izvor ovog predloga.</p> : null}
      {head && !editableAiDraft(head) ? <p role="alert">Ovo stanje ne dozvoljava novu verziju. Završite pregled ili ponovo otvorite odbijeni nacrt kroz postojeći tok odluka.</p> : null}
      {head?.status === "approved" ? <p className="text-amber-100">Nova prihvaćena verzija poništava aktuelno odobrenje. Istorijske odluke ostaju sačuvane.</p> : null}
      {conflict ? <p role="alert">Sukob revizija ili promenjeno stanje predloga. Lokalni unos je sačuvan. Proverite najnoviju reviziju pre nove potvrde.</p> : null}
      {intent ? <section aria-label="Oporavak prihvatanja" className="space-y-3 rounded-xl border border-amber-300 p-4">
        <p>Ishod prihvatanja još nije potvrđen. Čuva se ista komanda i ceo potvrđeni sadržaj; nema automatskog ponavljanja.</p><p className="break-all">Komanda: {intent.command.command_id}</p>
        <Button type="button" disabled={task.busy} onClick={() => void execute(intent)}>{intent.receipt ? "Potvrdi prihvaćenu verziju čitanjem" : "Ponovi isto prihvatanje"}</Button>
      </section> : null}
      {form ? <form noValidate className="min-w-0 space-y-5 rounded-xl border border-white/20 p-4 sm:p-6" aria-label="Uređivanje AI predloga" onSubmit={event => { event.preventDefault(); prepare(); }}>
        <h3 className="text-xl font-bold">Urednički sadržaj za prihvatanje</h3>
        <p>Naslov, sažetak i telo potiču iz predloga. Ostala polja preuzimaju postojeći nacrt, ako postoji. Proverite sva polja i reference slika. Izvorna AI sugestija ostaje nepromenjena.</p>
        <p role="status">{dirty ? "Nesačuvane lokalne izmene." : "Nema dodatnih lokalnih izmena. Predlog još nije prihvaćen."}</p>
        <div ref={errorSummary} tabIndex={-1}>{Object.keys(errors).length ? <p role="alert">Proverite označena polja. Nijedna komanda nije poslata.</p> : null}</div>
        <EditorialFormFields form={form} errors={errors} readOnly={locked} sources={suggestion ? [suggestion.input.source] : []} onChange={next => { if (!locked && !task.isRunning() && suggestion) { setForm({ ...next, sources: frozenAttribution(suggestion.input.source) }); setErrors({}); } }} />
        <p className="break-all text-sm">Zaključana atribucija: članak {suggestion?.article_id} · portal {suggestion?.source_id}. Zamrznuti tekst, URL i vreme snimanja određuje server.</p>
        <Button ref={confirmationTrigger} type="submit" className="h-auto min-h-10 max-w-full whitespace-normal" disabled={locked}>Pregledaj i potvrdi prihvatanje</Button>
      </form> : null}
    </>}
    {confirmation ? <ConfirmDiscardDialog lang="sr-Latn" cancelFocusRef={confirmationTrigger} title="Prihvatiti u novu uredničku verziju?" message={`Priča: ${storyId}\nAI predlog: ${suggestionId}\nUlazni SHA-256: ${suggestion?.input_hash}\nIzlazni SHA-256: ${suggestion?.output_hash}\nOčekivana revizija: ${confirmation.command.expected_revision}; nova verzija: ${confirmation.versionNumber}.\nNaslov: ${confirmation.command.payload.headline}\nPotvrđujete ceo sadržaj iz forme i zamrznuti izvor ovog predloga. Nova verzija je u stanju Uređivanje, bez odobrenja. Prethodno aktuelno odobrenje prestaje da važi.`} confirmLabel="Prihvati u nacrt" cancelLabel="Odustani" onCancel={() => setConfirmation(null)} onConfirm={() => void execute(confirmation)} /> : null}
    {blocker.state === "blocked" ? <ConfirmDiscardDialog lang="sr-Latn" title="Napustiti AI uređivanje?" message="Lokalne izmene i podaci za oporavak komande postoje samo na ovoj stranici. Poslata komanda možda još završava na serveru. Zabeležite identifikator pre napuštanja i proverite istoriju pre nove komande." confirmLabel="Napusti stranicu" cancelLabel="Ostani" onCancel={() => blocker.reset()} onConfirm={() => blocker.proceed()} /> : null}
  </div>;
}
