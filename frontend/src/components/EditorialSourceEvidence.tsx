import { useState } from "react";
import { safeLink } from "../lib/editorialForm";
import { getEditorialStoryWorkspace } from "../services/newsService";
import type { EditorialStoryWorkspace } from "../types/news";
import type { SourceSnapshot, StorySource } from "../types/editorial";
import { Button } from "./ui/button";

function sourceKey(value: string | null) { return safeLink(value)?.replace(/\/$/, "") ?? null; }
function originalLink(value: string | null) { const href = safeLink(value); return href ? <a className="break-all font-semibold text-[#f5c518] underline" href={href} target="_blank" rel="noopener noreferrer">{value}</a> : <span>Original URL unavailable</span>; }
function date(value: string | null) { return value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : "Publication time unavailable"; }

export function EditorialSourceEvidence({ storyId, sources, frozen }: { storyId: string; sources: StorySource[]; frozen: SourceSnapshot[] }) {
  const [current, setCurrent] = useState<EditorialStoryWorkspace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const source = sources.find(row => row.article_id === selected) ?? sources[0];
  const matches = source && sourceKey(source.source_url) ? (current?.source_articles ?? []).filter(article => sourceKey(article.source_url) === sourceKey(source.source_url) && [source.original_url, source.canonical_url].some(url => safeLink(url) !== null && safeLink(url) === safeLink(article.url))) : [];
  return <div className="space-y-5">
    <section className="space-y-3 rounded-xl border border-white/20 bg-[#08245a] p-4" aria-label="Current collected source evidence">
      <h3 className="text-lg font-bold">Current collected material</h3>
      <p className="text-sm text-[#c2d3f5]">This material can change after recollection. Full text is shown only when it can be matched unambiguously to this portal and article.</p>
      {source ? <>
        <label className="block text-sm">Inspect current source<select value={source.article_id} className="mt-2 block w-full rounded-lg bg-[#071d49] p-2" onChange={event => setSelected(event.target.value)}>{sources.map(row => <option key={row.article_id} value={row.article_id}>{row.source_name} — {row.title || row.article_id}</option>)}</select></label>
        <p className="font-semibold">{source.source_name}</p>{originalLink(source.original_url)}<p className="text-xs text-[#c2d3f5]">Published: {date(source.published_at)}</p>
        <p className="whitespace-pre-wrap break-words text-sm">{source.excerpt || "No current excerpt is available."}</p>
        <Button type="button" variant="secondary" disabled={loading} onClick={async () => {
          setLoading(true); setError(false); setCurrent(null);
          try { const result = await getEditorialStoryWorkspace(storyId); if (!Array.isArray(result.source_articles) || result.source_articles.some(row => typeof row.url !== "string" || typeof row.source_url !== "string" || (row.content !== null && typeof row.content !== "string"))) throw new Error("Invalid source preview"); setCurrent(result); } catch { setError(true); } finally { setLoading(false); }
        }}>{loading ? "Loading current source text…" : "Load current source text"}</Button>
        {error ? <p role="alert">Current full text could not be loaded. The saved evidence is unchanged.</p> : null}
        {current ? <p className="whitespace-pre-wrap break-words text-sm">{matches.length === 1 ? matches[0].content || "Full current text is unavailable." : "A unique current article could not be matched. Use the excerpt or open the original."}</p> : null}
      </> : <p>No current source summaries are available.</p>}
    </section>
    <FrozenVersionEvidence sources={frozen} />
  </div>;
}

export function FrozenVersionEvidence({ sources, title = "Frozen evidence for the saved version", note = "Saving reuses existing selected snapshots. Selecting a new article captures its current input. Recollection does not rewrite this evidence.", emptyText = "Source snapshots will be captured only after the server creates the draft." }: { sources: SourceSnapshot[]; title?: string; note?: string; emptyText?: string }) {
  return <section className="space-y-3 rounded-xl border border-[#f5c518]/40 p-4" aria-label="Frozen saved source evidence">
      <h3 className="text-lg font-bold">{title}</h3>
      <p className="text-sm text-[#c2d3f5]">{note}</p>
      {sources.length ? sources.map(row => <details key={row.id} className="rounded-lg border border-white/20 p-3">
        <summary className="cursor-pointer font-semibold">{row.source_name} — captured {date(row.captured_at)}</summary>
        <div className="mt-3 space-y-3">{originalLink(row.original_url)}<p className="text-xs">Published: {date(row.published_at)}</p><p className="break-all text-xs text-[#c2d3f5]">Snapshot hash: {row.snapshot_hash}</p><pre className="whitespace-pre-wrap break-words font-sans text-sm">{row.input_text}</pre></div>
      </details>) : <p>{emptyText}</p>}
    </section>;
}
