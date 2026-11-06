import type { AiStatus } from "./ai";
import type { DraftStatus } from "./editorial";
import type { EditorialStory } from "./news";

/** EQ-001 private projection; no evidence, actor or command payloads. */
export type QueueAIStatus = {
  has_suggestion: boolean; latest_suggestion_id: string | null; status: AiStatus | null;
  created_at: string | null; completed_at: string | null; recovery_required: boolean;
};
export type PrivateQueueStory = EditorialStory & {
  editorial: { draft_id: string; status: DraftStatus; revision: number; current_version_number: number | null } | null;
  ai: QueueAIStatus;
};
export type PrivateEditorialQueue = {
  stories: PrivateQueueStory[]; stories_total: number; limit: number; offset: number; has_more: boolean;
};
