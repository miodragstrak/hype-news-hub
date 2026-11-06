import { isUuid, safeLink } from "./editorialForm";
import { isHash } from "./editorialWorkflow";
import { EditorialApiError } from "../services/editorialApi";
import type { AiProvenance, AiStatus, AiSuggestion, AiSummary, CreateAiSuggestion } from "../types/ai";
import type { StorySource } from "../types/editorial";
import type { EditorialStoryWorkspace, SourceArticle } from "../types/news";

export const aiStatusText: Record<AiStatus, string> = { processing: "Obrada je u toku", succeeded: "Predlog je spreman za proveru", failed: "Obrada nije uspela", interrupted: "Obrada je prekinuta", rejected: "Odbijen AI predlog", accepted: "Prihvaćen u uredničku verziju" };
const invalid = () => new EditorialApiError(502, "Invalid AI workspace response.");
const nullableText = (value: unknown) => value === null || typeof value === "string";
function provenance(value: AiProvenance) {
  if (!value || !["mock", "gemini"].includes(value.provider) || value.is_mock !== (value.provider === "mock") || ![value.model, value.adapter_version].every(v => typeof v === "string" && v.length > 0)) throw invalid();
}
export function checkedAiSummary(value: AiSummary, storyId: string) {
  if (!value || ![value.id, value.article_id, value.source_id, value.command_id].every(isUuid) || value.story_id !== storyId || value.target_locale !== "sr-Latn" || value.mode !== "translation" || !Object.prototype.hasOwnProperty.call(aiStatusText, value.status) || !Number.isSafeInteger(value.revision) || value.revision < 1 || value.revision > 3 || !isHash(value.input_hash) || (value.output_hash !== null && !isHash(value.output_hash)) || !nullableText(value.error_code) || typeof value.recovery_required !== "boolean" || ![value.created_at, value.expires_at].every(v => typeof v === "string") || ![value.completed_at, value.rejected_at].every(nullableText)) throw invalid();
  provenance(value.provenance);
  return value;
}
export function checkedAiSummaries(rows: AiSummary[], storyId: string, limit: number) {
  if (!Array.isArray(rows) || rows.length > limit) throw invalid();
  rows.forEach(row => checkedAiSummary(row, storyId));
  if (new Set(rows.map(row => row.id)).size !== rows.length) throw invalid();
  return rows;
}
export function checkedAiSuggestion(value: AiSuggestion, storyId: string, expected?: Pick<AiSummary, "id" | "input_hash"> | CreateAiSuggestion) {
  checkedAiSummary(value, storyId);
  if (expected && ("id" in expected ? value.id !== expected.id || value.input_hash !== expected.input_hash : value.command_id !== expected.command_id || value.article_id !== expected.article_id || value.source_id !== expected.source_id)) throw invalid();
  const input = value.input, source = input?.source;
  if (!input || input.request_id !== value.id || input.story_id !== storyId || input.mode !== value.mode || input.target_locale !== value.target_locale || typeof input.prompt_version !== "string" || !source || source.article_id !== value.article_id || source.source_id !== value.source_id || !isHash(source.input_text_hash) || ![source.title, source.excerpt, source.input_text, source.source_name, source.original_url, source.source_url, source.captured_at].every(v => typeof v === "string") || ![source.content, source.external_id, source.canonical_url, source.language, source.source_language ?? null, source.published_at].every(nullableText) || !Array.isArray(value.events) || value.events.length > 3) throw invalid();
  if (value.recovery_command != null) {
    const command = value.recovery_command;
    const fields = ["command_id", "story_id", "article_id", "source_id", "target_locale", "mode"] as const;
    if (value.status !== "processing" || Object.keys(command).length !== fields.length || fields.some(field => command[field] !== value[field])) throw invalid();
  }
  const output = value.output;
  if (["succeeded", "accepted", "rejected"].includes(value.status)) {
    if (!output || ![output.headline, output.excerpt, output.body].every(v => typeof v === "string" && v.length > 0) || !Array.isArray(output.warnings) || !output.warnings.length || output.warnings.length > 10 || output.warnings.some(v => typeof v !== "string") || !Array.isArray(output.source_references) || output.source_references.length !== 1 || !value.output_hash) throw invalid();
    if (output.seo !== undefined && (!output.seo || typeof output.seo.title !== "string" || !output.seo.title || output.seo.title.length > 120 || typeof output.seo.description !== "string" || !output.seo.description || output.seo.description.length > 320)) throw invalid();
    provenance(output.provenance);
    if (["provider", "model", "is_mock", "adapter_version"].some(key => output.provenance[key as keyof AiProvenance] !== value.provenance[key as keyof AiProvenance])) throw invalid();
    const reference = output.source_references[0];
    if (!reference || reference.article_id !== source.article_id || reference.source_id !== source.source_id || reference.input_text_hash !== source.input_text_hash || typeof reference.excerpt !== "string" || !reference.excerpt || !source.input_text.includes(reference.excerpt)) throw invalid();
  } else if (output !== null) throw invalid();
  const meta = value.processing_metadata;
  const count = (v: unknown) => v === null || (typeof v === "number" && Number.isSafeInteger(v) && v >= 0);
  if (meta && (!count(meta.counted_input_tokens) || ![meta.model_metadata_version, meta.reported_model_version, meta.provider_response_id].every(nullableText) || meta.estimated_cost !== null || meta.cost_status !== "unknown" || (meta.usage !== null && (!meta.usage || ![meta.usage.prompt_tokens, meta.usage.output_tokens, meta.usage.thinking_tokens, meta.usage.cached_tokens, meta.usage.total_tokens].every(count))))) throw invalid();
  if (new TextEncoder().encode(JSON.stringify(value)).byteLength > 512 * 1024) throw invalid();
  return value;
}
export function checkedAiSources(rows: StorySource[]) {
  if (!Array.isArray(rows) || rows.length > 50 || rows.some(row => !row || !isUuid(row.article_id) || !isUuid(row.source_id) || ![row.source_name, row.title, row.excerpt].every(v => typeof v === "string") || ![row.source_url, row.original_url, row.canonical_url, row.published_at].every(nullableText)) || new Set(rows.map(row => row.article_id)).size !== rows.length) throw invalid();
  return rows;
}
export function checkedCollectedStory(value: EditorialStoryWorkspace, storyId: string) {
  if (!value || value.story_id !== storyId || typeof value.headline !== "string" || !Array.isArray(value.source_articles) || value.source_articles.some(row => !row || ![row.source, row.source_url, row.title, row.excerpt, row.url, row.external_id].every(v => typeof v === "string") || ![row.content, row.language, row.published_at].every(nullableText))) throw invalid();
  return value;
}
export function matchingCollectedSource(source: StorySource | undefined, articles: SourceArticle[]) {
  if (!source || !safeLink(source.source_url)) return null;
  const portal = safeLink(source.source_url)?.replace(/\/$/, "");
  const matches = articles.filter(article => safeLink(article.source_url)?.replace(/\/$/, "") === portal &&
    [source.original_url, source.canonical_url].some(url => Boolean(safeLink(url)) && safeLink(url) === safeLink(article.url)));
  return matches.length === 1 ? matches[0] : null;
}
export function aiErrorText(error: unknown) {
  const status = error instanceof EditorialApiError ? error.status : 0;
  return ({ 0: "Veza je prekinuta. Ishod generisanja nije potvrđen.", 401: "Prijava je istekla. Privatni sadržaj je uklonjen.", 403: "Nemate dozvolu za ovu AI operaciju. Privatni sadržaj je uklonjen.", 404: "Priča ili AI predlog nisu dostupni.", 409: "Komanda je u sukobu. Proverite postojeći predlog pre novog pokušaja.", 413: "Zahtev je prevelik.", 429: "Dnevni budžet AI obrade je dostignut. Novi zahtev nije poslat AI servisu.", 422: "Izvor ili odgovor nije podržan. Sadržaj nije skraćen.", 503: "AI servis nije dostupan ili nije podešen. Ishod generisanja nije potvrđen." } as Record<number, string>)[status] ?? "Server nije potvrdio AI zahtev. Nema automatskog ponavljanja.";
}

