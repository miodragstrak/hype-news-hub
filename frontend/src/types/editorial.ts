/** Private FastAPI editorial schemas; public aggregation types remain separate. */
export type EditorialPermission = "editorial:read" | "editorial:edit" | "editorial:submit" | "editorial:review" | "editorial:deliver" | "editorial:administer";
export type EditorialRole = "reader" | "editor" | "reviewer" | "publisher" | "administrator";
export type EditorialCapabilities = { roles: EditorialRole[]; permissions: EditorialPermission[]; storage: "postgres"; commands_enabled: boolean };
export type Attribution = { article_id: string; source_id: string };
export type EditorialImage = { url: string; alt: string; credit: string; source_article_id: string };
export type PublishingPayload = {
  headline: string; body: string; excerpt: string; slug: string; categories: string[]; tags: string[];
  seo: { title: string; description: string }; images: EditorialImage[]; source_attribution: Attribution[];
};
export type StorySource = Attribution & {
  source_name: string; source_url: string | null; external_id: string | null; original_url: string | null;
  canonical_url: string | null; title: string; excerpt: string; published_at: string | null;
};
export type SourceSnapshot = Attribution & {
  id: string; source_name: string; source_url: string; external_id: string | null; original_url: string;
  canonical_url: string | null; published_at: string | null; input_text: string; captured_at: string; snapshot_hash: string;
};
export type EditorialVersion = {
  id: string; version_number: number; payload_schema_version: number; payload: Record<string, unknown>;
  content_hash: string; origin: string; actor_issuer: string; actor_subject: string; created_at: string; sources: SourceSnapshot[];
};
export type DraftStatus = "editing" | "in_review" | "changes_requested" | "approved" | "rejected";
export type EditorialDraft = {
  id: string; story_id: string; target_locale: "sr-Latn"; status: DraftStatus; revision: number;
  created_at: string; updated_at: string; current_version: EditorialVersion | null; effective_approval: boolean;
};
export type CreateDraftCommand = { command_id: string; expected_revision: 0; story_id: string; target_locale: "sr-Latn"; payload: PublishingPayload };
export type SaveRevisionCommand = { command_id: string; expected_revision: number; payload: PublishingPayload };
export type EditorialReceipt = { command_id: string; draft_id: string; revision: number; status: DraftStatus; version_number: number; content_hash: string };
export type EditorialVersionSummary = Omit<EditorialVersion, "payload" | "sources"> & { source_count: number };
export type EditorialEvent = {
  id: string; event_type: string; from_status: string | null; to_status: string | null;
  version_number: number | null; command_id: string | null; actor_issuer: string; actor_subject: string;
  occurred_at: string; details: Record<string, unknown>;
};
export type VersionCommand = { command_id: string; expected_revision: number; version_number: number; content_hash: string };
export type DecisionCommand = VersionCommand & { reason?: string | null };
export type NegativeDecisionCommand = VersionCommand & { reason: string };
export type EditorialAction = "submit" | "approve" | "request-changes" | "reject" | "reopen";
