import { isUuid } from "./editorialForm";
import { EditorialApiError } from "../services/editorialApi";
import type { DraftStatus, EditorialAction, EditorialCapabilities, EditorialDraft, EditorialEvent, EditorialVersion, EditorialVersionSummary } from "../types/editorial";

export const statusText: Record<DraftStatus, string> = { editing: "Uređivanje", in_review: "Na pregledu", changes_requested: "Traže se izmene", approved: "Odobreno", rejected: "Odbijeno" };
export const actionText: Record<EditorialAction, string> = { submit: "Pošalji na pregled", approve: "Odobri", "request-changes": "Zatraži izmene", reject: "Odbij", reopen: "Ponovo otvori" };
export const targetStatus: Record<EditorialAction, DraftStatus> = { submit: "in_review", approve: "approved", "request-changes": "changes_requested", reject: "rejected", reopen: "editing" };
export const isHash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const invalid = () => new EditorialApiError(502, "Invalid private editorial response.");
function metadata(value: EditorialVersion | EditorialVersionSummary) {
  if (!value || !isUuid(value.id) || !Number.isSafeInteger(value.version_number) || value.version_number < 1 || !isHash(value.content_hash) || !Number.isSafeInteger(value.payload_schema_version) || ![value.actor_issuer, value.actor_subject, value.origin, value.created_at].every(field => typeof field === "string")) throw invalid();
}
export function checkedVersion(value: EditorialVersion, expected?: Pick<EditorialVersionSummary, "id" | "version_number" | "content_hash">): EditorialVersion {
  metadata(value);
  if (!value.payload || typeof value.payload !== "object" || Array.isArray(value.payload) || !Array.isArray(value.sources) || value.sources.some(row => !row || !isUuid(row.id) || !isUuid(row.article_id) || !isUuid(row.source_id) || !isHash(row.snapshot_hash) || ![row.input_text, row.source_name, row.source_url, row.original_url, row.captured_at].every(field => typeof field === "string"))) throw invalid();
  if (expected && (value.id !== expected.id || value.version_number !== expected.version_number || value.content_hash !== expected.content_hash)) throw invalid();
  return value;
}
export function checkedHead(value: EditorialDraft, storyId: string): EditorialDraft {
  if (!value || !isUuid(value.id) || value.story_id !== storyId || value.target_locale !== "sr-Latn" || !Object.prototype.hasOwnProperty.call(statusText, value.status) || !Number.isSafeInteger(value.revision) || value.revision < 1 || typeof value.effective_approval !== "boolean") throw invalid();
  if (value.current_version !== null) checkedVersion(value.current_version);
  return value;
}
export function checkedSummaries(rows: EditorialVersionSummary[], limit: number) {
  if (!Array.isArray(rows) || rows.length > limit) throw invalid();
  rows.forEach(row => { metadata(row); if (!Number.isSafeInteger(row.source_count) || row.source_count < 0 || "payload" in row || "sources" in row) throw invalid(); });
  if (new Set(rows.map(row => row.id)).size !== rows.length) throw invalid();
  return rows;
}
export function checkedEvents(rows: EditorialEvent[], limit: number) {
  if (!Array.isArray(rows) || rows.length > limit || rows.some(row => !row || !isUuid(row.id) || ![row.event_type, row.actor_issuer, row.actor_subject, row.occurred_at].every(field => typeof field === "string") || !row.details || typeof row.details !== "object" || Array.isArray(row.details))) throw invalid();
  return rows;
}
export function allowedActions(head: EditorialDraft, capabilities: EditorialCapabilities): EditorialAction[] {
  if (!capabilities.commands_enabled || !head.current_version) return [];
  const result: EditorialAction[] = [];
  if (head.status === "editing" && capabilities.permissions.includes("editorial:submit")) result.push("submit");
  if (["changes_requested", "rejected"].includes(head.status) && capabilities.permissions.includes("editorial:edit")) result.push("reopen");
  if (head.status === "in_review" && capabilities.permissions.includes("editorial:review")) result.push("approve", "request-changes", "reject");
  return result;
}
export function reasonError(reason: string, required: boolean): string | null {
  if (required && !reason.trim()) return "Unesite obrazloženje odluke.";
  if ([...reason.trim()].length > 2000 || /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]|<[!?/a-zA-Z]|[\u0400-\u052f]/u.test(reason)) return "Obrazloženje mora biti običan tekst na latinici, do 2000 znakova.";
  return null;
}
export function privateError(reason: unknown): string {
  if (!(reason instanceof EditorialApiError)) return "Zahtev nije završen. Proverite vezu i pokušajte ponovo.";
  return ({ 0: "Veza nije dostupna. Ishod komande nije potvrđen.", 401: "Prijava je istekla. Privatni sadržaj je uklonjen.", 403: "Nemate dozvolu. Privatni sadržaj je uklonjen.", 404: "Nacrt ili verzija nisu dostupni.", 409: "Sukob revizija. Lokalni unos je sačuvan; učitajte i proverite najnoviju verziju.", 422: "Podaci ili veličina odgovora nisu podržani. Sadržaj nije skraćen.", 503: "Urednički servis nije dostupan. Ishod nije potvrđen." } as Record<number, string>)[reason.status] ?? "Server nije potvrdio zahtev. Pokušajte ponovo.";
}
export function sameApprovedPin(head: EditorialDraft, pin: EditorialDraft): boolean {
  return head.status === "approved" && head.effective_approval && head.id === pin.id && head.revision === pin.revision && Boolean(head.current_version && pin.current_version && head.current_version.id === pin.current_version.id && head.current_version.version_number === pin.current_version.version_number && head.current_version.content_hash === pin.current_version.content_hash);
}
export function matchingApproval(events: EditorialEvent[], head: EditorialDraft) {
  return events.find(event => {
    const result = event.details.result as Record<string, unknown> | undefined;
    return event.event_type === "draft.approve" && event.to_status === "approved" && event.version_number === head.current_version?.version_number && result?.draft_id === head.id && result?.revision === head.revision && result?.content_hash === head.current_version?.content_hash && result?.version_number === head.current_version?.version_number && result?.status === "approved";
  });
}