/** A persisted replay belongs only to the selected, validated processing detail. */
export function matchesSelectedAiRecovery(plan: { id: string | null; command: CreateAiSuggestion }, selectedId: string | null, detail: AiSuggestion | null): boolean {
  if (!plan.id || !detail || selectedId !== detail.id || plan.id !== detail.id || detail.status !== "processing" || !detail.recovery_command) return false;
  const fields = ["command_id", "story_id", "article_id", "source_id", "target_locale", "mode"] as const;
  return Boolean(plan.command) && Object.keys(plan.command).length === fields.length &&
    Object.keys(detail.recovery_command).length === fields.length && fields.every(field =>
    plan.command[field] === detail.recovery_command![field] && plan.command[field] === detail[field]);
}

/** Only authoritative, matching terminal history can resolve page-command uncertainty. */
export function reconcilePendingAiCommand<T extends { id: string | null; command: CreateAiSuggestion }>(pending: T | null, rows: readonly AiSummary[]): T | null {
  if (!pending) return pending;
  const fields = ["command_id", "story_id", "article_id", "source_id", "target_locale", "mode"] as const;
  const terminal: readonly AiStatus[] = ["succeeded", "failed", "interrupted", "rejected", "accepted"];
  return rows.some(row => (pending.id === null || pending.id === row.id) &&
    fields.every(field => pending.command[field] === row[field]) && terminal.includes(row.status)) ? null : pending;
}
