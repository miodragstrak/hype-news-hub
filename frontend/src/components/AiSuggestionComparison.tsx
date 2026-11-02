import { safeLink } from "../lib/editorialForm";
import { aiStatusText } from "../lib/aiSuggestions";
import type { AiSource, AiSuggestion } from "../types/ai";
import type { StorySource } from "../types/editorial";
import type { SourceArticle } from "../types/news";
import { Card, CardContent } from "./ui/card";

export function aiDate(value: string | null) { return value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("sr-Latn-RS") : "Datum nije dostupan"; }
function OriginalLink({ url }: { url: string | null }) {
  const href = safeLink(url);
  return href ? <a href={href} target="_blank" rel="noopener noreferrer" className="break-all text-[#f5c518] underline">{url}</a> : <span>Bez podržanog izvornog URL-a</span>;
}
export function AiSuggestionComparison({ suggestion, source, article }: { suggestion: AiSuggestion | null; source?: StorySource; article: SourceArticle | null }) {
  const frozen: AiSource | undefined = suggestion?.input.source;
  const evidence = frozen ?? article;
  const metadata = suggestion?.processing_metadata;
  return <div data-testid="ai-comparison" className="grid min-w-0 gap-5 lg:grid-cols-2">
    <Card className="min-w-0"><CardContent className="space-y-4 p-4 sm:p-6">
      <h3 className="text-xl font-bold">{frozen ? "Zamrznuti izvor AI predloga" : "Trenutni prikupljeni izvor"}</h3>
      <p className="text-sm text-[#c2d3f5]">{frozen ? "Tačan ulaz ove obrade. Ponovno prikupljanje ne menja ovaj snimak. Ovo nije urednička verzija." : "Prikupljeni materijal može se promeniti. Generisanje na serveru beleži zaseban zamrznuti snimak."}</p>
      {source || frozen ? <>
        <p className="font-semibold">{frozen?.source_name ?? source?.source_name}</p>
        <h4 className="font-bold">{evidence?.title ?? source?.title}</h4>
        <OriginalLink url={frozen?.original_url ?? source?.original_url ?? null} />
        <p className="text-sm">Objavljeno: {aiDate(frozen ? frozen.published_at : article?.published_at ?? source?.published_at ?? null)}</p>
        <p className="text-sm">Jezik izvora: {frozen ? frozen.language ?? frozen.source_language ?? "Nije zabeležen" : article?.language ?? "Nije zabeležen"}</p>
        <p className="whitespace-pre-wrap text-sm">{evidence?.excerpt ?? source?.excerpt}</p>
        <div role="region" aria-label="Originalni tekst izvora" tabIndex={0} className="max-h-[65vh] overflow-y-auto whitespace-pre-wrap rounded-xl border border-white/20 p-4 text-sm focus:ring-2 focus:ring-[#f5c518]">{evidence?.content ?? "Pun tekst nije jednoznačno dostupan. Pročitajte izvorni članak; sažetak nije ceo članak."}</div>
        <details className="text-xs"><summary className="cursor-pointer text-[#f5c518]">Identitet i poreklo izvora</summary><div className="mt-2 space-y-2 break-all">
          <p>Članak UUID: {frozen?.article_id ?? source?.article_id}</p><p>Portal UUID: {frozen?.source_id ?? source?.source_id}</p>
          <p>Izvorni ID: {(frozen ? frozen.external_id : source?.external_id) ?? "Nije dostupan"}</p>
          {frozen ? <><p>Snimljeno: {aiDate(frozen.captured_at)}</p><p>SHA-256 ulaznog teksta: {frozen.input_text_hash}</p><pre className="max-h-[65vh] overflow-y-auto whitespace-pre-wrap font-sans" tabIndex={0} aria-label="Tačan zamrznuti ulaz">{frozen.input_text}</pre></> : null}
        </div></details>
      </> : <p>Izaberite sačuvani izvor priče.</p>}
    </CardContent></Card>
    <Card className="min-w-0"><CardContent className="space-y-4 p-4 sm:p-6">
      <h3 className="text-xl font-bold">AI predlog — nije odobreni sadržaj</h3>
      <p className="text-sm text-[#c2d3f5]">Predlog ne menja sačuvani nacrt ili odluke. Prihvatanje, uređivanje i objavljivanje nisu dostupni u ovom prikazu.</p>
      {suggestion ? <>
        <p role="status" className="font-semibold text-[#f5c518]">{aiStatusText[suggestion.status]}</p>
        <p className="text-sm">Provider: {suggestion.provenance.provider} · Model: {suggestion.provenance.model} · Adapter: {suggestion.provenance.adapter_version}</p>
        {suggestion.provenance.is_mock ? <p className="rounded-xl border border-amber-300 p-3 text-amber-100">DEMO / MOCK: nije stvarni prevod niti proverena vest.</p> : null}
        {suggestion.error_code ? <p role="alert">Kod greške obrade: {suggestion.error_code}. Nema automatskog ponavljanja.</p> : null}
        {suggestion.recovery_required ? <p className="text-amber-100">Rezervacija je istekla. Ponovljena ista komanda beleži prekid; ne pokreće novu obradu.</p> : null}
        {suggestion.output ? <>
          <article aria-label="Sadržaj AI predloga" className="space-y-4"><h4 className="text-xl font-bold">{suggestion.output.headline}</h4><p className="whitespace-pre-wrap">{suggestion.output.excerpt}</p>
            <div role="region" aria-label="Tekst AI predloga" tabIndex={0} className="max-h-[65vh] overflow-y-auto whitespace-pre-wrap rounded-xl border border-white/20 p-4 focus:ring-2 focus:ring-[#f5c518]">{suggestion.output.body}</div>
          </article>
          <section aria-label="Upozorenja AI obrade"><h4 className="font-bold text-amber-100">Upozorenja — obavezna urednička provera</h4><ul className="list-disc space-y-2 pl-5 text-sm">{suggestion.output.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></section>
          <details><summary className="cursor-pointer font-semibold text-[#f5c518]">Reference na zamrznute dokaze</summary>{suggestion.output.source_references.map(reference => <div key={reference.article_id} className="mt-3 space-y-2 text-sm"><p className="break-all">Članak: {reference.article_id} · Portal: {reference.source_id}</p><p className="break-all">SHA-256: {reference.input_text_hash}</p><blockquote className="whitespace-pre-wrap border-l-2 border-[#f5c518] pl-3">{reference.excerpt}</blockquote></div>)}</details>
        </> : <p>Za ovu obradu nema potvrđenog izlaznog teksta.</p>}
        <details className="text-xs"><summary className="cursor-pointer text-[#f5c518]">Metapodaci obrade</summary><div className="mt-2 space-y-2 break-all">
          <p>Predlog: {suggestion.id}</p><p>Komanda: {suggestion.command_id}</p><p>Snimljeno: {aiDate(suggestion.created_at)}</p>
          <p>Ulazni hash: {suggestion.input_hash}</p><p>Izlazni hash: {suggestion.output_hash ?? "Nije dostupan"}</p><p>Prompt: {suggestion.input.prompt_version}</p>
          <p>Verzija modela: {metadata?.reported_model_version ?? "Nije prijavljena"}</p><p>ID odgovora: {metadata?.provider_response_id ?? "Nije prijavljen"}</p>
          <p>Prebrojani ulazni tokeni: {metadata?.counted_input_tokens ?? "Nepoznato"}</p><p>Ulaz / izlaz / razmišljanje / keš / ukupno: {metadata?.usage ? [metadata.usage.prompt_tokens, metadata.usage.output_tokens, metadata.usage.thinking_tokens, metadata.usage.cached_tokens, metadata.usage.total_tokens].map(value => value ?? "?").join(" / ") : "Nepoznato"}</p>
          <p>Trošak: nepoznat. Tokeni nisu račun.</p>
        </div></details>
      </> : <p>Izaberite postojeći predlog ili eksplicitno pokrenite jednu obradu.</p>}
    </CardContent></Card>
  </div>;
}
