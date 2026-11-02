import type { AiSuggestion, AiSummary } from "../src/types/ai";
import type { EditorialStoryWorkspace } from "../src/types/news";
import { sourceRows, storyId, uuid } from "./editorialFixtures";

export const collectedWorkspace = (id = storyId): EditorialStoryWorkspace => ({ id: `editorial-${id}`, story_id: id, headline: "Sačuvana regionalna priča", target_language: "sr", target_language_label: "Serbian", status: "needs_generation", source_count: 2, source_languages: ["sl", "hr"], source_countries: ["SI", "HR"],
  source_articles: sourceRows.map((row, index) => ({ external_id: "7", source: row.source_name, source_url: row.source_url!, country: index ? "HR" : "SI", language: index ? "hr" : "sl", title: row.title, excerpt: row.excerpt, content: `CURRENT ORIGINAL ${index + 1} <script>unsafe()</script>`, featured_image: null, published_at: row.published_at, url: row.original_url!, categories: [] })),
  editorial_intelligence: { importance_score: 50, confidence_score: 50, coverage: "Regional", risk_level: "Low", recommended_action: "Manual Review", reason: "Fixture" }, serbian_draft: { headline: null, excerpt: null, content: null, status: "not_generated" }, processing_history: [] });
export function aiSuggestion(number = 1, changes: Partial<AiSummary> = {}): AiSuggestion {
  const row: AiSummary = { id: uuid(1000 + number), story_id: storyId, article_id: sourceRows[0].article_id, source_id: sourceRows[0].source_id, command_id: uuid(2000 + number), mode: "translation", target_locale: "sr-Latn", status: "succeeded", revision: 2,
    provenance: { provider: "gemini", model: "gemini-fixture-model", is_mock: false, adapter_version: "1" }, input_hash: "a".repeat(64), output_hash: "b".repeat(64), error_code: null,
    created_at: "2026-11-01T12:00:00Z", expires_at: "2026-11-01T12:00:35Z", completed_at: "2026-11-01T12:00:02Z", rejected_at: null, recovery_required: false, ...changes };
  const source = sourceRows.find(source => source.article_id === row.article_id)!;
  const input = { request_id: row.id, story_id: row.story_id, mode: row.mode, target_locale: row.target_locale, prompt_version: "sr-latn-translation-v1", source: {
    article_id: source.article_id, source_id: source.source_id, source_name: source.source_name, source_url: source.source_url!, external_id: "7", original_url: source.original_url!, canonical_url: null,
    language: "sl", source_language: null, published_at: source.published_at, title: `Frozen ${source.title}`, excerpt: "Zamrznuti sažetak izvora.", content: `SEALED ORIGINAL ${source.source_name}`, input_text: `Frozen ${source.title}\n\nZamrznuti sažetak izvora.\n\nSEALED ORIGINAL ${source.source_name}`, input_text_hash: "c".repeat(64), captured_at: row.created_at } };
  return { ...row, input, output: ["succeeded", "accepted", "rejected"].includes(row.status) ? { provenance: row.provenance, headline: `AI naslov ${number}`, excerpt: "AI sažetak za proveru.", body: `AI PRIVATE BODY ${number}`, warnings: ["Obavezna ljudska provera. Dokazi nisu nezavisno potvrđeni."], source_references: [{ article_id: row.article_id, source_id: row.source_id, input_text_hash: input.source.input_text_hash, excerpt: input.source.input_text }] } : null,
    actor_issuer: "urn:test", actor_subject: "editor", events: [], processing_metadata: { counted_input_tokens: 123, usage: { prompt_tokens: 123, output_tokens: 40, thinking_tokens: 0, cached_tokens: 0, total_tokens: 163 }, model_metadata_version: "001", reported_model_version: "gemini-fixture-version", provider_response_id: "fixture-response-id", http_attempts: 3, generation_attempts: 1, generation_outcome: "completed", evidence_sufficient: true, output_schema_version: 1, estimated_cost: null, pricing_provenance: null, cost_status: "unknown" } };
}
export function aiSummary(value: AiSuggestion): AiSummary {
  const { input: _input, output: _output, actor_issuer: _issuer, actor_subject: _subject, events: _events, processing_metadata: _metadata, ...summary } = value;
  return summary;
}
