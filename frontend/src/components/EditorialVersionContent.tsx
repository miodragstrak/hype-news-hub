import { readPublishingPayload, safeLink } from "../lib/editorialForm";
import type { EditorialVersion } from "../types/editorial";
import { FrozenVersionEvidence } from "./EditorialSourceEvidence";
export function EditorialVersionContent({ version, label }: { version: EditorialVersion; label: string }) {
  const payload = readPublishingPayload(version.payload);
  return <article aria-label={label} className="min-w-0 space-y-5 rounded-2xl border border-white/20 bg-[#08245a] p-5 sm:p-6">
    <header className="space-y-2"><h3 className="text-xl font-bold">{label} · v{version.version_number}</h3><p className="break-all text-xs text-[#c2d3f5]">ID: {version.id}<br />SHA-256: {version.content_hash}</p><p className="break-words text-sm">Autor: {version.actor_subject} · {version.actor_issuer}<br /><time dateTime={version.created_at}>{version.created_at}</time> · {version.origin} · šema {version.payload_schema_version}</p></header>
    {payload ? <>
      <h4 className="break-words text-2xl font-bold">{payload.headline}</h4><p className="whitespace-pre-wrap break-words">{payload.excerpt}</p><div className="whitespace-pre-wrap break-words leading-7">{payload.body}</div>
      <dl className="space-y-2 text-sm"><div><dt className="font-bold">Slug</dt><dd className="break-all">{payload.slug}</dd></div><div><dt className="font-bold">Kategorije</dt><dd><ul>{payload.categories.map((value, index) => <li className="whitespace-pre-wrap break-words" key={index}>{value}</li>)}</ul></dd></div><div><dt className="font-bold">Oznake</dt><dd><ul>{payload.tags.map((value, index) => <li className="whitespace-pre-wrap break-words" key={index}>{value}</li>)}</ul></dd></div><div><dt className="font-bold">SEO naslov</dt><dd className="whitespace-pre-wrap break-words">{payload.seo.title}</dd></div><div><dt className="font-bold">SEO opis</dt><dd className="whitespace-pre-wrap break-words">{payload.seo.description}</dd></div></dl>
      <section className="space-y-2"><h4 className="font-bold">Reference slika</h4>{payload.images.length ? payload.images.map((row, index) => <div className="break-words text-sm" key={index}>{index === 0 ? "Naslovna slika" : `Slika ${index + 1}`}: {safeLink(row.url) ? <a className="break-all text-[#f5c518] underline" href={safeLink(row.url)!} target="_blank" rel="noopener noreferrer">{row.url}</a> : "URL nije podržan"}<p>{row.alt} · {row.credit}</p><p className="break-all">Izvor članka: {row.source_article_id}</p></div>) : <p>Nema referenci slika.</p>}</section>
      <details><summary className="cursor-pointer text-[#f5c518]">Identifikatori atribucije</summary><pre className="whitespace-pre-wrap break-all text-xs">{JSON.stringify(payload.source_attribution, null, 2)}</pre></details>
    </> : <div><p>Starija šema sadržaja: prikaz je samo za čitanje.</p><pre className="whitespace-pre-wrap break-words text-sm">{JSON.stringify(version.payload, null, 2)}</pre></div>}
    <FrozenVersionEvidence sources={version.sources} title="Zamrznuti izvori ove verzije" note="Ovo je tačan sačuvan ulaz ove verzije. Trenutno prikupljeni članci ga ne zamenjuju." emptyText="Za ovu verziju nema zamrznutih izvora." />
  </article>;
}
