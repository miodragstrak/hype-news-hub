import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { DemoDataProvider } from "../src/context/DemoDataContext";
import * as news from "../src/services/newsService";
import { matchingApproval } from "../src/lib/editorialWorkflow";
import type { DraftStatus, EditorialAction, EditorialDraft, EditorialEvent, EditorialReceipt, EditorialVersion, PublishingPayload } from "../src/types/editorial";
import { draftId, publishingPayload, savedDraft, sourceRows, storyId, TestEditorialIdentity, uuid } from "./editorialFixtures";
import { deferred } from "./fixtures";
vi.mock("../src/services/newsService", async original => ({ ...await original<typeof import("../src/services/newsService")>(), isDemoDataModeEnabled: vi.fn(), getDiscoverySources: vi.fn(), getStories: vi.fn(), getEditorialQueue: vi.fn() }));
type Call = { path: string; query: URLSearchParams; body: Record<string, unknown>; init: RequestInit };
let head: EditorialDraft, versions: EditorialVersion[], events: EditorialEvent[], permissions: string[], calls: Call[], capabilityStatus: number;
let getOverride: ((call: Call) => Promise<Response> | null) | null;
let postOverride: ((call: Call, commit: () => Response) => Promise<Response>) | null;
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
const summary = (value: EditorialVersion) => { const { payload: _payload, sources, ...metadata } = value; return { ...metadata, source_count: sources.length }; };
function version(number: number) { const value = savedDraft({ ...publishingPayload(), body: `PRIVATE VERSION BODY ${number}` }, number).current_version!; value.sources[0].input_text = `EXACT FROZEN ${number} <script>unsafe()</script>`; return value; }
function state(status: DraftStatus, revision = 1) { head = { ...savedDraft(), status, revision, effective_approval: status === "approved", current_version: versions[versions.length - 1] }; }
function mount(view = "decisions", identity: TestEditorialIdentity | undefined = new TestEditorialIdentity()) {
  const router = createMemoryRouter([{ path: "*", element: <App editorialIdentity={identity} /> }], { initialEntries: [`/review/${storyId}/${view}`] });
  return { ...render(<DemoDataProvider><RouterProvider router={router} /></DemoDataProvider>), router, identity };
}
const posts = () => calls.filter(call => call.init.method === "POST");
const reason = () => screen.getByLabelText(/^Obrazloženje/) as HTMLTextAreaElement;
async function loaded() { await screen.findByText(/Sačuvano stanje:/); }
function event(receipt: EditorialReceipt, action: string): EditorialEvent { return { id: uuid(900 + events.length), event_type: `draft.${action}`, from_status: "in_review", to_status: receipt.status, version_number: receipt.version_number, command_id: receipt.command_id, actor_issuer: "urn:verified", actor_subject: "reviewer-from-server", occurred_at: "2026-10-31T12:00:00Z", details: { result: receipt } }; }
beforeEach(() => {
  versions = [version(1)]; state("editing"); events = []; permissions = ["editorial:read", "editorial:edit", "editorial:submit"]; calls = []; capabilityStatus = 200; getOverride = null; postOverride = null;
  vi.mocked(news.isDemoDataModeEnabled).mockReturnValue(false); vi.mocked(news.getDiscoverySources).mockResolvedValue([]); vi.mocked(news.getStories).mockResolvedValue({ stories: [], stories_total: 0 }); vi.mocked(news.getEditorialQueue).mockResolvedValue({ stories: [], stories_total: 0 });
  const receipts = new Map<string, EditorialReceipt>();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input)); const call = { path: url.pathname, query: url.searchParams, body: init.body ? JSON.parse(String(init.body)) : {}, init }; calls.push(call);
    if (call.path.endsWith("/capabilities")) return json({ roles: ["reader"], permissions, commands_enabled: permissions.length > 1, storage: "postgres" }, capabilityStatus);
    if (init.method === "POST") {
      const commit = () => {
        const id = String(call.body.command_id); if (receipts.has(id)) return json(receipts.get(id));
        if (call.body.expected_revision !== head.revision) return json({}, 409);
        const action = call.path.split("/").at(-1)!;
        const targets: Record<string, DraftStatus> = { submit: "in_review", approve: "approved", "request-changes": "changes_requested", reject: "rejected", reopen: "editing", revisions: "editing" };
        if (action === "revisions") versions.push(savedDraft(call.body.payload as PublishingPayload, versions.length + 1).current_version!);
        head = { ...head, revision: head.revision + 1, status: targets[action], effective_approval: action === "approve", current_version: versions[versions.length - 1] };
        const receipt: EditorialReceipt = { command_id: id, draft_id: head.id, revision: head.revision, status: head.status, version_number: head.current_version!.version_number, content_hash: head.current_version!.content_hash };
        receipts.set(id, receipt); const row = event(receipt, action.replace("-", "_")); if (call.body.reason) row.details.reason = call.body.reason; events.push(row); return json(receipt);
      };
      return postOverride ? postOverride(call, commit) : commit();
    }
    const override = getOverride?.(call); if (override) return override;
    if (call.path.endsWith("/sources")) return json(sourceRows);
    if (call.path.endsWith("/events")) { const offset = Number(call.query.get("offset") || 0), limit = Number(call.query.get("limit") || 50); return json(events.slice(offset, offset + limit)); }
    if (call.path.endsWith("/versions")) { const offset = Number(call.query.get("offset") || 0), limit = Number(call.query.get("limit") || 20); return json(versions.slice(offset, offset + limit).map(summary)); }
    if (/\/versions\/\d+$/.test(call.path)) return json(versions.find(row => row.version_number === Number(call.path.split("/").at(-1))));
    return json(head);
  }));
});

