/** Browser tests only. Never imported by the production entry point. */
import React from "react";
import { createRoot } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import App from "../../src/App";
import { DemoDataProvider } from "../../src/context/DemoDataContext";
import type { CreateAiSuggestion } from "../../src/types/ai";
import { aiSuggestion, aiSummary, collectedWorkspace } from "../aiFixtures";
import { savedDraft, sourceRows, storyId, TestEditorialIdentity } from "../editorialFixtures";
import "../../src/index.css";

const identity = new TestEditorialIdentity();
let stored = [aiSuggestion()], loseNext = false, holdNext = false;
let release: (() => void) | null = null;
const posts: CreateAiSuggestion[] = [];
stored[0].input.source.content += "\n" + "Izvorni članak sa dugim redovima. ".repeat(200) + "X".repeat(2000);
stored[0].input.source.input_text += "\n" + stored[0].input.source.content;
stored[0].output!.body += "\n" + "Dugačak predlog za proveru prikaza. ".repeat(200) + "Y".repeat(2000);
const json = (value: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(value), { status }));
window.fetch = async (input, init = {}) => {
  const url = new URL(String(input), location.href), path = url.pathname;
  if (path.endsWith("/capabilities")) return json({ roles: ["editor"], permissions: ["editorial:read", "editorial:edit"], storage: "postgres", commands_enabled: true });
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
  if (path === "/api/editorial/drafts") return json(savedDraft());
  if (path === "/api/editorial/ai/suggestions") return json(stored.map(aiSummary).slice(Number(url.searchParams.get("offset") || 0), Number(url.searchParams.get("offset") || 0) + Number(url.searchParams.get("limit") || 20)));
  if (path.startsWith("/api/editorial/ai/suggestions/")) return json(stored.find(row => row.id === path.split("/").at(-1)));
  if (path === "/api/discovery") return json([]);
  if (path === "/api/stories" || path === "/api/editorial-queue") return json({ stories: [], stories_total: 0 });
  throw new Error("Unexpected fixture request");
};
Object.assign(window, { aiFixture: { posts, lose: () => { loseNext = true; }, hold: () => { holdNext = true; }, release: () => release?.(), logout: () => identity.changeSession(null) } });
const router = createMemoryRouter([{ path: "*", element: <App editorialIdentity={identity} /> }], { initialEntries: [`/review/${storyId}/ai`] });
createRoot(document.getElementById("root")!).render(<React.StrictMode><DemoDataProvider><RouterProvider router={router} /></DemoDataProvider></React.StrictMode>);
