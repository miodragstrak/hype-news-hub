import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useBeforeUnload, useBlocker, useParams } from "react-router-dom";
import { AiSuggestionComparison, aiDate } from "../components/AiSuggestionComparison";
import { ConfirmDiscardDialog } from "../components/ConfirmDiscardDialog";
import { EditorialPager } from "../components/EditorialPager";
import { EditorialPrivatePage, type PrivatePageAccess } from "../components/EditorialPrivatePage";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { useEditorialTask } from "../hooks/useEditorialTask";
import { aiErrorText, aiStatusText, checkedAiSources, checkedAiSuggestion, checkedAiSummaries, checkedCollectedStory, matchingCollectedSource } from "../lib/aiSuggestions";
import { newCommandId } from "../lib/editorialForm";
import { checkedHead, statusText } from "../lib/editorialWorkflow";
import { EditorialApiError } from "../services/editorialApi";
import type { AiSuggestion, AiSummary, CreateAiSuggestion } from "../types/ai";
import type { DraftStatus, StorySource } from "../types/editorial";
import type { EditorialStoryWorkspace } from "../types/news";

type Intent = { command: CreateAiSuggestion; id: string | null };
export function EditorialAiPage() {
  const { storyId = "" } = useParams();
  return <EditorialPrivatePage storyId={storyId} title="AI urednički predlozi">{access => <AiWorkspace storyId={storyId} {...access} />}</EditorialPrivatePage>;
}
function AiWorkspace({ storyId, client, capabilities, onDenied }: PrivatePageAccess & { storyId: string }) {
  const task = useEditorialTask(onDenied);
  const [loaded, setLoaded] = useState(false);
  const [workspace, setWorkspace] = useState<EditorialStoryWorkspace | null>(null);
  const [draftStatus, setDraftStatus] = useState<DraftStatus | null>(null);
  const [draftKnown, setDraftKnown] = useState(false);
  const [contextReady, setContextReady] = useState(false);
  const [contextLoading, setContextLoading] = useState(true);
  const [warnings, setWarnings] = useState<string[]>([]);
  const contextController = useRef<AbortController | null>(null);
  const contextBusy = useRef(true);
  const [sources, setSources] = useState<StorySource[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [sourceMore, setSourceMore] = useState(false);
  const [rows, setRows] = useState<AiSummary[]>([]);
  const [page, setPage] = useState({ offset: 0, limit: 20 });
  const [detail, setDetail] = useState<AiSuggestion | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [intent, setIntent] = useState<Intent | null>(null);
  const [retryOpen, setRetryOpen] = useState(false);
  const canEdit = capabilities.commands_enabled && capabilities.permissions.includes("editorial:edit");
  const canRecover = canEdit && loaded && contextReady;
  const canGenerate = canRecover && capabilities.ai_generation_enabled === true;
  const blocker = useBlocker(Boolean(intent));
  useBeforeUnload(useCallback((event: BeforeUnloadEvent) => { if (intent) { event.preventDefault(); event.returnValue = ""; } }, [intent]));
  function report(reason: unknown) {
    setError(aiErrorText(reason));
    if (reason instanceof EditorialApiError && [401, 403].includes(reason.status)) { contextController.current?.abort(); task.report(reason); }
  }
  async function load() {
    const ticket = task.begin(); if (!ticket) return;
    setError(null);
    try {
      const history = checkedAiSummaries(await client.aiSuggestions(storyId, 20, 0, ticket.signal), storyId, 20);
      if (task.owns(ticket)) { setRows(history); setPage({ offset: 0, limit: 20 }); setLoaded(true); }
    } catch (reason) { if (task.owns(ticket)) report(reason); }
    finally { task.finish(ticket); }
  }
  useEffect(() => { void load(); }, [client, storyId]);
  async function loadContext() {
    contextController.current?.abort();
    const abort = new AbortController(); contextController.current = abort;
    contextBusy.current = true; setContextLoading(true); setContextReady(false); setWarnings([]);
    const owns = () => contextController.current === abort && !abort.signal.aborted;
    // Optional reads must never gate history. Auth failures still invalidate all
    // private operations immediately, including a concurrently loaded history.
    const checked = <T,>(request: Promise<T>) => request.catch(reason => {
      if (owns() && reason instanceof EditorialApiError && [401, 403].includes(reason.status)) report(reason);
      throw reason;
    });
    const [material, sourceRows, head] = await Promise.allSettled([
      checked(client.collectedStory(storyId, abort.signal).then(value => checkedCollectedStory(value, storyId))),
      checked(client.sources(storyId, 0, abort.signal).then(checkedAiSources)),
      checked(client.find(storyId, abort.signal).then(value => checkedHead(value, storyId)).catch(reason => {
        if (reason instanceof EditorialApiError && reason.status === 404) return null; throw reason;
      })),
    ]);
    if (!owns()) return;
    const notes: string[] = [];
    setWorkspace(material.status === "fulfilled" ? material.value : null);
    if (material.status === "rejected") notes.push("Trenutni izvorni materijal nije dostupan.");
    const nextSources = sourceRows.status === "fulfilled" ? sourceRows.value : [];
    setSources(nextSources); setSourceMore(nextSources.length === 50);
    setSourceId(previous => nextSources.some(row => row.article_id === previous) ? previous : nextSources[0]?.article_id ?? "");
    if (sourceRows.status === "rejected") notes.push("Spisak trenutnih izvora nije dostupan.");
    setDraftKnown(head.status === "fulfilled"); setDraftStatus(head.status === "fulfilled" ? head.value?.status ?? null : null);
    if (head.status === "rejected") notes.push("Urednički status nije dostupan.");
    setWarnings(notes); setContextReady(notes.length === 0); setContextLoading(false); contextBusy.current = false;
  }
  useEffect(() => { void loadContext(); return () => contextController.current?.abort(); }, [client, storyId]);
  function receive(value: AiSuggestion, command?: CreateAiSuggestion) {
    setDetail(value); setSelectedId(value.id);
    setRows(previous => previous.map(row => row.id === value.id ? value : row));
    if (command) setIntent(value.status === "processing" ? { command, id: value.id } : null);
    else if (intent && intent.command.command_id === value.command_id) setIntent(value.status === "processing" ? { ...intent, id: value.id } : null);
  }
  async function history(offset: number, limit: number) {
    const ticket = task.begin(); if (!ticket) return;
    setError(null); setDetail(null); setSelectedId(null);
    try {
      const next = checkedAiSummaries(await client.aiSuggestions(storyId, limit, offset, ticket.signal), storyId, limit);
      if (task.owns(ticket)) { setRows(next); setPage({ offset, limit }); }
    } catch (reason) { if (task.owns(ticket)) report(reason); }
    finally { task.finish(ticket); }
  }
  async function inspect(row: AiSummary) {
    const ticket = task.begin(); if (!ticket) return;
    setError(null); setSelectedId(row.id); setDetail(null);
    try { const value = checkedAiSuggestion(await client.aiSuggestion(row.id, ticket.signal), storyId, row); if (task.owns(ticket)) receive(value); }
    catch (reason) { if (task.owns(ticket)) report(reason); }
    finally { task.finish(ticket); }
  }
  async function generate(plan?: Intent) {
    if (!(plan ? canRecover : canGenerate) || contextBusy.current || task.isRunning() || (!plan && intent)) return;
    const source = sources.find(row => row.article_id === sourceId);
    if (!plan && !source) return;
    const ticket = task.begin(); if (!ticket) return;
    setRetryOpen(false); setError(null);
    let pending = plan;
    let acknowledged = false;
    try {
      pending ??= { id: null, command: { command_id: newCommandId(), story_id: storyId, article_id: source!.article_id, source_id: source!.source_id, mode: "translation", target_locale: "sr-Latn" } };
      setIntent(pending); setDetail(null); setSelectedId(null);
      const value = checkedAiSuggestion(await client.generateAiSuggestion(pending.command, ticket.signal), storyId, pending.command);
      if (!task.owns(ticket)) return;
      receive(value, pending.command);
      acknowledged = true;
      // Keep a confirmed detail even if refreshing the summary list fails.
      const next = checkedAiSummaries(await client.aiSuggestions(storyId, page.limit, 0, ticket.signal), storyId, page.limit);
      if (task.owns(ticket)) { setRows(next); setPage(previous => ({ ...previous, offset: 0 })); }
    } catch (reason) {
      if (!task.owns(ticket)) return;
      if (!acknowledged && reason instanceof EditorialApiError && [400, 413, 415, 422, 429].includes(reason.status)) setIntent(null);
      report(reason);
    } finally { task.finish(ticket); }
  }
  const source = sources.find(row => row.article_id === sourceId);
  const article = matchingCollectedSource(source, workspace?.source_articles ?? []);
  return <div className="min-w-0 space-y-5 [overflow-wrap:anywhere]">
    <p>Jedan izvor · prevod na srpsku latinicu (sr-Latn). AI izlaz je predlog za ljudsku proveru; ne prihvata se, ne odobrava i ne objavljuje automatski.</p>
    {task.busy ? <p role="status">Zahtev je u toku… Nemojte pokretati novu obradu.</p> : null}
    {error ? <p role="alert" className="rounded-xl border border-rose-300 p-4 text-rose-100">{error}</p> : null}
    {!loaded ? <><p>{task.busy ? "Učitavanje privatnog AI radnog prostora…" : "AI radni prostor nije učitan."}</p><Button type="button" variant="secondary" disabled={task.busy} onClick={() => void load()}>Ponovo učitaj radni prostor</Button></> : <>
      <Card><CardContent className="space-y-3 p-4 sm:p-6">
        <h3 className="text-2xl font-bold">{workspace?.headline ?? `Priča ${storyId}`}</h3>
        <p>Urednički status: {!draftKnown ? "Nije potvrđen" : draftStatus ? statusText[draftStatus] : "Nema sačuvanog uredničkog nacrta"}. Stanje pri učitavanju; generisanje ga ne menja.</p>
        {contextLoading ? <p role="status">Provera konteksta priče… Istorija ostaje dostupna; generisanje je onemogućeno.</p> : null}
        {warnings.length ? <aside aria-label="Nedostupan kontekst priče" className="space-y-2 rounded-xl border border-amber-300 p-3 text-amber-100"><ul className="list-disc pl-5">{warnings.map(note => <li key={note}>{note}</li>)}</ul><p>Istorija i zamrznuti dokazi ostaju dostupni. Generisanje je onemogućeno dok se kontekst ne potvrdi.</p></aside> : null}
        {warnings.length ? <Button type="button" variant="secondary" className="h-auto min-h-10 whitespace-normal" disabled={task.busy || contextLoading || Boolean(intent)} onClick={() => { if (!task.isRunning() && !contextBusy.current && !intent) void loadContext(); }}>Ponovo učitaj kontekst priče</Button> : null}
        <p className="text-sm text-[#c2d3f5]">Izaberite jedan trajno sačuvani članak. Podešavanje i izbor AI providera obavlja server. Obrada može imati trošak.</p>
        {sources.length ? <label className="block font-semibold">Izvor za novu obradu<select className="mt-2 block w-full min-w-0 rounded-xl bg-[#071d49] p-3 text-sm" value={sourceId} disabled={task.busy || contextLoading || Boolean(intent)} onChange={event => { if (!task.isRunning() && !contextBusy.current && !intent) { setSourceId(event.target.value); setDetail(null); setSelectedId(null); setError(null); } }}>{sources.map(row => <option key={row.article_id} value={row.article_id}>{row.source_name} — {row.title}</option>)}</select></label> : !contextLoading ? <p>Nema potvrđenog spiska izvora za novu obradu.</p> : null}
        {source ? <p className="text-sm">{source.source_name} · {source.title} · Objavljeno: {aiDate(source.published_at)}</p> : null}
        {detail ? <p className="text-sm text-[#c2d3f5]">Istorijski prikaz ne menja izvor za novu obradu. Nova obrada koristi članak iz gornjeg izbora.</p> : null}
        {sourceMore ? <Button type="button" variant="secondary" disabled={task.busy || contextLoading || Boolean(intent)} onClick={async () => {
          if (contextBusy.current || intent) return;
          const ticket = task.begin(); if (!ticket) return;
          try { const next = checkedAiSources(await client.sources(storyId, sources.length, ticket.signal)); if (task.owns(ticket)) { setSources(previous => [...previous, ...next.filter(row => !previous.some(old => old.article_id === row.article_id))]); setSourceMore(next.length === 50); } }
          catch (reason) { if (task.owns(ticket)) report(reason); } finally { task.finish(ticket); }
        }}>Učitaj još izvora</Button> : null}
        {capabilities.ai_generation_enabled !== true ? <p>AI generisanje nije uključeno. Sačuvani predlozi ostaju dostupni; nema zamenskog demo izlaza.</p> : null}
        {!canEdit ? <p>Pregled je dostupan. Generisanje zahteva Editor dozvolu i uključen urednički servis.</p> : null}
        <Button type="button" className="h-auto min-h-10 max-w-full whitespace-normal" disabled={!canGenerate || task.busy || Boolean(intent) || !source} onClick={() => void generate()}>Generiši AI predlog</Button>
      </CardContent></Card>
      {intent ? <section aria-label="Oporavak AI komande" className="space-y-3 rounded-xl border border-amber-300 p-4">
        <h3 className="font-bold">{intent.id ? "Postojeća obrada još nije završena" : "Ishod komande nije potvrđen"}</h3>
        <p className="text-sm">Komanda: <span className="break-all">{intent.command.command_id}</span>. Nova komanda je blokirana. Nema automatskog ponavljanja. Proverite istoriju ili eksplicitno pošaljite istu komandu radi oporavka.</p>
        <Button type="button" variant="secondary" className="h-auto min-h-10 whitespace-normal" disabled={task.busy || !canRecover} onClick={() => setRetryOpen(true)}>Oporavi istu komandu</Button>
      </section> : null}
      <AiSuggestionComparison suggestion={detail} source={source} article={article} />
      {canEdit && contextReady && detail?.status === "succeeded" && !task.busy && !intent ? <Link className="inline-block rounded-xl border border-[#f5c518] px-4 py-3 font-semibold text-[#f5c518] underline" to={`/review/${storyId}/ai/${detail.id}/edit`}>Uredi i pripremi prihvatanje</Link> : null}
      <section aria-label="Istorija AI predloga" className="space-y-4 rounded-xl border border-white/20 p-4 sm:p-6">
        <h3 className="text-xl font-bold">Prethodni AI predlozi ove priče</h3><p className="text-sm text-[#c2d3f5]">Lista učitava metapodatke. Tekst i zamrznuti dokazi učitavaju se tek izborom predloga.</p>
        <EditorialPager {...page} count={rows.length} busy={task.busy} onPage={(offset, limit) => void history(offset, limit)} label="AI predloga po stranici" />
        {!rows.length ? <p>Nema AI predloga na ovoj stranici.</p> : <ul className="space-y-3">{rows.map(row => <li key={row.id} className="space-y-2 rounded-xl border border-white/20 p-3">
          <p className="font-semibold">{aiStatusText[row.status]}</p><p className="text-sm">{row.provenance.is_mock ? "MOCK / DEMO" : row.provenance.provider} · {row.provenance.model} · {aiDate(row.created_at)}</p><p className="break-all text-xs">Predlog: {row.id} · Članak: {row.article_id}</p>
          <Button type="button" variant="secondary" disabled={task.busy} aria-pressed={selectedId === row.id} onClick={() => void inspect(row)}>Prikaži predlog {row.id.slice(0, 8)}…{row.id.slice(-4)}</Button>
        </li>)}</ul>}
        <Button type="button" variant="secondary" disabled={task.busy} onClick={() => void history(page.offset, page.limit)}>Osveži istoriju AI predloga</Button>
      </section>
    </>}
    {retryOpen && intent ? <ConfirmDiscardDialog lang="sr-Latn" title="Oporaviti istu AI komandu?" message={`Komanda ${intent.command.command_id} koristi isti izvor i isti identifikator. Ako je server već primio zahtev, neće ponovo generisati. Ako zahtev nikada nije stigao, obrada može početi sada i imati trošak. Posle neizvesnog ishoda ne pravite novu komandu.`} confirmLabel="Pošalji istu komandu" cancelLabel="Odustani" onCancel={() => setRetryOpen(false)} onConfirm={() => void generate(intent)} /> : null}
    {blocker.state === "blocked" ? <ConfirmDiscardDialog lang="sr-Latn" title="Napustiti nepotvrđenu AI obradu?" message={`Komanda ${intent?.command.command_id ?? ""} može nastaviti na serveru. Napuštanje uklanja lokalne podatke za oporavak. Zabeležite identifikator i kasnije proverite istoriju; ne pokrećite naslepo novu obradu.`} confirmLabel="Napusti prikaz" cancelLabel="Ostani" onCancel={() => blocker.reset()} onConfirm={() => blocker.proceed()} /> : null}
  </div>;
}
