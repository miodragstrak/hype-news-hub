import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { DemoDataProvider } from "../src/context/DemoDataContext";
import * as news from "../src/services/newsService";
import { checkedAcceptedVersion } from "../src/lib/aiAcceptance";
import type { AcceptAiSuggestion, AiSuggestion } from "../src/types/ai";
import type { DraftStatus, EditorialDraft, EditorialReceipt, EditorialVersion } from "../src/types/editorial";
import { aiSuggestion } from "./aiFixtures";
import { draftId, publishingPayload, savedDraft, sourceRows, storyId, TestEditorialIdentity, uuid } from "./editorialFixtures";
import { deferred } from "./fixtures";

vi.mock("../src/services/newsService", async original => ({ ...await original<typeof import("../src/services/newsService")>(), isDemoDataModeEnabled: vi.fn(), getDiscoverySources: vi.fn(), getStories: vi.fn(), getEditorialQueue: vi.fn() }));
type Call = { path: string; body: AcceptAiSuggestion; init: RequestInit };
let suggestion: AiSuggestion, head: EditorialDraft | null, versions: EditorialVersion[], calls: Call[], permissions: string[], commands: boolean, capabilityStatus: number;
let getOverride: ((call: Call) => Promise<Response> | null) | null;
let postOverride: ((call: Call, commit: () => Response) => Promise<Response>) | null;
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const posts = () => calls.filter(call => call.init.method === "POST");
const currentHead = () => head;
const body = () => screen.getByLabelText(/^Body/) as HTMLTextAreaElement;
const prepare = () => screen.getByRole("button", { name: "Pregledaj i potvrdi prihvatanje" });
const confirm = () => screen.getByRole("button", { name: "Prihvati u nacrt" });
const loaded = () => screen.findByRole("form", { name: "Uređivanje AI predloga" });
const accepted = () => screen.findByRole("region", { name: "Potvrđeno AI prihvatanje" });
function mount(identity: TestEditorialIdentity | undefined = new TestEditorialIdentity(), id = storyId, suggestionId = suggestion.id) {
  const router = createMemoryRouter([{ path: "*", element: <App editorialIdentity={identity} /> }], { initialEntries: [`/review/${id}/ai/${suggestionId}/edit`] });
  return { ...render(<DemoDataProvider><RouterProvider router={router} /></DemoDataProvider>), router };
}
function accept() { fireEvent.click(prepare()); fireEvent.click(confirm()); }
function aiVersion(command: AcceptAiSuggestion, number: number): EditorialVersion {
  const source = suggestion.input.source;
  return { id: uuid(5000 + number), version_number: number, payload_schema_version: 1, payload: JSON.parse(JSON.stringify(command.payload)), content_hash: "d".repeat(64), origin: "ai", actor_issuer: "urn:verified", actor_subject: "verified-editor", created_at: "2026-11-02T10:00:00Z",
    sources: [{ id: uuid(6000 + number), article_id: source.article_id, source_id: source.source_id, source_name: source.source_name, source_url: source.source_url, external_id: source.external_id, original_url: source.original_url, canonical_url: source.canonical_url, published_at: source.published_at, input_text: source.input_text, captured_at: source.captured_at, snapshot_hash: "f".repeat(64) }] };
}
beforeEach(() => {
  suggestion = aiSuggestion(); head = savedDraft(); versions = [head.current_version!]; calls = []; permissions = ["editorial:read", "editorial:edit"]; commands = true; capabilityStatus = 200; getOverride = null; postOverride = null;
  vi.mocked(news.isDemoDataModeEnabled).mockReturnValue(false); vi.mocked(news.getDiscoverySources).mockResolvedValue([]); vi.mocked(news.getStories).mockResolvedValue({ stories: [], stories_total: 0 }); vi.mocked(news.getEditorialQueue).mockResolvedValue({ stories: [], stories_total: 0 });
  const receipts = new Map<string, { command: string; receipt: EditorialReceipt }>();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input)).pathname;
    const call: Call = { path, init, body: init.body ? JSON.parse(String(init.body)) : {} }; calls.push(call);
    if (path.endsWith("/capabilities")) return json({ roles: ["reader"], permissions, commands_enabled: commands, storage: "postgres" }, capabilityStatus);
    if (init.method === "POST") {
      expect(path).toBe(`/api/editorial/ai/suggestions/${suggestion.id}/accept`);
      const commit = () => {
        const previous = receipts.get(call.body.command_id);
        if (previous) return JSON.stringify(call.body) === previous.command ? json(previous.receipt) : json({}, 409);
        if (call.body.expected_revision !== (head?.revision ?? 0) || suggestion.status !== "succeeded") return json({}, 409);
        expect(call.body.confirm_acceptance).toBe(true); expect(call.body.story_id).toBe(storyId);
        expect(call.body.payload.source_attribution).toEqual([{ article_id: suggestion.article_id, source_id: suggestion.source_id }]);
        const version = aiVersion(call.body, (head?.current_version?.version_number ?? 0) + 1); versions.push(version);
        head = { ...(head ?? savedDraft()), revision: (head?.revision ?? 0) + 1, status: "editing", effective_approval: false, current_version: version };
        const receipt: EditorialReceipt = { command_id: call.body.command_id, draft_id: head.id, revision: head.revision, status: "editing", version_number: version.version_number, content_hash: version.content_hash };
        receipts.set(call.body.command_id, { command: JSON.stringify(call.body), receipt }); suggestion = { ...suggestion, status: "accepted", revision: 3 };
        return json(receipt);
      };
      return postOverride ? postOverride(call, commit) : commit();
    }
    const override = getOverride?.(call); if (override) return override;
    if (path === `/api/editorial/ai/suggestions/${suggestion.id}`) return json(suggestion);
    if (path === "/api/editorial/drafts") return head ? json(head) : json({}, 404);
    if (path === `/api/editorial/drafts/${draftId}`) return json(head);
    if (/\/versions\/\d+$/.test(path)) return json(versions.find(row => row.version_number === Number(path.split("/").at(-1))));
    throw new Error("Unexpected private route: " + path);
  }));
});

