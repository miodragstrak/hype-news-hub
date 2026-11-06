import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { EditorialPager } from "../components/EditorialPager";
import { Button } from "../components/ui/button";
import { useDemoData } from "../context/DemoDataContext";
import { useEditorialAccess } from "../context/EditorialAccessContext";
import { aiStatusText } from "../lib/aiSuggestions";
import { checkedPrivateQueue, collectionStatusText, queueErrorText } from "../lib/editorialQueue";
import { statusText } from "../lib/editorialWorkflow";
import { EditorialApiError, type EditorialApi } from "../services/editorialApi";
import type { PrivateEditorialQueue, PrivateQueueStory } from "../types/editorialQueue";

const date = (value: string | null) => value && Number.isFinite(Date.parse(value))
  ? new Date(value).toLocaleString("sr-Latn-RS", { dateStyle: "medium", timeStyle: "short" }) : "Datum nije dostupan";
const linkClass = "inline-block rounded-lg border border-white/25 px-3 py-2 text-sm font-semibold text-[#f5c518] underline focus-visible:ring-2 focus-visible:ring-[#f5c518]";

export function EditorialQueuePage() {
  const { isDemoMode } = useDemoData();
  const access = useEditorialAccess();
  if (isDemoMode) return <DemoQueue />;
  const readable = access.state === "ready" && access.capabilities?.permissions.includes("editorial:read") && access.client;
  return <section lang="sr-Latn" className="min-w-0 space-y-4">
    <header><h2 className="text-3xl font-bold">Urednički red</h2><p>Privatni pregled sačuvanih priča i uredničkog rada.</p></header>
    {readable && access.client ? <PrivateQueue client={access.client} key={access.sessionKey} /> : <div className="space-y-3 rounded-xl border border-white/25 p-4">
      <p role={access.state === "checking" ? "status" : "alert"}>{access.state === "checking" ? "Provera prijave i pristupa uredničkom redu…" :
        access.state === "unconfigured" ? "Privatni urednički red nije dostupan. Prijava nije podešena." :
        access.state === "signed_out" ? "Prijavite se za pregled privatnog uredničkog reda." :
        queueErrorText(access.state === "ready" ? new EditorialApiError(403, "Denied") : access.error)}</p>
      {access.state !== "checking" ? <Button type="button" onClick={access.refresh}>Ponovo proveri pristup</Button> : null}
      <p>Javno prikupljeni podaci i demo sadržaj nisu zamena za privatni red.</p>
      <Link className={linkClass} to="/collect">Prikupljanje i izvori</Link>
    </div>}
  </section>;
}

type ReadState = { owner: EditorialApi; key: string; response: PrivateEditorialQueue | null; error: unknown };
function PrivateQueue({ client }: { client: EditorialApi }) {
  const [page, setPage] = useState({ limit: 20, offset: 0 });
  const [reload, setReload] = useState(0);
  const [read, setRead] = useState<ReadState | null>(null);
  const key = `${page.limit}:${page.offset}:${reload}`;
  const current = read?.owner === client && read.key === key ? read : null;
  const response = current?.response ?? null, error = current?.error;
  const busy = !current;
  useEffect(() => {
    const controller = new AbortController();
    void client.queue(page.limit, page.offset, controller.signal).then(raw => {
      const response = checkedPrivateQueue(raw, page.limit, page.offset);
      if (!controller.signal.aborted) setRead({ owner: client, key, response, error: null });
    }).catch(error => {
      if (!controller.signal.aborted) setRead({ owner: client, key, response: null, error });
    });
    return () => controller.abort();
  }, [client, key, page.limit, page.offset]);
  return <div className="min-w-0 space-y-4" aria-label="Privatni urednički red">
    <p className="text-sm text-[#c2d3f5]">Najnovije priče prvo. Stanje je potvrđeno pri učitavanju; osvežite red za novije promene.</p>
    <Button type="button" variant="secondary" disabled={busy} onClick={() => setReload(value => value + 1)}>{error ? "Pokušaj ponovo" : "Osveži red"}</Button>
    {busy ? <p role="status">Učitavanje privatnog uredničkog reda…</p> : error ? <p role="alert">{queueErrorText(error)}</p> : null}
    {response ? <>
      <p>Ukupno sačuvanih priča: {response.stories_total}. Učitano na ovoj stranici: {response.stories.length}.</p>
      <EditorialPager {...page} count={response.stories.length} hasMore={response.has_more} busy={busy} label="Priča po stranici" onPage={(offset, limit) => setPage({ offset, limit })} />
      <QueueRows stories={response.stories} />
    </> : null}
  </div>;
}

