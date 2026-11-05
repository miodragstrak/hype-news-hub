import type { EditorialReceipt, PublishingPayload } from "./editorial";

/** Private Sprint 17B contracts. Provider selection and credentials are server-owned. */
export type CreateAiSuggestion = { command_id: string; story_id: string; article_id: string; source_id: string; target_locale: "sr-Latn"; mode: "translation" };
export type AcceptAiSuggestion = { command_id: string; story_id: string; expected_revision: number; payload: PublishingPayload; confirm_acceptance: true };
export type AiStatus = "processing" | "succeeded" | "failed" | "interrupted" | "rejected" | "accepted";
export type AiProvenance = { provider: "mock" | "gemini"; model: string; adapter_version: string; is_mock: boolean };
export type AiSource = {
  article_id: string; source_id: string; source_name: string; source_url: string; external_id: string | null;
  original_url: string; canonical_url: string | null; language: string | null; source_language?: string | null;
  published_at: string | null; title: string; excerpt: string; content: string | null;
  input_text: string; input_text_hash: string; captured_at: string;
};
export type AiReference = { article_id: string; source_id: string; input_text_hash: string; excerpt: string };
export type AiOutput = { provenance: AiProvenance; headline: string; excerpt: string; body: string; seo?: { title: string; description: string }; source_references: AiReference[]; warnings: string[] };
export type AiMetadata = {
  counted_input_tokens: number | null;
  usage: { prompt_tokens: number | null; output_tokens: number | null; thinking_tokens: number | null; cached_tokens: number | null; total_tokens: number | null } | null;
  model_metadata_version: string | null; reported_model_version: string | null; provider_response_id: string | null;
  http_attempts: number; generation_attempts: number; generation_outcome: "not_started" | "rejected" | "completed" | "unknown";
  evidence_sufficient: boolean | null; output_schema_version: 1 | 2; estimated_cost: null; pricing_provenance: null; cost_status: "unknown";
};
export type AiSummary = {
  id: string; story_id: string; article_id: string; source_id: string; command_id: string;
  target_locale: "sr-Latn"; mode: "translation"; status: AiStatus; revision: number; provenance: AiProvenance;
  input_hash: string; output_hash: string | null; error_code: string | null;
  created_at: string; expires_at: string; completed_at: string | null; rejected_at: string | null; recovery_required: boolean;
};
export type AiSuggestion = AiSummary & {
  input: { request_id: string; story_id: string; mode: "translation"; target_locale: "sr-Latn"; prompt_version: string; source: AiSource;
    instructions?: string | null; response_schema?: string | null;
    generation_settings?: { max_input_tokens: number; max_output_tokens: number; output_schema_version: 1 | 2 } | null };
  output: AiOutput | null; actor_issuer: string; actor_subject: string;
  events: { revision: number; action: string; status: AiStatus; command_id: string | null; actor_issuer: string; actor_subject: string;
    reason: string | null; occurred_at: string; result?: EditorialReceipt | null }[];
  processing_metadata?: AiMetadata | null;
};