describe("explicit AI suggestion acceptance", () => {
  it.each(["direct", "before", "after"])("verifies the normalized complete payload after %s commit response, with stable command recovery", async timing => {
    const frozen = JSON.stringify(suggestion.input), output = JSON.stringify(suggestion.output);
    const expected = { ...publishingPayload(), headline: "Potvrđen naslov", body: "Urednički potvrđen tekst.", excerpt: "Potvrđen sažetak.",
      seo: { title: "Potvrđen SEO naslov", description: "Potvrđen SEO opis." }, images: [{ url: "https://media.invalid/image.jpg", alt: "Tačan opis", credit: "Tačan kredit", source_article_id: sourceRows[0].article_id }] };
    head = savedDraft({ ...publishingPayload(), images: expected.images }); let first = true;
    postOverride = async (_call, commit) => {
      if (first && timing === "before") { first = false; throw new Error("lost before commit"); }
      const response = commit();
      // Emulate PublishingPayload's persisted normalized values independently of
      // the frontend normalizer; exact read-back must still match this payload.
      versions.at(-1)!.payload = JSON.parse(JSON.stringify(expected));
      if (first && timing === "after") { first = false; throw new Error("lost after commit"); }
      return response;
    };
    mount(); await loaded();
    for (const [label, value] of [[/^Headline/, expected.headline], [/^Body/, expected.body], [/^Excerpt/, expected.excerpt], [/^SEO title/, expected.seo.title], [/^SEO description/, expected.seo.description], [/^Featured image alternative text/, expected.images[0].alt], [/^Featured image credit/, expected.images[0].credit]] as const) {
      fireEvent.change(screen.getByLabelText(label), { target: { value: "\u0085" + value + "\u0085" } });
    }
    accept();
    if (timing !== "direct") {
      await screen.findByLabelText("Oporavak prihvatanja"); expect(body().value).toBe("\u0085" + expected.body + "\u0085");
      expect(posts()).toHaveLength(1); fireEvent.click(screen.getByRole("button", { name: "Ponovi isto prihvatanje" }));
    }
    const view = await accepted(); expect(posts()[0].body.payload).toEqual(expected); expect(within(view).getByText(expected.body)).toBeTruthy();
    if (timing !== "direct") expect(posts()[1].body).toEqual(posts()[0].body);
    expect(versions).toHaveLength(2); expect(JSON.stringify(suggestion.input)).toBe(frozen); expect(JSON.stringify(suggestion.output)).toBe(output);
  });
  it("preserves internal NEL and FEFF in an accepted publishing body", async () => {
    mount(); await loaded(); const text = "\ufeffPrvi\tred\nDrugi\u0085red\u00a0čćšžđ\ufeff";
    fireEvent.change(body(), { target: { value: "\u0085" + text + "\u0085" } }); accept();
    const view = await accepted(); expect(posts()[0].body.payload.body).toBe(text); expect(within(view).getByText((_value, node) => node?.textContent === text && node.classList.contains("leading-7"))).toBeTruthy();
  });
  it("prepopulates a separate editor, preserves publishing metadata and accepts only after confirmation and fresh reads", async () => {
    const frozen = JSON.stringify(suggestion.input), output = JSON.stringify(suggestion.output);
    head = savedDraft({ ...publishingPayload(), categories: ["Pop\nkultura", "Film, TV"], tags: ["Čćšžđ\r\nFestival"] });
    mount(); await loaded(); expect(body().value).toBe("AI PRIVATE BODY 1"); expect((screen.getByLabelText(/^Headline/) as HTMLTextAreaElement).value).toBe("AI naslov 1");
    expect((screen.getByLabelText(/^Excerpt/) as HTMLTextAreaElement).value).toBe(suggestion.output!.excerpt);
    fireEvent.change(body(), { target: { value: "Urednik je ručno izmenio telo članka." } }); fireEvent.click(prepare());
    expect(posts()).toHaveLength(0); expect(screen.getByRole("alertdialog").textContent).toContain(suggestion.input_hash);
    expect(screen.getByRole("alertdialog").textContent).toContain(suggestion.output_hash);
    fireEvent.click(confirm()); const view = await accepted(); expect(posts()).toHaveLength(1);
    expect(posts()[0].body).toEqual({ command_id: expect.any(String), story_id: storyId, expected_revision: 1, confirm_acceptance: true, payload: { ...publishingPayload(), headline: "AI naslov 1", excerpt: suggestion.output!.excerpt, body: "Urednik je ručno izmenio telo članka.", categories: ["Pop\nkultura", "Film, TV"], tags: ["Čćšžđ\r\nFestival"] } });
    expect(within(view).getByText("Urednik je ručno izmenio telo članka.")).toBeTruthy();
    expect(within(view).getByText((_text, element) => element?.tagName === "PRE" && element.textContent === suggestion.input.source.input_text)).toBeTruthy(); expect(head?.effective_approval).toBe(false);
    expect(JSON.stringify(suggestion.input)).toBe(frozen); expect(JSON.stringify(suggestion.output)).toBe(output);
    expect(calls.some(call => call.path.endsWith("/versions/2"))).toBe(true); expect(calls.some(call => call.path === `/api/editorial/drafts/${draftId}`)).toBe(true);
    expect(screen.getByText("Prihvaćen u uredničku verziju")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Odobri|Objavi/ })).toBeNull();
  });
  it("cancels without any mutation and preserves local wording", async () => {
    mount(); await loaded(); fireEvent.change(body(), { target: { value: "Lokalno uređivanje" } }); fireEvent.click(prepare()); fireEvent.click(screen.getByRole("button", { name: "Odustani" }));
    expect(posts()).toHaveLength(0); expect(body().value).toBe("Lokalno uređivanje"); expect(screen.getByText("Nesačuvane lokalne izmene.")).toBeTruthy();
  });
  it.each(["", "Ћирилица", "<script>unsafe()</script>"])("rejects invalid edited text %s before submitting", async value => {
    mount(); await loaded(); fireEvent.change(body(), { target: { value } }); fireEvent.click(prepare());
    expect(screen.queryByRole("alertdialog")).toBeNull(); expect(screen.getByText(/Proverite označena polja/)).toBeTruthy(); expect(posts()).toHaveLength(0); expect(body().value).toBe(value);
  });
  it("creates a workspace using revision zero and the frozen portal UUID despite shared external IDs", async () => {
    head = null; versions = []; suggestion = aiSuggestion(1, { article_id: sourceRows[1].article_id, source_id: sourceRows[1].source_id });
    mount(); await loaded(); fireEvent.change(screen.getByLabelText(/^Slug/), { target: { value: "novi-ai-nacrt" } });
    fireEvent.change(screen.getByLabelText(/^Category 1/), { target: { value: "Zabava" } });
    fireEvent.change(screen.getByLabelText(/^SEO title/), { target: { value: "SEO naslov" } }); fireEvent.change(screen.getByLabelText(/^SEO description/), { target: { value: "SEO opis." } });
    accept(); await accepted(); expect(posts()[0].body.expected_revision).toBe(0); expect(currentHead()?.current_version?.version_number).toBe(1);
    expect(currentHead()?.current_version?.sources[0].source_id).toBe(sourceRows[1].source_id); expect(currentHead()?.current_version?.sources[0].input_text).toContain("Portal Two");
  });
  it.each(["approved", "changes_requested"] as DraftStatus[])("accepts from %s as editing without approval", async status => {
    head = { ...savedDraft(), status, revision: 6, effective_approval: status === "approved" }; mount(); await loaded(); accept(); await accepted();
    expect(posts()[0].body.expected_revision).toBe(6); expect(head?.revision).toBe(7); expect(head?.current_version?.version_number).toBe(2); expect(head?.status).toBe("editing"); expect(head?.effective_approval).toBe(false);
  });
  it.each(["in_review", "rejected"] as DraftStatus[])("does not offer acceptance from %s", async status => {
    head = { ...savedDraft(), status }; mount(); await loaded(); expect(prepare().hasAttribute("disabled")).toBe(true); expect(body().readOnly).toBe(true); fireEvent.click(prepare()); expect(posts()).toHaveLength(0);
  });
  it.each(["processing", "failed", "interrupted", "rejected", "accepted"] as const)("does not edit consumed or unfinished suggestion %s", async status => {
    suggestion = aiSuggestion(1, { status, revision: status === "accepted" || status === "rejected" ? 3 : 2, output_hash: ["processing", "failed", "interrupted"].includes(status) ? null : "b".repeat(64) });
    mount(); await screen.findByText(/Ovaj predlog nije dostupan za prihvatanje/); expect(screen.queryByRole("form")).toBeNull(); expect(posts()).toHaveLength(0);
  });
  it("prevents rapid duplicate confirmations and freezes editing until persistence is confirmed", async () => {
    const pending = deferred<Response>(); postOverride = async (_call, commit) => { const result = commit(); await pending.promise; return result; };
    mount(); await loaded(); fireEvent.click(prepare()); const button = confirm(); fireEvent.click(button); fireEvent.click(button);
    await waitFor(() => expect(posts()).toHaveLength(1)); expect(body().readOnly).toBe(true); expect(screen.queryByLabelText("Potvrđeno AI prihvatanje")).toBeNull();
    fireEvent.change(body(), { target: { value: "TOO LATE" } }); expect(body().value).toBe("AI PRIVATE BODY 1");
    await act(async () => pending.resolve(json({}))); await accepted(); expect(versions).toHaveLength(2);
  });
  it.each(["before", "after"])("recovers a lost response %s commit with the exact original command and payload", async timing => {
    let first = true; postOverride = async (_call, commit) => { if (first) { first = false; if (timing === "after") commit(); throw new Error("SENSITIVE TRANSPORT"); } return commit(); };
    mount(); await loaded(); fireEvent.change(body(), { target: { value: "Sačuvati tačno ovaj unos." } }); accept();
    await screen.findByLabelText("Oporavak prihvatanja"); expect(posts()).toHaveLength(1); expect(body().readOnly).toBe(true); expect(screen.queryByLabelText("Potvrđeno AI prihvatanje")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ponovi isto prihvatanje" })); await accepted();
    expect(posts()).toHaveLength(2); expect(posts()[1].body).toEqual(posts()[0].body); expect(versions).toHaveLength(2); expect(document.body.textContent).not.toContain("SENSITIVE TRANSPORT");
  });
  it("keeps an acceptance receipt after a read fails and retries only the pinned read", async () => {
    let fail = true; getOverride = call => fail && /\/versions\/2$/.test(call.path) ? Promise.resolve(json({}, 422)) : null;
    mount(); await loaded(); accept(); await screen.findByRole("button", { name: "Potvrdi prihvaćenu verziju čitanjem" });
    expect(screen.queryByLabelText("Potvrđeno AI prihvatanje")).toBeNull(); expect(posts()).toHaveLength(1); fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Potvrdi prihvaćenu verziju čitanjem" })); await accepted(); expect(posts()).toHaveLength(1);
  });
  it("does not report success until the pinned version has been read back from the server", async () => {
    const pending = deferred<Response>(); getOverride = call => /\/versions\/2$/.test(call.path) ? pending.promise : null;
    mount(); await loaded(); accept(); await waitFor(() => expect(calls.some(call => call.path.endsWith("/versions/2"))).toBe(true));
    expect(head?.status).toBe("editing"); expect(screen.queryByLabelText("Potvrđeno AI prihvatanje")).toBeNull(); expect(body().readOnly).toBe(true);
    await act(async () => pending.resolve(json(versions.at(-1)))); await accepted(); expect(posts()).toHaveLength(1);
  });
  it("pins the accepted immutable version when a later manual edit has already changed current content", async () => {
    let first = true; postOverride = async (_call, commit) => {
      const response = commit();
      if (first) { first = false; const newer = savedDraft({ ...publishingPayload(), body: "LATER MANUAL CONTENT" }, 3); versions.push(newer.current_version!); head = newer; throw new Error("lost response"); }
      return response;
    };
    mount(); await loaded(); accept(); await screen.findByLabelText("Oporavak prihvatanja"); fireEvent.click(screen.getByRole("button", { name: "Ponovi isto prihvatanje" }));
    const view = await accepted(); expect(within(view).getByText("AI PRIVATE BODY 1")).toBeTruthy(); expect(within(view).queryByText("LATER MANUAL CONTENT")).toBeNull(); expect(within(view).getByText(/Druga komanda/)).toBeTruthy(); expect(posts()[1].body).toEqual(posts()[0].body);
  });
  it("preserves local edits after a stale revision and requires explicit fresh context before a new command", async () => {
    mount(); await loaded(); fireEvent.change(body(), { target: { value: "NE PREPISUJ LOKALNI TEKST" } });
    head = savedDraft({ ...publishingPayload(), body: "REMOTE EDIT" }, 3); accept(); await screen.findByText(/Sukob revizija ili promenjeno stanje/);
    expect(body().value).toBe("NE PREPISUJ LOKALNI TEKST"); expect(prepare().hasAttribute("disabled")).toBe(true); expect(posts()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Proveri najnoviju reviziju" })); await waitFor(() => expect(prepare().hasAttribute("disabled")).toBe(false));
    expect(body().value).toBe("NE PREPISUJ LOKALNI TEKST"); accept(); await accepted(); expect(posts()[1].body.expected_revision).toBe(3); expect(posts()[1].body.command_id).not.toBe(posts()[0].body.command_id);
  });
  it("freezes editing during a delayed concurrency refresh and never applies server wording to local input", async () => {
    mount(); await loaded(); fireEvent.change(body(), { target: { value: "LOKALNI TEKST" } }); head = savedDraft({ ...publishingPayload(), body: "REMOTE TEXT" }, 4);
    accept(); await screen.findByText(/Sukob revizija ili promenjeno stanje/);
    const pending = deferred<Response>(); getOverride = call => call.path === "/api/editorial/drafts" ? pending.promise : null;
    fireEvent.click(screen.getByRole("button", { name: "Proveri najnoviju reviziju" })); expect(body().readOnly).toBe(true);
    fireEvent.change(body(), { target: { value: "REJECTED DURING REFRESH" } }); expect(body().value).toBe("LOKALNI TEKST");
    await act(async () => pending.resolve(json(head))); await waitFor(() => expect(body().readOnly).toBe(false)); expect(body().value).toBe("LOKALNI TEKST"); expect(screen.getByText("Nesačuvane lokalne izmene.")).toBeTruthy(); expect(posts()).toHaveLength(1);
  });
  it("requires explicit correction of existing images attributed to another article", async () => {
    const payload = publishingPayload(); payload.images = [{ url: "https://media.invalid/image.jpg", alt: "Opis fotografije", credit: "Portal One", source_article_id: sourceRows[0].article_id }]; head = savedDraft(payload);
    suggestion = aiSuggestion(1, { article_id: sourceRows[1].article_id, source_id: sourceRows[1].source_id }); mount(); await loaded(); fireEvent.click(prepare());
    expect(screen.getByText("Choose a selected source article for this image.")).toBeTruthy(); expect(posts()).toHaveLength(0);
    expect((screen.getByLabelText(/^Featured image URL/) as HTMLTextAreaElement).value).toBe(payload.images[0].url);
    fireEvent.change(screen.getByLabelText(/^Image 1 source article/), { target: { value: sourceRows[1].article_id } }); accept(); await accepted();
    expect(posts()[0].body.payload.images[0]).toEqual({ ...payload.images[0], source_article_id: sourceRows[1].article_id });
  });
  it.each([422, 503])("handles acceptance HTTP %s without false success, silent edits or automatic retries", async status => {
    postOverride = async () => json({ detail: "SENSITIVE DATABASE" }, status); mount(); await loaded(); fireEvent.change(body(), { target: { value: "Lokalna korekcija" } }); accept();
    await screen.findByRole("alert"); expect(body().value).toBe("Lokalna korekcija"); expect(posts()).toHaveLength(1); expect(document.body.textContent).not.toContain("SENSITIVE DATABASE"); expect(screen.queryByLabelText("Potvrđeno AI prihvatanje")).toBeNull();
    expect(body().readOnly).toBe(status === 503);
  });
  it.each([401, 403])("clears all private content after acceptance HTTP %s", async status => {
    postOverride = async () => json({}, status); mount(); await loaded(); accept(); await screen.findByRole("button", { name: "Ponovo proveri pristup" });
    expect(screen.queryByRole("form")).toBeNull(); expect(screen.queryByTestId("ai-comparison")).toBeNull(); expect(screen.queryByLabelText("Potvrđeno AI prihvatanje")).toBeNull(); expect(posts()).toHaveLength(1);
  });
  it.each(["reader", "reviewer", "disabled"])("fails closed for %s capability without loading acceptance content", async kind => {
    permissions = kind === "disabled" ? ["editorial:read", "editorial:edit"] : kind === "reviewer" ? ["editorial:read", "editorial:review"] : ["editorial:read"]; commands = kind !== "disabled";
    mount(); await screen.findByText(/Prihvatanje zahteva Editor dozvolu/); expect(calls).toHaveLength(1); expect(screen.queryByRole("form")).toBeNull();
  });
  it.each([401, 403, 503])("does not edit when required draft context returns HTTP %s", async status => {
    getOverride = call => call.path === "/api/editorial/drafts" ? Promise.resolve(json({}, status)) : null; mount(); await screen.findByRole("alert");
    expect(screen.queryByRole("form")).toBeNull(); expect(posts()).toHaveLength(0);
  });
  it("keeps memory-mode and unconfigured identity unavailable", async () => {
    capabilityStatus = 503; const first = mount(); await screen.findByText(/Production editorial editing is unavailable/); expect(calls).toHaveLength(1); first.unmount(); calls = [];
    const router = createMemoryRouter([{ path: "*", element: <App /> }], { initialEntries: [`/review/${storyId}/ai/${suggestion.id}/edit`] });
    render(<DemoDataProvider><RouterProvider router={router} /></DemoDataProvider>); await screen.findByText(/Sign-in integration has not been configured/); expect(calls).toHaveLength(0);
  });
  it("rejects a suggestion belonging to another story", async () => {
    mount(new TestEditorialIdentity(), uuid(99)); await screen.findByRole("alert"); expect(screen.queryByRole("form")).toBeNull(); expect(posts()).toHaveLength(0);
  });
  it("clears a pending acceptance on logout and ignores its late successful response", async () => {
    const pending = deferred<Response>(); postOverride = async (_call, commit) => { const result = commit(); await pending.promise; return result; };
    const identity = new TestEditorialIdentity(); mount(identity); await loaded(); accept(); await waitFor(() => expect(posts()).toHaveLength(1));
    act(() => identity.changeSession(null)); await act(async () => pending.resolve(json({}))); expect(screen.queryByRole("form")).toBeNull(); expect(screen.queryByTestId("ai-comparison")).toBeNull(); expect(screen.queryByLabelText("Potvrđeno AI prihvatanje")).toBeNull();
  });
  it("guards unsaved internal navigation and unload without storing private input", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem"); const { router } = mount(); await loaded(); fireEvent.change(body(), { target: { value: "Unsaved private edit" } });
    const unload = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(unload); expect(unload.defaultPrevented).toBe(true);
    await act(async () => { await router.navigate("/review"); }); await screen.findByRole("alertdialog"); fireEvent.click(screen.getByRole("button", { name: "Ostani" })); expect(body().value).toBe("Unsaved private edit");
    expect(storage).not.toHaveBeenCalled(); expect(posts()).toHaveLength(0);
  });
  it("warns before leaving a pending acceptance and cannot restore its private result after navigation", async () => {
    const pending = deferred<Response>(); postOverride = async (_call, commit) => { const response = commit(); await pending.promise; return response; };
    const { router } = mount(); await loaded(); accept(); await waitFor(() => expect(posts()).toHaveLength(1));
    await act(async () => { await router.navigate("/review"); }); await screen.findByRole("alertdialog"); fireEvent.click(screen.getByRole("button", { name: "Ostani" })); expect(body().readOnly).toBe(true);
    await act(async () => { await router.navigate("/review"); }); fireEvent.click(screen.getByRole("button", { name: "Napusti stranicu" }));
    await act(async () => pending.resolve(json({}))); expect(screen.queryByRole("form")).toBeNull(); expect(screen.queryByLabelText("Potvrđeno AI prihvatanje")).toBeNull(); expect(posts()).toHaveLength(1);
  });
  it("refuses to confirm a version whose frozen text differs from the sealed suggestion", async () => {
    getOverride = call => /\/versions\/2$/.test(call.path) ? Promise.resolve(json({ ...versions.at(-1)!, sources: [{ ...versions.at(-1)!.sources[0], input_text: "CURRENT RECOLLECTED BODY" }] })) : null;
    mount(); await loaded(); accept(); await screen.findByRole("button", { name: "Potvrdi prihvaćenu verziju čitanjem" }); expect(screen.queryByLabelText("Potvrđeno AI prihvatanje")).toBeNull(); expect(posts()).toHaveLength(1);
  });
  it("rejects changed immutable hashes, origin or publishing payload during confirmation", () => {
    const command: AcceptAiSuggestion = { command_id: uuid(99), story_id: storyId, expected_revision: 1, payload: publishingPayload(), confirm_acceptance: true };
    const value = aiVersion(command, 2), plan = { command, draftId, versionNumber: 2, receipt: { command_id: command.command_id, draft_id: draftId, revision: 2, status: "editing" as const, version_number: 2, content_hash: value.content_hash } };
    expect(checkedAcceptedVersion(value, plan, suggestion.input.source)).toBe(value);
    for (const changed of [{ ...value, origin: "manual" }, { ...value, content_hash: "e".repeat(64) }, { ...value, payload: { ...value.payload, body: "OTHER BODY" } }, { ...value, payload: { ...value.payload, body: " " + value.payload.body } }]) expect(() => checkedAcceptedVersion(changed, plan, suggestion.input.source)).toThrow();
  });
});