function QueueRows({ stories, demo = false }: { stories: PrivateQueueStory[]; demo?: boolean }) {
  const [search, setSearch] = useState(""), [editorial, setEditorial] = useState("all"), [ai, setAi] = useState("all");
  const visible = stories.filter(row => row.headline.toLocaleLowerCase("sr-Latn").includes(search.toLocaleLowerCase("sr-Latn")) &&
    (editorial === "all" || (row.editorial?.status ?? "not_started") === editorial) &&
    (ai === "all" || (ai === "recovery" ? row.ai.recovery_required : (row.ai.status ?? "none") === ai)));
  return <div className="min-w-0 space-y-3 [overflow-wrap:anywhere]">
    <p className="text-sm">Pretraga i filteri važe samo za učitanu stranicu, ne za ceo arhiv.</p>
    <div className="grid min-w-0 gap-3 sm:grid-cols-3">
      <label>Pretraga naslova<input type="search" value={search} onChange={event => setSearch(event.target.value)} className="mt-1 w-full min-w-0 rounded-lg bg-[#08245a] p-3" /></label>
      {!demo ? <><label>Urednički status<select value={editorial} onChange={event => setEditorial(event.target.value)} className="mt-1 w-full min-w-0 rounded-lg bg-[#08245a] p-3"><option value="all">Svi urednički statusi</option><option value="not_started">Nije započeto</option>{Object.entries(statusText).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>
      <label>AI status<select value={ai} onChange={event => setAi(event.target.value)} className="mt-1 w-full min-w-0 rounded-lg bg-[#08245a] p-3"><option value="all">Svi AI statusi</option><option value="none">Nema AI predloga</option>{Object.entries(aiStatusText).map(([value, text]) => <option key={value} value={value}>{text}</option>)}<option value="recovery">Potreban oporavak</option></select></label></> : null}
    </div>
    <p role="status">Prikazano posle filtera: {visible.length} od {stories.length} priča na učitanoj stranici.</p>
    {!stories.length ? <p>Nema priča na ovoj stranici.</p> : !visible.length ? <p>Nema podudaranja na učitanoj stranici. Promenite filtere ili stranicu.</p> : <ul aria-label="Priče u uredničkom redu" className="space-y-2">{visible.map(row => <li key={row.id} className="grid min-w-0 gap-3 rounded-xl border border-white/20 bg-[#08245a]/60 p-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
      <div className="min-w-0"><h3 className="font-semibold"><Link className="underline focus-visible:ring-2 focus-visible:ring-[#f5c518]" to={`/review/${encodeURIComponent(row.id)}`}>{row.headline}</Link></h3><p className="text-sm">Objavljeno: {date(row.published_at)}</p><p className="text-sm">Izvori: {row.source_count} · Važnost: {row.importance_score}/100</p></div>
      <dl className="min-w-0 text-sm"><dt className="text-[#b7c9ee]">Prikupljanje</dt><dd>{collectionStatusText[row.status]}</dd><dt className="mt-1 text-[#b7c9ee]">Urednički rad</dt><dd>{demo ? "Demo — nije potvrđeno" : row.editorial ? statusText[row.editorial.status] : "Nije započeto"}</dd></dl>
      <div className="min-w-0 text-sm"><p className="text-[#b7c9ee]">AI obrada</p><p>{demo ? "Demo — nije potvrđeno" : row.ai.has_suggestion && row.ai.status ? aiStatusText[row.ai.status] : "Nema AI predloga"}</p>{!demo && row.ai.recovery_required ? <p className="mt-1 text-amber-200">Potreban oporavak — proverite AI radni prostor. Ova oznaka ne daje dozvolu za oporavak.</p> : null}{demo && row.article_count === 1 ? <p>No match yet</p> : null}</div>
      <nav aria-label={`Rad sa pričom: ${row.headline}`} className="flex flex-wrap items-start gap-2 md:flex-col"><Link className={linkClass} to={`/review/${encodeURIComponent(row.id)}`}>Pregled priče</Link>{!demo ? <Link className={linkClass} to={`/review/${encodeURIComponent(row.id)}/ai`}>AI radni prostor</Link> : null}</nav>
    </li>)}</ul>}
  </div>;
}
function DemoQueue() {
  const { editorialStories, editorialError, isLoadingEditorial } = useDemoData();
  const stories = [...editorialStories].sort((a, b) => b.importance_score - a.importance_score).map(row => ({ ...row, editorial: null,
    ai: { has_suggestion: false, latest_suggestion_id: null, status: null, created_at: null, completed_at: null, recovery_required: false } }));
  return <section lang="sr-Latn" className="min-w-0 space-y-4"><h2 className="text-3xl font-bold">Urednički red — demo</h2>
    <p role="note">Demonstracija sa primerima. Ovo nisu podaci privatnog produkcionog reda; urednički i AI statusi nisu potvrđeni.</p>
    {editorialError ? <p role="alert">Demo red nije dostupan.</p> : isLoadingEditorial ? <p role="status">Učitavanje demo reda…</p> : null}
    <QueueRows stories={stories} demo />
  </section>;
}
