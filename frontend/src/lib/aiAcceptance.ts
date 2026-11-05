import { canonicalJson, emptyForm, formFromPayload, isUuid, readPublishingPayload } from "./editorialForm";
import { checkedVersion, isHash } from "./editorialWorkflow";
import { EditorialApiError } from "../services/editorialApi";
import type { AcceptAiSuggestion, AiSource, AiSuggestion } from "../types/ai";
import type { EditorialDraft, EditorialReceipt, EditorialVersion } from "../types/editorial";

export type AcceptanceIntent = {
  command: AcceptAiSuggestion; draftId: string | null; versionNumber: number; receipt: EditorialReceipt | null;
};
const invalid = () => new EditorialApiError(502, "Unconfirmed AI acceptance response.");
export const editableAiDraft = (head: EditorialDraft | null) => !head || ["editing", "changes_requested", "approved"].includes(head.status);
export const frozenAttribution = (source: AiSource) => [{ article_id: source.article_id, source_id: source.source_id }];

export function formFromSuggestion(suggestion: AiSuggestion, head: EditorialDraft | null) {
  const saved = head?.current_version;
  const payload = saved ? readPublishingPayload(saved.payload) : null;
  if (saved && (saved.payload_schema_version !== 1 || !payload)) throw invalid();
  if (!suggestion.output) throw invalid();
  const form = payload ? formFromPayload(payload) : emptyForm();
  return { ...form, headline: suggestion.output.headline, excerpt: suggestion.output.excerpt, body: suggestion.output.body,
    ...(suggestion.output.seo ? { seoTitle: suggestion.output.seo.title, seoDescription: suggestion.output.seo.description } : {}),
    sources: frozenAttribution(suggestion.input.source) };
}

export function checkedAcceptanceReceipt(value: EditorialReceipt, plan: AcceptanceIntent) {
  if (!value || value.command_id !== plan.command.command_id || !isUuid(value.draft_id) || (plan.draftId && value.draft_id !== plan.draftId) ||
      value.revision !== plan.command.expected_revision + 1 || value.status !== "editing" || value.version_number !== plan.versionNumber || !isHash(value.content_hash)) throw invalid();
  return value;
}
function sameTime(left: string | null, right: string | null) {
  return left === right || (left !== null && right !== null && Number.isFinite(Date.parse(left)) && Date.parse(left) === Date.parse(right));
}
export function checkedAcceptedVersion(raw: EditorialVersion, plan: AcceptanceIntent, source: AiSource) {
  const value = checkedVersion(raw), receipt = plan.receipt;
  const payload = readPublishingPayload(value.payload), snapshot = value.sources[0];
  if (!receipt || value.version_number !== receipt.version_number || value.content_hash !== receipt.content_hash || value.origin !== "ai" ||
      value.payload_schema_version !== 1 || !payload || canonicalJson(payload) !== canonicalJson(plan.command.payload) || value.sources.length !== 1 ||
      snapshot.article_id !== source.article_id || snapshot.source_id !== source.source_id || snapshot.input_text !== source.input_text ||
      snapshot.source_name !== source.source_name || snapshot.source_url !== source.source_url || snapshot.external_id !== source.external_id ||
      snapshot.original_url !== source.original_url || snapshot.canonical_url !== source.canonical_url ||
      !sameTime(snapshot.published_at, source.published_at) || !sameTime(snapshot.captured_at, source.captured_at)) throw invalid();
  return value;
}
