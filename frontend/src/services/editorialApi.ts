import { API_BASE_URL } from "./apiClient";
import type { AcceptAiSuggestion, AiSuggestion, AiSummary, CreateAiSuggestion } from "../types/ai";
import type { EditorialStoryWorkspace } from "../types/news";
import type { CreateDraftCommand, DecisionCommand, EditorialCapabilities, EditorialDraft, EditorialEvent, EditorialReceipt, EditorialVersion, EditorialVersionSummary, NegativeDecisionCommand, SaveRevisionCommand, StorySource, VersionCommand } from "../types/editorial";

export class EditorialApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message); this.name = "EditorialApiError"; }
}

export function editorialErrorMessage(error: unknown): string {
  if (!(error instanceof EditorialApiError)) return "The editorial service could not complete this request. Your local text has been kept.";
  const messages: Record<number, string> = {
    0: "The editorial service could not be reached. Your local text has been kept.",
    401: "Your editorial session is missing or expired. Sign in through your identity provider and retry access.",
    403: "Your account does not have permission for this editorial operation.",
    404: "This persisted story or editorial draft is no longer available.",
    409: "The server has a conflicting revision. Your local edits are intact; compare the latest saved draft before continuing.",
    413: "The editorial request is too large. Reduce the content before saving.",
    422: "The server rejected this content. Check required fields, Serbian Latin text, source attribution and image references.",
    503: "Production editorial editing is unavailable. Authentication or persistent editorial storage is not ready.",
  };
  return messages[error.status] ?? "The editorial service returned an unexpected response. No save has been confirmed.";
}

export class EditorialApi {
  constructor(private readonly token: () => Promise<string | null>, private readonly baseUrl = API_BASE_URL) {}

  private async request<T>(path: string, signal?: AbortSignal, body?: unknown): Promise<T> {
    if (!this.baseUrl) throw new EditorialApiError(503, "Editorial backend is not configured.");
    let token: string | null;
    try { token = await this.token(); }
    catch (error) { if (error instanceof EditorialApiError) throw error; throw new EditorialApiError(401, "Editorial session is unavailable."); }
    if (!token) throw new EditorialApiError(401, "Verified identity is required.");
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const abort = new AbortController();
    const cancel = () => abort.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    const deadline = setTimeout(cancel, 60_000);
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method: body === undefined ? "GET" : "POST", signal: abort.signal, cache: "no-store", credentials: "omit", redirect: "error",
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      // Do not reflect server bodies: errors may contain private input or connection details.
      if (!response.ok) throw new EditorialApiError(response.status, "Editorial request rejected.");
      try { return await response.json() as T; }
      catch { if (abort.signal.aborted) throw new EditorialApiError(0, "Editorial request timed out."); throw new EditorialApiError(502, "Invalid editorial JSON response."); }
    } catch (error) {
      if (signal?.aborted) throw error;
      if (error instanceof EditorialApiError) throw error;
      throw new EditorialApiError(0, "Editorial network request failed.");
    } finally {
      clearTimeout(deadline);
      signal?.removeEventListener("abort", cancel);
    }
  }

  capabilities(signal?: AbortSignal) { return this.request<EditorialCapabilities>("/api/editorial/capabilities", signal); }
  sources(storyId: string, offset = 0, signal?: AbortSignal) {
    return this.request<StorySource[]>(`/api/editorial/stories/${encodeURIComponent(storyId)}/sources?limit=50&offset=${offset}`, signal);
  }
  create(command: CreateDraftCommand, signal?: AbortSignal) { return this.request<EditorialReceipt>("/api/editorial/drafts", signal, command); }
  find(storyId: string, signal?: AbortSignal) { return this.request<EditorialDraft>(`/api/editorial/drafts?story_id=${encodeURIComponent(storyId)}`, signal); }
  draft(draftId: string, signal?: AbortSignal) { return this.request<EditorialDraft>(`/api/editorial/drafts/${encodeURIComponent(draftId)}`, signal); }
  save(draftId: string, command: SaveRevisionCommand, signal?: AbortSignal) {
    return this.request<EditorialReceipt>(`/api/editorial/drafts/${encodeURIComponent(draftId)}/revisions`, signal, command);
  }
  versions(draftId: string, limit = 20, offset = 0, signal?: AbortSignal) {
    return this.request<EditorialVersionSummary[]>(`/api/editorial/drafts/${encodeURIComponent(draftId)}/versions?limit=${limit}&offset=${offset}`, signal);
  }
  version(draftId: string, number: number, signal?: AbortSignal) {
    return this.request<EditorialVersion>(`/api/editorial/drafts/${encodeURIComponent(draftId)}/versions/${number}`, signal);
  }
  events(draftId: string, limit = 50, offset = 0, signal?: AbortSignal) {
    return this.request<EditorialEvent[]>(`/api/editorial/drafts/${encodeURIComponent(draftId)}/events?limit=${limit}&offset=${offset}`, signal);
  }
  submit(draftId: string, command: VersionCommand, signal?: AbortSignal) {
    return this.request<EditorialReceipt>(`/api/editorial/drafts/${encodeURIComponent(draftId)}/submit`, signal, command);
  }
  approve(draftId: string, command: DecisionCommand, signal?: AbortSignal) {
    return this.request<EditorialReceipt>(`/api/editorial/drafts/${encodeURIComponent(draftId)}/approve`, signal, command);
  }
  requestChanges(draftId: string, command: NegativeDecisionCommand, signal?: AbortSignal) {
    return this.request<EditorialReceipt>(`/api/editorial/drafts/${encodeURIComponent(draftId)}/request-changes`, signal, command);
  }
  reject(draftId: string, command: NegativeDecisionCommand, signal?: AbortSignal) {
    return this.request<EditorialReceipt>(`/api/editorial/drafts/${encodeURIComponent(draftId)}/reject`, signal, command);
  }
  reopen(draftId: string, command: NegativeDecisionCommand, signal?: AbortSignal) {
    return this.request<EditorialReceipt>(`/api/editorial/drafts/${encodeURIComponent(draftId)}/reopen`, signal, command);
  }
  collectedStory(storyId: string, signal?: AbortSignal) {
    // Existing public collected material, with private transport/no demo fallback.
    return this.request<EditorialStoryWorkspace>(`/api/editorial-stories/${encodeURIComponent(storyId)}`, signal);
  }
  aiSuggestions(storyId: string, limit = 20, offset = 0, signal?: AbortSignal) {
    return this.request<AiSummary[]>(`/api/editorial/ai/suggestions?story_id=${encodeURIComponent(storyId)}&limit=${limit}&offset=${offset}`, signal);
  }
  aiSuggestion(id: string, signal?: AbortSignal) {
    return this.request<AiSuggestion>(`/api/editorial/ai/suggestions/${encodeURIComponent(id)}`, signal);
  }
  generateAiSuggestion(command: CreateAiSuggestion, signal?: AbortSignal) {
    return this.request<AiSuggestion>("/api/editorial/ai/suggestions", signal, command);
  }
  acceptAiSuggestion(suggestionId: string, command: AcceptAiSuggestion, signal?: AbortSignal) {
    return this.request<EditorialReceipt>(`/api/editorial/ai/suggestions/${encodeURIComponent(suggestionId)}/accept`, signal, command);
  }
}
