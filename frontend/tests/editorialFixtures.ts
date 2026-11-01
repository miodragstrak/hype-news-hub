import type { EditorialIdentityAdapter } from "../src/context/EditorialAccessContext";
import type { EditorialDraft, EditorialReceipt, PublishingPayload, StorySource } from "../src/types/editorial";

export const uuid = (number: number) => `00000000-0000-4000-8000-${String(number).padStart(12, "0")}`;
export const storyId = uuid(1);
export const draftId = uuid(2);
export const sourceRows: StorySource[] = [1, 2].map(number => ({ article_id: uuid(100 + number), source_id: uuid(200 + number), source_name: `Portal ${number === 1 ? "One" : "Two"}`, source_url: `https://portal-${number}.invalid`, external_id: "7", original_url: `https://portal-${number}.invalid/posts/7`, canonical_url: null, title: `Izvor ${number}`, excerpt: `Current excerpt ${number}`, published_at: "2026-10-31T09:00:00Z" }));
export const publishingPayload = (): PublishingPayload => ({ headline: "Urednički naslov", body: "SAVED PRIVATE BODY", excerpt: "Kratak urednički opis.", slug: "urednicki-naslov", categories: ["Zabava"], tags: ["Festival"], seo: { title: "SEO naslov", description: "SEO opis." }, images: [], source_attribution: [{ article_id: sourceRows[0].article_id, source_id: sourceRows[0].source_id }] });
export function savedDraft(payload = publishingPayload(), revision = 1): EditorialDraft {
  return { id: draftId, story_id: storyId, target_locale: "sr-Latn", status: "editing", revision, created_at: "2026-10-31T10:00:00Z", updated_at: "2026-10-31T10:00:00Z", effective_approval: false,
    current_version: { id: uuid(300 + revision), version_number: revision, payload_schema_version: 1, payload: JSON.parse(JSON.stringify(payload)), content_hash: (revision % 2 ? "a" : "b").repeat(64), origin: "manual", actor_issuer: "urn:test", actor_subject: "editor", created_at: "2026-10-31T10:00:00Z", sources: payload.source_attribution.map(pair => {
      const source = sourceRows.find(row => row.article_id === pair.article_id)!;
      return { ...pair, id: uuid(400 + Number(pair.article_id.slice(-2))), source_name: source.source_name, source_url: source.source_url!, external_id: "7", original_url: source.original_url!, canonical_url: null, published_at: source.published_at, input_text: `FROZEN EVIDENCE ${source.source_name}`, captured_at: "2026-10-31T10:00:00Z", snapshot_hash: "f".repeat(64) };
    }) } };
}
export const receipt = (commandId: string, draft: EditorialDraft): EditorialReceipt => ({ command_id: commandId, draft_id: draft.id, revision: draft.revision, status: "editing", version_number: draft.current_version!.version_number, content_hash: draft.current_version!.content_hash });

/** Automated-test fixture only. Application code never imports this provider. */
export class TestEditorialIdentity implements EditorialIdentityAdapter {
  private session: { key: string } | null = { key: "test-session" };
  private listeners = new Set<() => void>();
  getSnapshot() { return this.session; }
  subscribe(listener: () => void) { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; }
  async getAccessToken(): Promise<string | null> { return this.session ? "fixture-editor-token" : null; }
  changeSession(key: string | null) { this.session = key ? { key } : null; this.listeners.forEach(listener => listener()); }
}
