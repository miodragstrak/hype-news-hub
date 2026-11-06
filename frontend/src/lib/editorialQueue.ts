import { EditorialApiError } from "../services/editorialApi";
import type { PrivateEditorialQueue } from "../types/editorialQueue";
import type { StoryStatus } from "../types/news";
import { isUuid } from "./editorialForm";
import { statusText } from "./editorialWorkflow";
import { aiStatusText } from "./aiSuggestions";

export const collectionStatusText: Record<StoryStatus, string> = {
  collected: "Prikupljeno", merged: "Grupisano", translated: "Prevedeno", draft: "Oznaka nacrta",
  review: "Oznaka pregleda", published: "Oznaka objave",
};
const owns = (value: object, key: PropertyKey) => Object.prototype.hasOwnProperty.call(value, key);
const natural = (value: number) => Number.isSafeInteger(value) && value >= 0;
const date = (value: string | null) => value === null || (typeof value === "string" && Number.isFinite(Date.parse(value)));
export function checkedPrivateQueue(value: PrivateEditorialQueue, limit: number, offset: number): PrivateEditorialQueue {
  const invalid = () => { throw new EditorialApiError(502, "Invalid private queue response."); };
  if (!value || value.limit !== limit || value.offset !== offset || !natural(value.stories_total) ||
      typeof value.has_more !== "boolean" || !Array.isArray(value.stories) || value.stories.length > limit ||
      value.has_more !== (offset + value.stories.length < value.stories_total) ||
      (value.stories.length > 0 && offset + value.stories.length > value.stories_total)) invalid();
  for (const row of value.stories) {
    if (!row || !isUuid(row.id) || typeof row.headline !== "string" || !row.headline || !(row.published_at === null || typeof row.published_at === "string") ||
        !owns(collectionStatusText, row.status) || !natural(row.source_count) || !natural(row.article_count) ||
        !natural(row.importance_score) || row.importance_score > 100 || !Array.isArray(row.sources) ||
        row.sources.some(source => typeof source !== "string")) invalid();
    const editorial = row.editorial, ai = row.ai;
    if (editorial !== null && (!editorial || !isUuid(editorial.draft_id) || !owns(statusText, editorial.status) ||
        !natural(editorial.revision) || editorial.revision < 1 || (editorial.current_version_number !== null &&
        (!natural(editorial.current_version_number) || editorial.current_version_number < 1)))) invalid();
    if (!ai || typeof ai.has_suggestion !== "boolean" || typeof ai.recovery_required !== "boolean" ||
        !date(ai.created_at) || !date(ai.completed_at)) invalid();
    if (ai.has_suggestion) {
      if (!isUuid(ai.latest_suggestion_id) || ai.status === null || !owns(aiStatusText, ai.status) || ai.created_at === null ||
          (ai.recovery_required && ai.status !== "processing") || (ai.status === "processing" && ai.completed_at !== null)) invalid();
    } else if (ai.latest_suggestion_id !== null || ai.status !== null || ai.created_at !== null || ai.completed_at !== null || ai.recovery_required) invalid();
  }
  if (new Set(value.stories.map(row => row.id)).size !== value.stories.length) invalid();
  return value;
}
export function queueErrorText(reason: unknown): string {
  const status = reason instanceof EditorialApiError ? reason.status : 0;
  return ({ 0: "Veza sa uredničkim servisom nije dostupna.", 401: "Prijava je istekla ili nije potvrđena. Privatni red nije dostupan.",
    403: "Nemate dozvolu za pregled privatnog uredničkog reda.", 503: "Privatni urednički servis nije dostupan. Proverite prijavu i PostgreSQL.",
    502: "Odgovor privatnog uredničkog reda nije podržan." } as Record<number, string>)[status] ?? "Urednički red nije učitan. Pokušajte ponovo.";
}
