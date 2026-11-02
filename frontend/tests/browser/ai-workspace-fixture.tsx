/** Browser tests only. Never imported by the production entry point. */
import React from "react";
import { createRoot } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import App from "../../src/App";
import { DemoDataProvider } from "../../src/context/DemoDataContext";
import type { AcceptAiSuggestion, CreateAiSuggestion } from "../../src/types/ai";
import type { EditorialReceipt, EditorialVersion } from "../../src/types/editorial";
import { aiSuggestion, aiSummary, collectedWorkspace } from "../aiFixtures";
import { savedDraft, sourceRows, storyId, TestEditorialIdentity, uuid } from "../editorialFixtures";
import "../../src/index.css";

const identity = new TestEditorialIdentity();
let stored = [aiSuggestion()], loseNext = false, holdNext = false;
let release: (() => void) | null = null;
const posts: CreateAiSuggestion[] = [];
const acceptancePosts: AcceptAiSuggestion[] = [], receipts = new Map<string, EditorialReceipt>();
let head = savedDraft(), loseAccept = false;
const versions: EditorialVersion[] = [head.current_version!];
stored[0].input.source.content += "\n" + "Izvorni članak sa dugim redovima. ".repeat(200) + "X".repeat(2000);
stored[0].input.source.input_text += "\n" + stored[0].input.source.content;
stored[0].output!.body += "\n" + "Dugačak predlog za proveru prikaza. ".repeat(200) + "Y".repeat(2000);
const json = (value: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(value), { status }));
window.fetch = async (input, init = {}) => {
  const url = new URL(String(input), location.href), path = url.pathname;
  if (path.endsWith("/capabilities")) return json({ roles: ["editor"], permissions: ["editorial:read", "editorial:edit"], storage: "postgres", commands_enabled: true });
  if (path.endsWith("/accept") && init.method === "POST") {
    const command: AcceptAiSuggestion = JSON.parse(String(init.body)); acceptancePosts.push(command);
    const previous = receipts.get(command.command_id); if (previous) return json(previous);
    const run = stored.find(row => row.id === path.split("/").at(-2));
    if (!run || run.status !== "succeeded" || command.expected_revision !== head.revision || !command.confirm_acceptance) return json({}, 409);
    const source = run.input.source, number = versions.length + 1;
    const version: EditorialVersion = { id: uuid(7000 + number), version_number: number, payload_schema_version: 1, payload: JSON.parse(JSON.stringify(command.payload)), content_hash: "d".repeat(64), origin: "ai", actor_issuer: "urn:test", actor_subject: "browser-editor", created_at: "2026-11-02T10:00:00Z",
      sources: [{ id: uuid(8000 + number), article_id: source.article_id, source_id: source.source_id, source_name: source.source_name, source_url: source.source_url, external_id: source.external_id, original_url: source.original_url, canonical_url: source.canonical_url, published_at: source.published_at, input_text: source.input_text, captured_at: source.captured_at, snapshot_hash: "f".repeat(64) }] };
    versions.push(version); head = { ...head, revision: head.revision + 1, status: "editing", effective_approval: false, current_version: version };
    run.status = "accepted"; run.revision = 3;
    const receipt: EditorialReceipt = { command_id: command.command_id, draft_id: head.id, revision: head.revision, status: "editing", version_number: number, content_hash: version.content_hash }; receipts.set(command.command_id, receipt);
    if (loseAccept) { loseAccept = false; throw new Error("Simulated lost acceptance response after commit"); }
    return json(receipt);
  }
  if (path === "/api/editorial/ai/suggestions" && init.method === "POST") {
    const command: CreateAiSuggestion = JSON.parse(String(init.body)); posts.push(command);
    let result = stored.find(row => row.command_id === command.command_id);
    if (!result) { result = aiSuggestion(stored.length + 1, command); stored = [result, ...stored]; }
    if (holdNext) { holdNext = false; await new Promise<void>(resolve => { release = resolve; }); }
    if (loseNext) { loseNext = false; throw new Error("Simulated lost response after commit"); }
    return json(result, 201);
  }
  if (path.startsWith("/api/editorial-stories/")) return json(collectedWorkspace());
  if (path.endsWith("/sources")) return json(sourceRows);
  if (path === "/api/editorial/drafts" || path === `/api/editorial/drafts/${head.id}`) return json(head);
  if (/\/versions\/\d+$/.test(path)) return json(versions.find(row => row.version_number === Number(path.split("/").at(-1))));
  if (path === "/api/editorial/ai/suggestions") return json(stored.map(aiSummary).slice(Number(url.searchParams.get("offset") || 0), Number(url.searchParams.get("offset") || 0) + Number(url.searchParams.get("limit") || 20)));
  if (path.startsWith("/api/editorial/ai/suggestions/")) return json(stored.find(row => row.id === path.split("/").at(-1)));
  if (path === "/api/discovery") return json([]);
  if (path === "/api/stories" || path === "/api/editorial-queue") return json({ stories: [], stories_total: 0 });
  throw new Error("Unexpected fixture request");
};
Object.assign(window, { aiFixture: { posts, acceptancePosts, getHead: () => head, getVersions: () => versions, getEvidence: () => stored[0].input, loseAccept: () => { loseAccept = true; }, lose: () => { loseNext = true; }, hold: () => { holdNext = true; }, release: () => release?.(), logout: () => identity.changeSession(null) } });
const router = createMemoryRouter([{ path: "*", element: <App editorialIdentity={identity} /> }], { initialEntries: [`/review/${storyId}/ai`] });
createRoot(document.getElementById("root")!).render(<React.StrictMode><DemoDataProvider><RouterProvider router={router} /></DemoDataProvider></React.StrictMode>);