describe("version summaries and frozen history", () => {
  it("paginates lightweight summaries and loads historical evidence only on demand", async () => {
    permissions = ["editorial:read"]; versions = Array.from({ length: 23 }, (_, index) => version(index + 1)); state("editing", 23);
    mount("history"); await screen.findByRole("button", { name: "Prikaži verziju 1" });
    expect(screen.getAllByRole("button", { name: /^Prikaži verziju/ })).toHaveLength(20); expect(calls.filter(call => /\/versions\/\d+$/.test(call.path))).toHaveLength(0); expect(screen.queryByText(/EXACT FROZEN/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sledeća stranica" })); await screen.findByRole("button", { name: "Prikaži verziju 23" });
    expect(calls.filter(call => call.path.endsWith("/versions")).at(-1)?.query.get("offset")).toBe("20");
    fireEvent.click(screen.getByRole("button", { name: "Prikaži verziju 21" })); await screen.findByText("EXACT FROZEN 21 <script>unsafe()</script>");
    expect(document.querySelector("script")).toBeNull(); expect(screen.getByRole("article", { name: "Arhivski pregled" })).toBeTruthy(); expect(calls.filter(call => /\/versions\/\d+$/.test(call.path))).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Prethodna stranica" })); await screen.findByRole("button", { name: "Prikaži verziju 1" }); expect(screen.queryByRole("article")).toBeNull();
  });
  it("enforces page-size choices without fetching detail payloads", async () => {
    mount("history"); await screen.findByRole("button", { name: "Prikaži verziju 1" }); fireEvent.change(screen.getByLabelText("Verzija po stranici"), { target: { value: "50" } });
    await waitFor(() => expect(calls.filter(call => call.path.endsWith("/versions")).at(-1)?.query.get("limit")).toBe("50")); expect(calls.filter(call => /\/versions\/\d+$/.test(call.path))).toHaveLength(0);
  });
  it.each([422, 401, 403])("handles detail failure %s without exposing a prior snapshot or error body", async status => {
    mount("history"); await screen.findByRole("button", { name: "Prikaži verziju 1" }); getOverride = call => /\/versions\/\d+$/.test(call.path) ? Promise.resolve(json({ detail: "SENSITIVE INTERNAL" }, status)) : null;
    fireEvent.click(screen.getByRole("button", { name: "Prikaži verziju 1" })); await screen.findByRole("alert"); expect(screen.queryByRole("article")).toBeNull(); expect(document.body.textContent).not.toContain("SENSITIVE INTERNAL");
    if (status !== 422) expect(screen.queryByRole("button", { name: "Prikaži verziju 1" })).toBeNull();
  });
  it("rejects a detail response with another immutable identity", async () => {
    mount("history"); await screen.findByRole("button", { name: "Prikaži verziju 1" }); getOverride = call => /\/versions\/\d+$/.test(call.path) ? Promise.resolve(json({ ...versions[0], id: uuid(9999) })) : null;
    fireEvent.click(screen.getByRole("button", { name: "Prikaži verziju 1" })); await screen.findByRole("alert"); expect(screen.queryByRole("article")).toBeNull();
  });
  it("ignores historical details arriving after logout", async () => {
    const identity = new TestEditorialIdentity(); mount("history", identity); await screen.findByRole("button", { name: "Prikaži verziju 1" });
    const pending = deferred<Response>(); getOverride = call => /\/versions\/\d+$/.test(call.path) ? pending.promise : null;
    fireEvent.click(screen.getByRole("button", { name: "Prikaži verziju 1" })); await waitFor(() => expect(calls.some(call => /\/versions\/\d+$/.test(call.path))).toBe(true));
    act(() => identity.changeSession(null)); await act(async () => pending.resolve(json(versions[0])));
    expect(screen.queryByRole("article")).toBeNull(); expect(screen.queryByRole("button", { name: "Prikaži verziju 1" })).toBeNull();
  });
});

describe("server-confirmed editorial decisions", () => {
  it("submits only after confirmation and waits for a fresh server read", async () => {
    mount(); await loaded(); const read = deferred<Response>(); getOverride = call => call.path === `/api/editorial/drafts/${draftId}` ? read.promise : null;
    fireEvent.click(screen.getByRole("button", { name: "Pošalji na pregled" })); expect(posts()).toHaveLength(0); fireEvent.click(screen.getByRole("button", { name: "Potvrdi odluku" }));
    await waitFor(() => expect(posts()).toHaveLength(1)); expect(posts()[0].body).toEqual({ command_id: expect.any(String), expected_revision: 1, version_number: 1, content_hash: versions[0].content_hash }); expect(screen.queryByText(/Server je potvrdio stanje/)).toBeNull();
    await act(async () => read.resolve(json(head))); await screen.findByText(/Server je potvrdio stanje: Na pregledu/); expect(calls.some(call => call.path === `/api/editorial/drafts/${draftId}`)).toBe(true);
  });
  it.each(["approve", "request-changes", "reject"] as EditorialAction[])("performs Reviewer action %s with bound version/hash and reasoning", async action => {
    state("in_review"); permissions = ["editorial:read", "editorial:review"]; mount(); await loaded();
    const label = { approve: "Odobri", "request-changes": "Zatraži izmene", reject: "Odbij" }[action as "approve" | "request-changes" | "reject"];
    if (action !== "approve") { fireEvent.click(screen.getByRole("button", { name: label })); expect(screen.getByText("Unesite obrazloženje odluke.")).toBeTruthy(); expect(posts()).toHaveLength(0); }
    fireEvent.change(reason(), { target: { value: "Proverene činjenice i jasno obrazloženje." } }); fireEvent.click(screen.getByRole("button", { name: label })); const confirm = screen.getByRole("button", { name: "Potvrdi odluku" }); act(() => { fireEvent.click(confirm); fireEvent.click(confirm); });
    await screen.findByText(/Server je potvrdio stanje/); expect(posts()).toHaveLength(1); expect(posts()[0].path.endsWith(action)).toBe(true); expect(posts()[0].body).toMatchObject({ expected_revision: 1, version_number: 1, content_hash: versions[0].content_hash, reason: "Proverene činjenice i jasno obrazloženje." }); expect(events).toHaveLength(1);
  });
  it.each(["changes_requested", "rejected"] as DraftStatus[])("reopens %s with Editor permission and a required reason", async initial => {
    state(initial, 3); mount(); await loaded(); fireEvent.click(screen.getByRole("button", { name: "Ponovo otvori" })); expect(posts()).toHaveLength(0);
    fireEvent.change(reason(), { target: { value: "Dopunjene informacije." } }); fireEvent.click(screen.getByRole("button", { name: "Ponovo otvori" })); fireEvent.click(screen.getByRole("button", { name: "Potvrdi odluku" })); await screen.findByText(/Server je potvrdio stanje: Uređivanje/); expect(posts()[0].body).toMatchObject({ expected_revision: 3, version_number: 1, reason: "Dopunjene informacije." }); expect(versions).toHaveLength(1);
  });
  it("lets an Editor continue requested changes with a new content version", async () => {
    state("changes_requested", 2); mount(); await loaded(); fireEvent.click(screen.getByRole("link", { name: "Nastavi uređivanje traženih izmena" })); await screen.findByRole("form");
    fireEvent.change(screen.getByLabelText(/^Body/), { target: { value: "Dopunjen sadržaj." } }); fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await screen.findByText(/Saved version 2/); expect(head.status).toBe("editing"); expect(head.revision).toBe(3); expect(head.effective_approval).toBe(false);
  });
  it.each(["reader", "editor", "reviewer"])("exposes only permitted in-review actions for %s", async role => {
    state("in_review"); permissions = role === "reader" ? ["editorial:read"] : role === "editor" ? ["editorial:read", "editorial:edit", "editorial:submit"] : ["editorial:read", "editorial:review"];
    mount(); await loaded(); expect(Boolean(screen.queryByRole("button", { name: "Odobri" }))).toBe(role === "reviewer"); expect(screen.queryByRole("button", { name: "Pošalji na pregled" })).toBeNull(); expect(screen.queryByRole("button", { name: "Ponovo otvori" })).toBeNull();
  });
  it("retains reasoning on 409 until explicit reload and a new confirmation", async () => {
    state("in_review"); permissions = ["editorial:read", "editorial:review"]; mount(); await loaded(); fireEvent.change(reason(), { target: { value: "KEEP LOCAL REASON" } }); postOverride = async () => { state("in_review", 2); return json({}, 409); };
    fireEvent.click(screen.getByRole("button", { name: "Odobri" })); fireEvent.click(screen.getByRole("button", { name: "Potvrdi odluku" })); await screen.findByRole("heading", { name: "Sukob revizija" }); expect(reason().value).toBe("KEEP LOCAL REASON"); expect(screen.getByRole("button", { name: "Odobri" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Učitaj najnovije stanje" })); fireEvent.click(screen.getByRole("button", { name: "Učitaj i proveri" })); await waitFor(() => expect(screen.getByRole("button", { name: "Odobri" }).hasAttribute("disabled")).toBe(false)); expect(reason().value).toBe("KEEP LOCAL REASON"); postOverride = null;
    fireEvent.click(screen.getByRole("button", { name: "Odobri" })); fireEvent.click(screen.getByRole("button", { name: "Potvrdi odluku" })); await screen.findByText(/Server je potvrdio stanje: Odobreno/); expect(posts()[1].body.expected_revision).toBe(2);
  });
  it.each(["before", "after"])("retries the identical uncertain command after a failure %s commit", async timing => {
    state("in_review"); permissions = ["editorial:read", "editorial:review"]; mount(); await loaded(); let first = true;
    postOverride = async (_call, commit) => { if (first) { first = false; if (timing === "after") commit(); throw new Error("lost network"); } return commit(); };
    fireEvent.click(screen.getByRole("button", { name: "Odobri" })); fireEvent.click(screen.getByRole("button", { name: "Potvrdi odluku" })); await screen.findByRole("button", { name: "Ponovi istu komandu" }); expect(screen.queryByText(/Server je potvrdio stanje/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ponovi istu komandu" })); await screen.findByText(/Server je potvrdio stanje: Odobreno/); expect(posts()[1].body).toEqual(posts()[0].body); expect(events).toHaveLength(1);
  });
  it("retries confirmation by GET without repeating an acknowledged decision", async () => {
    state("in_review"); permissions = ["editorial:read", "editorial:review"]; mount(); await loaded(); let once = true; getOverride = call => call.path === `/api/editorial/drafts/${draftId}` && once ? (once = false, Promise.resolve(json({}, 503))) : null;
    fireEvent.click(screen.getByRole("button", { name: "Odobri" })); fireEvent.click(screen.getByRole("button", { name: "Potvrdi odluku" })); await screen.findByRole("button", { name: "Potvrdi stanje čitanjem" }); fireEvent.click(screen.getByRole("button", { name: "Potvrdi stanje čitanjem" })); await screen.findByText(/Server je potvrdio stanje: Odobreno/); expect(posts()).toHaveLength(1);
  });
  it("never treats a replayed historical approval as current after later rejection", async () => {
    state("in_review"); permissions = ["editorial:read", "editorial:review"]; mount(); await loaded(); let first = true;
    postOverride = async (_call, commit) => { if (first) { first = false; commit(); throw new Error("lost reply"); } return commit(); };
    fireEvent.click(screen.getByRole("button", { name: "Odobri" })); fireEvent.click(screen.getByRole("button", { name: "Potvrdi odluku" })); await screen.findByRole("button", { name: "Ponovi istu komandu" }); versions.push(version(2)); state("rejected", 6);
    fireEvent.click(screen.getByRole("button", { name: "Ponovi istu komandu" })); await screen.findByText(/Komanda je zabeležena, a stanje se u međuvremenu promenilo/); expect(screen.getByText(/Aktuelno odobrenje prema serveru: Ne/)).toBeTruthy(); expect(head.status).toBe("rejected"); expect(events[0].event_type).toBe("draft.approve");
  });
  it.each([401, 403, 422])("handles decision failure %s without claiming success", async status => {
    state("in_review"); permissions = ["editorial:read", "editorial:review"]; mount(); await loaded(); fireEvent.change(reason(), { target: { value: "LOCAL PRIVATE REASON" } }); postOverride = async () => json({ detail: "SENSITIVE CONNECTION" }, status);
    fireEvent.click(screen.getByRole("button", { name: "Odobri" })); fireEvent.click(screen.getByRole("button", { name: "Potvrdi odluku" })); await screen.findByRole("alert"); expect(screen.queryByText(/Server je potvrdio stanje/)).toBeNull(); expect(document.body.textContent).not.toContain("SENSITIVE CONNECTION");
    if (status === 422) expect(reason().value).toBe("LOCAL PRIVATE REASON"); else expect(screen.queryByLabelText(/^Obrazloženje/)).toBeNull();
  });
  it("clears pending decisions on logout and ignores their late response", async () => {
    state("in_review"); permissions = ["editorial:read", "editorial:review"]; const identity = new TestEditorialIdentity(); mount("decisions", identity); await loaded(); const pending = deferred<Response>(); postOverride = async (_call, commit) => { const response = commit(); void response; return pending.promise; };
    fireEvent.click(screen.getByRole("button", { name: "Odobri" })); fireEvent.click(screen.getByRole("button", { name: "Potvrdi odluku" })); await waitFor(() => expect(posts()).toHaveLength(1)); act(() => identity.changeSession(null)); await screen.findByText(/Sign in through your newsroom identity provider/);
    await act(async () => pending.resolve(json(events[0].details.result))); expect(screen.queryByRole("article")).toBeNull(); expect(screen.queryByText(/Server je potvrdio stanje/)).toBeNull(); expect(screen.queryByText(/reviewer-from-server/)).toBeNull();
  });
  it("paginates append-only audit records and keeps historical decision reasons visible", async () => {
    events = Array.from({ length: 23 }, (_, index) => ({ id: uuid(5000 + index), event_type: index === 0 ? "draft.approve" : "draft.reopen", from_status: "in_review", to_status: "editing", version_number: 1, command_id: uuid(6000 + index), actor_issuer: "urn:verified", actor_subject: "actor", occurred_at: "2026-10-31T12:00:00Z", details: { reason: `HISTORICAL REASON ${index}` } }));
    mount(); await loaded(); await screen.findByText("Obrazloženje: HISTORICAL REASON 0");
    fireEvent.click(screen.getByRole("button", { name: "Sledeća stranica" })); await screen.findByText("Obrazloženje: HISTORICAL REASON 22");
    expect(calls.filter(call => call.path.endsWith("/events")).at(-1)?.query.get("offset")).toBe("20"); expect(events).toHaveLength(23); expect(posts()).toHaveLength(0);
  });
  it("warns before navigating away from a local decision reason", async () => {
    state("in_review"); permissions = ["editorial:read", "editorial:review"]; mount(); await loaded(); fireEvent.change(reason(), { target: { value: "KEEP UNSENT REASON" } });
    const unload = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(unload); expect(unload.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole("link", { name: "Istorija verzija" })); await screen.findByRole("alertdialog"); fireEvent.click(screen.getByRole("button", { name: "Ostani" })); expect(reason().value).toBe("KEEP UNSENT REASON"); expect(posts()).toHaveLength(0);
  });
});

describe("effective approved preview", () => {
  it("pins immutable content, verifies the current head twice and shows matching approval metadata", async () => {
    state("approved", 2); const receipt: EditorialReceipt = { command_id: uuid(888), draft_id: draftId, revision: 2, status: "approved", version_number: 1, content_hash: versions[0].content_hash }; events = [event(receipt, "approve")];
    mount("approved"); await screen.findByRole("article", { name: "Odobreni pregled — nepromenljiva verzija" }); expect(screen.getByText(/Odobrio: reviewer-from-server/)).toBeTruthy(); expect(calls.filter(call => /\/versions\/\d+$/.test(call.path)).map(call => call.path)).toEqual([`/api/editorial/drafts/${draftId}/versions/1`]); expect(calls.some(call => call.path === `/api/editorial/drafts/${draftId}`)).toBe(true); expect(screen.getByRole("button", { name: "Objavljivanje nije dostupno" }).hasAttribute("disabled")).toBe(true); expect(posts()).toHaveLength(0);
  });
  it("does not infer effective approval from status or historical events", async () => {
    state("approved", 2); head.effective_approval = false; mount("approved"); await screen.findByText(/Nema efektivno odobrene/); expect(screen.queryByRole("article")).toBeNull(); expect(calls.some(call => /\/versions\/\d+$/.test(call.path))).toBe(false);
  });
  it("hides a preview if approval changes during lazy detail loading", async () => {
    state("approved", 2); const pending = deferred<Response>(); getOverride = call => /\/versions\/\d+$/.test(call.path) ? pending.promise : null; mount("approved"); await waitFor(() => expect(calls.some(call => /\/versions\/\d+$/.test(call.path))).toBe(true)); state("editing", 3);
    await act(async () => pending.resolve(json(versions[0]))); await screen.findByText(/Odobrenje se promenilo tokom učitavanja/); expect(screen.queryByRole("article")).toBeNull();
  });
  it.each(["editing", "approved"] as DraftStatus[])("clears the pinned preview on a newer %s head without silently switching versions", async status => {
    state("approved", 2); mount("approved"); await screen.findByRole("article", { name: "Odobreni pregled — nepromenljiva verzija" }); versions.push(version(2)); state(status, 3); fireEvent(window, new Event("focus"));
    await screen.findByText(/Aktuelno odobrenje se promenilo/); expect(screen.queryByRole("article")).toBeNull(); expect(calls.some(call => call.path.endsWith("/versions/2"))).toBe(false);
    if (status === "approved") { fireEvent.click(screen.getByRole("button", { name: "Učitaj trenutno odobrenu verziju" })); await screen.findByRole("article", { name: "Odobreni pregled — nepromenljiva verzija" }); expect(screen.getByText("PRIVATE VERSION BODY 2")).toBeTruthy(); }
  });
  it("invalidates approval after an Editor saves subsequent content", async () => {
    state("approved", 2); mount("edit"); await screen.findByRole("form"); fireEvent.change(screen.getByLabelText(/^Body/), { target: { value: "UNAPPROVED NEW CONTENT" } }); fireEvent.click(screen.getByRole("button", { name: "Save revision" })); await screen.findByText(/Saved version 2/); fireEvent.click(screen.getByRole("link", { name: "Odobreni pregled" })); await screen.findByText(/Nema efektivno odobrene/); expect(screen.queryByRole("article")).toBeNull(); expect(head.effective_approval).toBe(false);
  });
  it.each([403, 503])("hides approved content when revalidation fails with %s", async status => {
    state("approved", 2); mount("approved"); await screen.findByRole("article", { name: "Odobreni pregled — nepromenljiva verzija" }); getOverride = call => call.path === `/api/editorial/drafts/${draftId}` ? Promise.resolve(json({}, status)) : null; fireEvent(window, new Event("focus")); await screen.findByRole("alert"); expect(screen.queryByRole("article")).toBeNull();
  });
  it("does not attribute a different draft's approval event to this version", () => {
    state("approved", 2); const receipt: EditorialReceipt = { command_id: uuid(888), draft_id: uuid(999), revision: 2, status: "approved", version_number: 1, content_hash: versions[0].content_hash }; expect(matchingApproval([event(receipt, "approve")], head)).toBeUndefined();
  });
  it("rechecks the authoritative head on the visible-page timer", async () => {
    const interval = vi.spyOn(globalThis, "setInterval");
    state("approved", 2); mount("approved"); await screen.findByRole("article", { name: "Odobreni pregled — nepromenljiva verzija" });
    const tick = interval.mock.calls.find(([, delay]) => delay === 30_000)?.[0]; expect(typeof tick).toBe("function");
    state("editing", 3);
    await act(async () => { if (typeof tick === "function") tick(); });
    await screen.findByText(/Aktuelno odobrenje se promenilo/); expect(screen.queryByRole("article")).toBeNull();
  });
});
