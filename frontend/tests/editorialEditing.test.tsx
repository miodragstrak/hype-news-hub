import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { StrictMode, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { DemoDataProvider, useDemoData } from "../src/context/DemoDataContext";
import * as news from "../src/services/newsService";
import type { EditorialDraft, PublishingPayload } from "../src/types/editorial";
import { draftId, publishingPayload, receipt, savedDraft, sourceRows, storyId, TestEditorialIdentity, uuid } from "./editorialFixtures";
import { deferred } from "./fixtures";

vi.mock("../src/services/newsService", async importOriginal => ({ ...await importOriginal<typeof import("../src/services/newsService")>(), isDemoDataModeEnabled: vi.fn(), getDiscoverySources: vi.fn(), getStories: vi.fn(), getEditorialQueue: vi.fn(), getEditorialStoryWorkspace: vi.fn() }));

type Call = { path: string; search: string; body: Record<string, unknown>; init: RequestInit };
let head: EditorialDraft | null;
let calls: Call[];
let capabilityStatus: number;
let permissions: string[];
let postOverride: ((call: Call) => Promise<Response>) | null;
let getOverride: ((path: string) => Promise<Response> | null) | null;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function PublicState() { const value = useDemoData(); return <output data-testid="public-package">{JSON.stringify(value.selectedDraftPackage)}</output>; }
function mount(identity: TestEditorialIdentity | undefined = new TestEditorialIdentity(), strict = false) {
  let replaceIdentity: (identity: TestEditorialIdentity | undefined) => void = () => undefined;
  function IdentityHost() {
    const [adapter, setAdapter] = useState<TestEditorialIdentity | undefined>(identity); replaceIdentity = setAdapter;
    return <App editorialIdentity={adapter} />;
  }
  const router = createMemoryRouter([{ path: "*", element: <IdentityHost /> }], { initialEntries: [`/review/${storyId}/edit`], future: { v7_relativeSplatPath: true } });
  const content = <DemoDataProvider><RouterProvider router={router} future={{ v7_startTransition: true }} /><PublicState /></DemoDataProvider>;
  return { ...render(strict ? <StrictMode>{content}</StrictMode> : content), router, replaceIdentity: (next: TestEditorialIdentity | undefined) => act(() => replaceIdentity(next)) };
}
function body() { return screen.getByLabelText(/^Body/) as HTMLTextAreaElement; }
function fill() {
  const payload = publishingPayload();
  fireEvent.click(screen.getByRole("button", { name: "Add tag" }));
  const values: Array<[RegExp, string]> = [[/^Headline/, payload.headline], [/^Body/, payload.body], [/^Excerpt/, payload.excerpt], [/^Slug/, payload.slug], [/^Category 1/, "Zabava"], [/^Tag 1/, "Festival"], [/^SEO title/, payload.seo.title], [/^SEO description/, payload.seo.description]];
  for (const [label, value] of values) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByRole("checkbox", { name: /Use Portal One/ }));
}
async function loaded() { await screen.findByRole("form", { name: "Serbian Latin editorial form" }); }
function posts() { return calls.filter(call => call.init.method === "POST"); }

beforeEach(() => {
  head = null; calls = []; capabilityStatus = 200; permissions = ["editorial:read", "editorial:edit", "editorial:submit"]; postOverride = null; getOverride = null;
  vi.mocked(news.isDemoDataModeEnabled).mockReturnValue(false);
  vi.mocked(news.getDiscoverySources).mockResolvedValue([]); vi.mocked(news.getStories).mockResolvedValue({ stories_total: 0, stories: [] }); vi.mocked(news.getEditorialQueue).mockResolvedValue({ stories_total: 0, stories: [] });
  const publicWorkspace = news.getDemoEditorialStoryWorkspace("story-finale-week");
  vi.mocked(news.getEditorialStoryWorkspace).mockResolvedValue({ ...publicWorkspace, id: storyId, story_id: storyId, source_articles: sourceRows.map((row, index) => ({ external_id: "7", source: row.source_name, source_url: row.source_url!, country: "RS", language: "sr", title: row.title, excerpt: row.excerpt, content: `CURRENT ARTICLE ${index + 1} <script>unsafe()</script>`, url: row.original_url!, published_at: row.published_at, featured_image: null, categories: [] })) });
  const outcomes = new Map<string, unknown>();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input)); const path = url.pathname;
    const call = { path, search: url.search, body: init.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {}, init }; calls.push(call);
    if (path === "/api/editorial/capabilities") return capabilityStatus === 200 ? json({ roles: ["editor"], permissions, storage: "postgres", commands_enabled: permissions.includes("editorial:edit") }) : json({ detail: "SENSITIVE SECRET" }, capabilityStatus);
    if (init.method === "POST") {
      if (postOverride) return postOverride(call);
      const key = String(call.body.command_id);
      if (outcomes.has(key)) return json(outcomes.get(key), path.endsWith("/revisions") ? 200 : 201);
      head = savedDraft(call.body.payload as PublishingPayload, Number(call.body.expected_revision) + 1);
      const result = receipt(key, head); outcomes.set(key, result); return json(result, path.endsWith("/revisions") ? 200 : 201);
    }
    const override = getOverride?.(path); if (override) return override;
    if (path.endsWith("/sources")) return json(sourceRows);
    if (path === "/api/editorial/drafts" || path === `/api/editorial/drafts/${draftId}`) return head ? json(head) : json({ detail: "Not found" }, 404);
    return json({}, 404);
  }));
});

describe("authenticated editorial editing", () => {
  it("preserves public preview and reports unavailable editing without an identity adapter", async () => {
    const router = createMemoryRouter([{ path: "*", element: <App /> }], { initialEntries: [`/review/${storyId}/edit`] });
    render(<DemoDataProvider><RouterProvider router={router} /></DemoDataProvider>);
    await screen.findByText(/Sign-in integration has not been configured/);
    expect(calls).toHaveLength(0); expect(screen.queryByLabelText(/^Body/)).toBeNull();
    fireEvent.click(screen.getByRole("link", { name: "Public story preview" }));
    await screen.findByRole("heading", { name: "Editorial Story Workspace" });
  });
  it.each([401, 403, 503])("shows capability failure %s without private data or demo fallback", async status => {
    capabilityStatus = status; mount(); await screen.findByRole("complementary", { name: "Production editorial access" });
    await waitFor(() => expect(screen.queryByText(/Checking authenticated/)).toBeNull());
    expect(screen.queryByLabelText(/^Body/)).toBeNull(); expect(posts()).toHaveLength(0);
    expect(document.body.textContent).not.toContain("SENSITIVE SECRET");
    expect(calls.every(call => call.path === "/api/editorial/capabilities")).toBe(true);
  });
  it("creates only on explicit Save and confirms persistence with a fresh read", async () => {
    mount(); await loaded(); fill(); expect(posts()).toHaveLength(0);
    expect(screen.getByText("Unsaved changes")).toBeTruthy(); fireEvent.click(screen.getByRole("button", { name: "Create and save draft" }));
    await screen.findByText(/Saved version 1\. Revision 1 confirmed/);
    const command = posts()[0].body;
    expect(command).toEqual({ command_id: expect.any(String), expected_revision: 0, story_id: storyId, target_locale: "sr-Latn", payload: publishingPayload() });
    expect(calls.some(call => call.path === `/api/editorial/drafts/${draftId}`)).toBe(true);
    expect(screen.getByTestId("public-package").textContent).toBe("null");
    expect(screen.queryByRole("button", { name: /approve|publish|reject/i })).toBeNull();
  });
  it("reloads saved drafts after navigation and a fresh application mount", async () => {
    head = savedDraft(); const first = mount(); await loaded(); expect(body().value).toBe("SAVED PRIVATE BODY");
    fireEvent.click(screen.getByRole("link", { name: "Public story preview" })); await screen.findByRole("heading", { name: "Editorial Story Workspace" });
    expect(document.body.textContent).not.toContain("SAVED PRIVATE BODY");
    fireEvent.click(screen.getByRole("link", { name: "Open draft editor" })); await loaded(); expect(body().value).toBe("SAVED PRIVATE BODY");
    first.unmount(); mount(); await loaded(); expect(body().value).toBe("SAVED PRIVATE BODY");
  });
  it("saves expected revisions and retains every loaded image reference", async () => {
    const payload = publishingPayload(); payload.source_attribution = sourceRows.map(({ article_id, source_id }) => ({ article_id, source_id })); payload.images = sourceRows.map(row => ({ url: `${row.source_url}/image.jpg`, alt: "Fotografija", credit: "Foto izvor", source_article_id: row.article_id }));
    head = savedDraft(payload); mount(); await loaded(); fireEvent.change(body(), { target: { value: "A new private editorial body" } }); fireEvent.click(screen.getByRole("button", { name: "Save revision" }));
    await screen.findByText(/Saved version 2\. Revision 2 confirmed/);
    expect(posts()[0].body.expected_revision).toBe(1); expect((posts()[0].body.payload as PublishingPayload).images).toEqual(payload.images);
  });
  it("warns on refresh and blocks navigation until changes are explicitly discarded", async () => {
    head = savedDraft(); mount(); await loaded(); fireEvent.change(body(), { target: { value: "UNSAVED LOCAL TEXT" } });
    const event = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(event); expect(event.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole("link", { name: "Public story preview" })); await screen.findByRole("alertdialog");
    fireEvent.click(screen.getByRole("button", { name: "Keep editing" })); expect(body().value).toBe("UNSAVED LOCAL TEXT");
    fireEvent.click(screen.getByRole("link", { name: "Public story preview" })); fireEvent.click(await screen.findByRole("button", { name: "Discard and leave" }));
    await screen.findByRole("heading", { name: "Editorial Story Workspace" }); expect(posts()).toHaveLength(0);
  });
  it("retains local edits on 409 and uses a new expected revision only after explicit reload", async () => {
    head = savedDraft(); mount(); await loaded(); fireEvent.change(body(), { target: { value: "LOCAL CONFLICT TEXT" } });
    postOverride = async () => { head = savedDraft({ ...publishingPayload(), body: "REMOTE NEW BODY" }, 2); return json({}, 409); };
    fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await screen.findByRole("heading", { name: "Concurrent edit conflict" });
    expect(body().value).toBe("LOCAL CONFLICT TEXT"); expect(screen.queryByText(/confirmed by the server/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Replace local edits with latest saved draft" })); fireEvent.click(screen.getByRole("button", { name: "Keep editing" })); expect(body().value).toBe("LOCAL CONFLICT TEXT");
    fireEvent.click(screen.getByRole("button", { name: "Replace local edits with latest saved draft" })); fireEvent.click(screen.getByRole("button", { name: "Reload and replace" }));
    await waitFor(() => expect(body().value).toBe("REMOTE NEW BODY"));
    postOverride = null; fireEvent.change(body(), { target: { value: "MANUALLY MERGED BODY" } }); fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await screen.findByText(/Saved version 3/); expect(posts()[1].body.expected_revision).toBe(2);
  });
  it("selects UUIDs independently when portals share an external post ID", async () => {
    mount(); await loaded(); fill(); fireEvent.click(screen.getByRole("checkbox", { name: /Use Portal Two/ })); fireEvent.click(screen.getByRole("button", { name: "Create and save draft" })); await screen.findByText(/Saved version 1/);
    expect((posts()[0].body.payload as PublishingPayload).source_attribution).toEqual(sourceRows.map(({ article_id, source_id }) => ({ article_id, source_id })));
    fireEvent.change(screen.getByLabelText("Inspect current source"), { target: { value: sourceRows[1].article_id } }); fireEvent.click(screen.getByRole("button", { name: "Load current source text" }));
    await screen.findByText("CURRENT ARTICLE 2 <script>unsafe()</script>"); expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText("Frozen evidence for the saved version")).toBeTruthy();
  });
  it("keeps validation errors and server 422 failures editable without claiming a save", async () => {
    mount(); await loaded(); fireEvent.click(screen.getByRole("checkbox", { name: /Use Portal One/ })); fireEvent.click(screen.getByRole("button", { name: "Create and save draft" })); await screen.findByText("Check the editorial form"); expect(posts()).toHaveLength(0);
    // The box is already checked; fill text fields and preserve that selection.
    fill(); fireEvent.click(screen.getByRole("checkbox", { name: /Use Portal One/ })); postOverride = async () => json({ detail: "PRIVATE REJECTED INPUT" }, 422);
    fireEvent.click(screen.getByRole("button", { name: "Create and save draft" })); await screen.findByText(/server rejected this content/);
    expect(body().value).toBe("SAVED PRIVATE BODY"); expect(body().readOnly).toBe(false); expect(document.body.textContent).not.toContain("PRIVATE REJECTED INPUT"); expect(screen.queryByText(/confirmed by the server/)).toBeNull();
  });
  it("retries an uncertain network save with the exact same command UUID", async () => {
    head = savedDraft(); mount(); await loaded(); fireEvent.change(body(), { target: { value: "NETWORK LOCAL BODY" } });
    postOverride = async () => { throw new Error("offline"); }; fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await screen.findByRole("button", { name: "Retry save" });
    expect(body().value).toBe("NETWORK LOCAL BODY"); expect(body().readOnly).toBe(true); postOverride = null;
    fireEvent.click(screen.getByRole("button", { name: "Retry save" })); await screen.findByText(/Saved version 2/);
    expect(posts()[1].body).toEqual(posts()[0].body);
  });
  it("does not repeat a confirmed POST when the follow-up read fails", async () => {
    const pending = deferred<Response>(); let reads = 0;
    getOverride = path => path === `/api/editorial/drafts/${draftId}` && reads++ === 0 ? pending.promise : null;
    mount(); await loaded(); fill(); fireEvent.click(screen.getByRole("button", { name: "Create and save draft" }));
    await waitFor(() => expect(posts()).toHaveLength(1)); expect(screen.queryByText(/confirmed by the server/)).toBeNull();
    await act(async () => pending.resolve(json({}, 503))); await screen.findByRole("button", { name: "Confirm saved version" });
    fireEvent.click(screen.getByRole("button", { name: "Confirm saved version" })); await screen.findByText(/Saved version 1/); expect(posts()).toHaveLength(1);
  });
  it.each([401, 403])("clears private content after save access failure %s", async status => {
    head = savedDraft(); mount(); await loaded(); fireEvent.change(body(), { target: { value: "PRIVATE EDITS TO CLEAR" } }); postOverride = async () => json({}, status);
    fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await screen.findByText(/Private editorial content has been cleared/);
    expect(screen.queryByLabelText(/^Body/)).toBeNull(); expect(document.body.textContent).not.toContain("PRIVATE EDITS TO CLEAR");
  });
  it("makes Reader access read-only and clears content on identity change/logout", async () => {
    permissions = ["editorial:read"]; head = savedDraft(); const identity = new TestEditorialIdentity(); mount(identity); await loaded();
    expect(body().readOnly).toBe(true); expect(screen.getByRole("button", { name: "Save revision" }).hasAttribute("disabled")).toBe(true);
    act(() => identity.changeSession(null)); await screen.findByText(/Sign in through your newsroom identity provider/); expect(screen.queryByLabelText(/^Body/)).toBeNull(); expect(document.body.textContent).not.toContain("SAVED PRIVATE BODY");
  });
  it("loads safely under React StrictMode", async () => { head = savedDraft(); mount(new TestEditorialIdentity(), true); await loaded(); expect(body().value).toBe("SAVED PRIVATE BODY"); });
  it("retains unsaved text during same-session credential refresh", async () => {
    head = savedDraft(); const identity = new TestEditorialIdentity(); mount(identity); await loaded();
    fireEvent.change(body(), { target: { value: "KEEP THIS DURING TOKEN REFRESH" } });
    const reads = calls.filter(call => call.path === "/api/editorial/drafts").length;
    act(() => identity.changeSession("test-session"));
    expect(body().value).toBe("KEEP THIS DURING TOKEN REFRESH");
    expect(calls.filter(call => call.path === "/api/editorial/drafts")).toHaveLength(reads);
  });
  it("ignores a late private response after logout", async () => {
    const pending = deferred<Response>(); head = savedDraft();
    getOverride = path => path === "/api/editorial/drafts" ? pending.promise : null;
    const identity = new TestEditorialIdentity(); mount(identity);
    await waitFor(() => expect(calls.some(call => call.path === "/api/editorial/drafts")).toBe(true));
    act(() => identity.changeSession(null));
    await act(async () => pending.resolve(json(head)));
    expect(screen.queryByLabelText(/^Body/)).toBeNull();
    expect(document.body.textContent).not.toContain("SAVED PRIVATE BODY");
  });
  it("does not lose the public UI if the identity SDK cannot read its session", async () => {
    const identity = new TestEditorialIdentity(); vi.spyOn(identity, "getSnapshot").mockImplementation(() => { throw new Error("SDK SECRET"); });
    mount(identity); await screen.findByText(/Your editorial session is missing or expired/);
    expect(calls).toHaveLength(0); expect(document.body.textContent).not.toContain("SDK SECRET");
    expect(screen.getByRole("link", { name: "Public story preview" })).toBeTruthy();
  });
  it("shows source failures and empty sources without making a create request", async () => {
    getOverride = path => path.endsWith("/sources") ? Promise.resolve(json({}, 503)) : null;
    const view = mount(); await screen.findByText(/persistent editorial storage is not ready/); expect(posts()).toHaveLength(0);
    view.unmount(); getOverride = path => path.endsWith("/sources") ? Promise.resolve(json([])) : null;
    mount(); await loaded(); expect(screen.getByText("No persisted source articles are available for this story.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create and save draft" }).hasAttribute("disabled")).toBe(true);
  });
  it("keeps explicitly enabled demo stories out of production editing", async () => {
    vi.mocked(news.isDemoDataModeEnabled).mockReturnValue(true); head = savedDraft(); mount();
    await screen.findByText(/Production editorial editing is unavailable for sample demo stories/);
    expect(screen.queryByLabelText(/^Body/)).toBeNull(); expect(posts()).toHaveLength(0);
  });
  it("loads additional source pages without using external post IDs", async () => {
    const archive = Array.from({ length: 50 }, (_, index) => ({ ...sourceRows[0], article_id: uuid(1000 + index), source_id: uuid(2000), source_name: "Archive portal", source_url: "https://archive.invalid", original_url: `https://archive.invalid/${index}`, external_id: String(index), title: `Archive article ${index}` }));
    let sourceReads = 0;
    getOverride = path => path.endsWith("/sources") ? Promise.resolve(json(sourceReads++ === 0 ? archive : sourceRows)) : null;
    mount(); await loaded(); fireEvent.click(screen.getByRole("button", { name: "Load more sources" }));
    await screen.findByRole("checkbox", { name: /Use Portal Two/ });
    expect(new URLSearchParams(calls.filter(call => call.path.endsWith("/sources"))[1].search).get("offset")).toBe("50");
    fill(); fireEvent.click(screen.getByRole("button", { name: "Create and save draft" })); await screen.findByText(/Saved version 1/);
    expect((posts()[0].body.payload as PublishingPayload).source_attribution).toEqual(publishingPayload().source_attribution);
  });
  it("never sends a late token after the identity has logged out", async () => {
    const token = deferred<string | null>(); const identity = new TestEditorialIdentity();
    const getter = vi.spyOn(identity, "getAccessToken").mockReturnValue(token.promise);
    mount(identity); await waitFor(() => expect(getter).toHaveBeenCalled());
    act(() => identity.changeSession(null)); await act(async () => token.resolve("fixture-editor-token"));
    expect(calls).toHaveLength(0); expect(screen.queryByLabelText(/^Body/)).toBeNull();
  });
  it("locks the whole form during delayed reload and prevents overlapping commands", async () => {
    head = savedDraft(); mount(); await loaded(); fireEvent.change(body(), { target: { value: "LOCAL BEFORE CONFIRMATION" } });
    const pending = deferred<Response>(); let reads = 0;
    getOverride = path => path === "/api/editorial/drafts" ? (reads++, pending.promise) : null;
    fireEvent.click(screen.getByRole("button", { name: "Reload saved draft" })); fireEvent.click(screen.getByRole("button", { name: "Reload and replace" }));
    await screen.findByText("Reloading saved draft… Local input is locked.");
    expect(body().readOnly).toBe(true); expect(screen.getByLabelText(/^Category 1/).hasAttribute("readonly")).toBe(true);
    expect(screen.getByRole("checkbox", { name: /Use Portal One/ }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Save revision" }).hasAttribute("disabled")).toBe(true);
    fireEvent.change(body(), { target: { value: "MUST NOT BE ACCEPTED WHILE LOCKED" } });
    fireEvent.submit(screen.getByRole("form")); fireEvent.click(screen.getByRole("button", { name: "Reload saved draft" }));
    expect(posts()).toHaveLength(0); expect(reads).toBe(1);
    await act(async () => pending.resolve(json(savedDraft({ ...publishingPayload(), body: "NEW SERVER BODY" }, 2))));
    await waitFor(() => expect(body().value).toBe("NEW SERVER BODY")); expect(body().readOnly).toBe(false);
    expect(screen.getByText("No unsaved changes")).toBeTruthy();
    fireEvent.change(body(), { target: { value: "NEW EDIT AFTER RELOAD" } });
    expect(body().value).toBe("NEW EDIT AFTER RELOAD"); expect(screen.getByText("Unsaved changes")).toBeTruthy();
  });
  it.each([503, 0])("preserves local text and its dirty indicator when a reload fails (%s)", async status => {
    head = savedDraft(); mount(); await loaded(); fireEvent.change(body(), { target: { value: "KEEP ON RELOAD FAILURE" } });
    const pending = deferred<Response>(); getOverride = path => path === "/api/editorial/drafts" ? pending.promise.then(response => { if (!status) throw new Error("Offline"); return response; }) : null;
    fireEvent.click(screen.getByRole("button", { name: "Reload saved draft" })); fireEvent.click(screen.getByRole("button", { name: "Reload and replace" }));
    await act(async () => pending.resolve(json({}, status || 200)));
    await waitFor(() => expect(body().readOnly).toBe(false)); expect(body().value).toBe("KEEP ON RELOAD FAILURE"); expect(screen.getByText("Unsaved changes")).toBeTruthy(); expect(posts()).toHaveLength(0);
    getOverride = null; fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await screen.findByText(/Saved version 2/);
    expect((posts()[0].body.payload as PublishingPayload).body).toBe("KEEP ON RELOAD FAILURE");
  });
  it("serializes save confirmation against reload and rapid repeated submissions", async () => {
    head = savedDraft(); mount(); await loaded(); fireEvent.change(body(), { target: { value: "DELAYED SAVE" } });
    const pending = deferred<Response>(); postOverride = call => { head = savedDraft(call.body.payload as PublishingPayload, 2); return pending.promise; };
    const reads = calls.filter(call => call.path === "/api/editorial/drafts").length;
    const form = screen.getByRole("form");
    act(() => { fireEvent.submit(form); fireEvent.submit(form); });
    await waitFor(() => expect(posts()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Reload saved draft" }));
    expect(screen.queryByRole("alertdialog")).toBeNull(); expect(body().readOnly).toBe(true);
    expect(calls.filter(call => call.path === "/api/editorial/drafts")).toHaveLength(reads);
    await act(async () => pending.resolve(json(receipt(String(posts()[0].body.command_id), head!))));
    await screen.findByText(/Saved version 2/); expect(posts()).toHaveLength(1); expect(body().readOnly).toBe(false);
  });
  it("keeps conflict comparison inside the save lock until its response arrives", async () => {
    head = savedDraft(); mount(); await loaded(); fireEvent.change(body(), { target: { value: "KEEP CONFLICT TEXT" } });
    const pending = deferred<Response>(); postOverride = async () => json({}, 409); getOverride = path => path === "/api/editorial/drafts" ? pending.promise : null;
    fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await screen.findByRole("heading", { name: "Concurrent edit conflict" });
    expect(body().readOnly).toBe(true); expect(screen.getByRole("button", { name: "Replace local edits with latest saved draft" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Compare latest saved draft" })); expect(posts()).toHaveLength(1);
    await act(async () => pending.resolve(json(savedDraft({ ...publishingPayload(), body: "CONCURRENT SERVER BODY" }, 2))));
    await waitFor(() => expect(body().readOnly).toBe(false)); expect(body().value).toBe("KEEP CONFLICT TEXT");
    expect(screen.getByText(/Latest server version 2/)).toBeTruthy();
  });
  it("aborts an abandoned reload and ignores its response after revisiting the story", async () => {
    head = savedDraft(); mount(); await loaded(); const original = head;
    const pending = deferred<Response>(); getOverride = path => path === "/api/editorial/drafts" ? pending.promise : null;
    fireEvent.click(screen.getByRole("button", { name: "Reload saved draft" })); fireEvent.click(screen.getByRole("button", { name: "Reload and replace" })); await screen.findByText(/Reloading saved draft/);
    const request = calls.filter(call => call.path === "/api/editorial/drafts").at(-1)!;
    const unload = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(unload); expect(unload.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole("link", { name: "Public story preview" })); fireEvent.click(await screen.findByRole("button", { name: "Discard and leave" })); await screen.findByRole("heading", { name: "Editorial Story Workspace" });
    expect(request.init.signal?.aborted).toBe(true);
    head = savedDraft({ ...publishingPayload(), body: "FRESH REVISITED BODY" }, 2); getOverride = null;
    fireEvent.click(screen.getByRole("link", { name: "Open draft editor" })); await loaded();
    fireEvent.change(body(), { target: { value: "FRESH LOCAL EDIT" } }); await act(async () => pending.resolve(json(original)));
    expect(body().value).toBe("FRESH LOCAL EDIT"); expect(screen.getByText("Unsaved changes")).toBeTruthy();
  });
  it("fails closed before any private HTTP request if subscription initialization throws", async () => {
    head = savedDraft(); const identity = new TestEditorialIdentity(); let lateNotification: () => void = () => undefined;
    const subscription = vi.spyOn(identity, "subscribe").mockImplementation(listener => { lateNotification = listener; listener(); throw new Error("PRIVATE SDK ERROR"); });
    mount(identity, true); await screen.findByText(/Your editorial session is missing or expired/);
    expect(calls).toHaveLength(0); expect(screen.queryByLabelText(/^Body/)).toBeNull(); expect(document.body.textContent).not.toContain("PRIVATE SDK ERROR");
    subscription.mockRestore(); act(() => { identity.changeSession(null); lateNotification(); identity.changeSession("new-session"); lateNotification(); });
    expect(calls).toHaveLength(0); expect(screen.queryByLabelText(/^Body/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry editorial access" })); await loaded(); expect(body().value).toBe("SAVED PRIVATE BODY");
  });
  it("clears the workspace on unreliable identity replacement and ignores a pending reload", async () => {
    head = savedDraft(); const original = head; const view = mount(); await loaded(); fireEvent.change(body(), { target: { value: "PRIVATE EDIT BEFORE REPLACEMENT" } });
    const pending = deferred<Response>(); getOverride = path => path === "/api/editorial/drafts" ? pending.promise : null;
    fireEvent.click(screen.getByRole("button", { name: "Reload saved draft" })); fireEvent.click(screen.getByRole("button", { name: "Reload and replace" })); await screen.findByText(/Reloading saved draft/);
    const broken = new TestEditorialIdentity(); vi.spyOn(broken, "subscribe").mockImplementation(() => { throw new Error("PRIVATE SDK FAILURE"); });
    view.replaceIdentity(broken); await screen.findByText(/Your editorial session is missing or expired/);
    expect(screen.queryByLabelText(/^Body/)).toBeNull(); expect(document.body.textContent).not.toContain("PRIVATE EDIT BEFORE REPLACEMENT");
    act(() => broken.changeSession(null)); await act(async () => pending.resolve(json(original)));
    expect(screen.queryByLabelText(/^Body/)).toBeNull(); expect(document.body.textContent).not.toContain("FROZEN EVIDENCE");
    fireEvent.click(screen.getByRole("link", { name: "Public story preview" })); await screen.findByRole("heading", { name: "Editorial Story Workspace" });
  });
  it("removes private content when snapshot observation becomes unreliable", async () => {
    head = savedDraft(); const identity = new TestEditorialIdentity(); mount(identity); await loaded();
    vi.spyOn(identity, "getSnapshot").mockImplementation(() => { throw new Error("SECRET SNAPSHOT FAILURE"); });
    act(() => identity.changeSession("changed")); await screen.findByText(/Your editorial session is missing or expired/);
    expect(screen.queryByLabelText(/^Body/)).toBeNull(); expect(document.body.textContent).not.toContain("SAVED PRIVATE BODY"); expect(document.body.textContent).not.toContain("SECRET SNAPSHOT FAILURE");
  });
  it("does not let a previous adapter's reload replace a new adapter's workspace", async () => {
    head = savedDraft(); const original = head; const view = mount(); await loaded();
    const pending = deferred<Response>(); getOverride = path => path === "/api/editorial/drafts" ? pending.promise : null;
    fireEvent.click(screen.getByRole("button", { name: "Reload saved draft" })); fireEvent.click(screen.getByRole("button", { name: "Reload and replace" })); await screen.findByText(/Reloading saved draft/);
    getOverride = null; head = savedDraft({ ...publishingPayload(), body: "NEW IDENTITY PRIVATE BODY" }, 2);
    view.replaceIdentity(new TestEditorialIdentity()); await loaded();
    fireEvent.change(body(), { target: { value: "NEW IDENTITY LOCAL EDIT" } }); await act(async () => pending.resolve(json(original)));
    expect(body().value).toBe("NEW IDENTITY LOCAL EDIT"); expect(screen.getByText("Unsaved changes")).toBeTruthy();
  });
  it.each([
    ["reused key", "reject"], ["rotated key", "reject"], ["replaced adapter", "reject"],
    ["reused key", "resolve"], ["rotated key", "resolve"], ["replaced adapter", "resolve"],
  ] as const)("ignores an obsolete token %s / %s without clearing the new session's edits", async (replacement, outcome) => {
    head = savedDraft(); const identity = new TestEditorialIdentity(); const view = mount(identity); await loaded();
    fireEvent.change(body(), { target: { value: "PRIVATE EDIT FROM SESSION A" } });
    let resolve!: (token: string | null) => void; let reject!: (error: Error) => void;
    const promise = new Promise<string | null>((accept, fail) => { resolve = accept; reject = fail; });
    const getter = vi.spyOn(identity, "getAccessToken").mockReturnValueOnce(promise);
    fireEvent.click(screen.getByRole("button", { name: "Reload saved draft" })); fireEvent.click(screen.getByRole("button", { name: "Reload and replace" }));
    await waitFor(() => expect(getter).toHaveBeenCalledTimes(1));
    head = savedDraft({ ...publishingPayload(), body: "SAVED BODY LOADED IN SESSION B" }, 2);
    act(() => {
      identity.changeSession(null);
      if (replacement !== "replaced adapter") identity.changeSession(replacement === "reused key" ? "test-session" : "session-b");
    });
    if (replacement === "replaced adapter") view.replaceIdentity(new TestEditorialIdentity());
    await waitFor(() => { expect(body().readOnly).toBe(false); expect(body().value).toBe("SAVED BODY LOADED IN SESSION B"); });
    fireEvent.change(body(), { target: { value: "UNSAVED PRIVATE EDIT IN SESSION B" } }); const count = calls.length;
    await act(async () => { if (outcome === "reject") reject(new Error("OBSOLETE SDK FAILURE")); else resolve("fixture-editor-token"); });
    expect(calls).toHaveLength(count); expect(posts()).toHaveLength(0);
    expect(body().value).toBe("UNSAVED PRIVATE EDIT IN SESSION B"); expect(body().readOnly).toBe(false);
    expect(screen.getByText("Unsaved changes")).toBeTruthy(); expect(screen.getByRole("button", { name: "Save revision" }).hasAttribute("disabled")).toBe(false);
    expect(screen.queryByText(/Production editorial editing is unavailable/)).toBeNull(); expect(document.body.textContent).not.toContain("OBSOLETE SDK FAILURE");
    expect(screen.getByTestId("public-package").textContent).toBe("null");
  });
  it.each(["reject", "null"] as const)("still fails closed for a deferred current-session token %s", async outcome => {
    head = savedDraft(); const identity = new TestEditorialIdentity(); mount(identity); await loaded();
    fireEvent.change(body(), { target: { value: "CURRENT PRIVATE EDIT TO CLEAR" } });
    let resolve!: (token: string | null) => void; let reject!: (error: Error) => void;
    const promise = new Promise<string | null>((accept, fail) => { resolve = accept; reject = fail; });
    const getter = vi.spyOn(identity, "getAccessToken").mockReturnValueOnce(promise);
    fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await waitFor(() => expect(getter).toHaveBeenCalledTimes(1));
    await act(async () => { if (outcome === "reject") reject(new Error("CURRENT SDK SECRET")); else resolve(null); });
    await screen.findByText(/Your editorial session is missing or expired/);
    expect(screen.queryByLabelText(/^Body/)).toBeNull(); expect(posts()).toHaveLength(0);
    expect(document.body.textContent).not.toContain("CURRENT PRIVATE EDIT TO CLEAR"); expect(document.body.textContent).not.toContain("CURRENT SDK SECRET");
    expect(head.current_version?.version_number).toBe(1); expect(screen.getByTestId("public-package").textContent).toBe("null");
  });
  it("never restores a pending committed save after logout", async () => {
    head = savedDraft(); const identity = new TestEditorialIdentity(); mount(identity); await loaded(); fireEvent.change(body(), { target: { value: "PRIVATE LATE SAVE" } });
    const pending = deferred<Response>(); postOverride = call => { head = savedDraft(call.body.payload as PublishingPayload, 2); return pending.promise; };
    fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await waitFor(() => expect(posts()).toHaveLength(1));
    act(() => identity.changeSession(null)); await screen.findByText(/Sign in through your newsroom identity provider/);
    await act(async () => pending.resolve(json(receipt(String(posts()[0].body.command_id), head!))));
    expect(screen.queryByLabelText(/^Body/)).toBeNull(); expect(document.body.textContent).not.toContain("PRIVATE LATE SAVE"); expect(screen.getByTestId("public-package").textContent).toBe("null");
  });
  it("clears private content when token acquisition fails and ignores late tokens from replaced adapters", async () => {
    head = savedDraft(); const identity = new TestEditorialIdentity(); const view = mount(identity); await loaded();
    fireEvent.change(body(), { target: { value: "PRIVATE TOKEN FAILURE EDIT" } });
    vi.spyOn(identity, "getAccessToken").mockRejectedValue(new Error("SECRET SDK TOKEN"));
    fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await screen.findByText(/Your editorial session is missing or expired/);
    expect(screen.queryByLabelText(/^Body/)).toBeNull(); expect(document.body.textContent).not.toContain("PRIVATE TOKEN FAILURE EDIT");
    const token = deferred<string | null>(); const waiting = new TestEditorialIdentity(); const getter = vi.spyOn(waiting, "getAccessToken").mockReturnValue(token.promise);
    view.replaceIdentity(waiting); await waitFor(() => expect(getter).toHaveBeenCalled());
    const broken = new TestEditorialIdentity(); vi.spyOn(broken, "subscribe").mockImplementation(() => { throw new Error("Subscription unavailable"); });
    const count = calls.length; view.replaceIdentity(broken); await act(async () => token.resolve("fixture-editor-token"));
    expect(calls).toHaveLength(count); expect(screen.queryByLabelText(/^Body/)).toBeNull();
  });
  it("saves body-only changes without altering unusual category or tag values", async () => {
    const payload = { ...publishingPayload(), categories: ["Pop\nkultura", "Film, TV", "Dva\r\nreda", "\ufeffLabel\ufeff"], tags: ["Festival\rMuzika", "Tab\tlabel", "Čćšžđ 😀"] };
    head = savedDraft(payload); mount(); await loaded();
    // Textareas display CR/CRLF as LF; saving must use the untouched model values.
    expect((screen.getByLabelText(/^Category 3/) as HTMLTextAreaElement).value).toBe("Dva\nreda");
    fireEvent.change(body(), { target: { value: "Only the body changes." } }); fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await screen.findByText(/Saved version 2/);
    const sent = posts()[0].body.payload as PublishingPayload;
    expect(JSON.stringify(sent.categories)).toBe(JSON.stringify(payload.categories)); expect(JSON.stringify(sent.tags)).toBe(JSON.stringify(payload.tags));
  });
  it("edits, adds and removes individual labels without treating punctuation as separators", async () => {
    head = savedDraft(); mount(); await loaded();
    fireEvent.change(screen.getByLabelText(/^Category 1/), { target: { value: "Film, TV\nScena" } }); fireEvent.click(screen.getByRole("button", { name: "Add category" }));
    fireEvent.change(screen.getByLabelText(/^Category 2/), { target: { value: "Događaji" } }); fireEvent.click(screen.getByRole("button", { name: "Remove tag 1" })); fireEvent.click(screen.getByRole("button", { name: "Add tag" }));
    fireEvent.change(screen.getByLabelText(/^Tag 1/), { target: { value: "Muzika, festival\nProgram" } }); fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await screen.findByText(/Saved version 2/);
    expect((posts()[0].body.payload as PublishingPayload).categories).toEqual(["Film, TV\nScena", "Događaji"]); expect((posts()[0].body.payload as PublishingPayload).tags).toEqual(["Muzika, festival\nProgram"]);
  });
});
