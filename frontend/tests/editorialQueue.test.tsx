import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { DemoDataProvider } from "../src/context/DemoDataContext";
import { checkedPrivateQueue } from "../src/lib/editorialQueue";
import { EditorialApi } from "../src/services/editorialApi";
import { installSessionTransport } from "../src/services/sessionTransport";
import * as news from "../src/services/newsService";
import type { PrivateEditorialQueue, PrivateQueueStory } from "../src/types/editorialQueue";
import type { AiStatus } from "../src/types/ai";
import { TestEditorialIdentity, uuid } from "./editorialFixtures";
import { deferred, editorial } from "./fixtures";

vi.mock("../src/services/newsService", async original => ({ ...await original<typeof import("../src/services/newsService")>(),
  isDemoDataModeEnabled: vi.fn(), getDiscoverySources: vi.fn(), getStories: vi.fn(), getEditorialQueue: vi.fn(),
}));
const row = (number = 1, changes: Partial<PrivateQueueStory> = {}): PrivateQueueStory => ({ ...editorial,
  id: uuid(number), headline: `Privatna priča ${number}`, published_at: "2026-11-06T09:00:00Z",
  editorial: null, ai: { has_suggestion: false, latest_suggestion_id: null, status: null, created_at: null, completed_at: null, recovery_required: false }, ...changes });
const ai = (status: AiStatus, recovery_required = false): PrivateQueueStory["ai"] => ({ has_suggestion: true,
  latest_suggestion_id: uuid(900), status, created_at: "2026-11-06T09:00:00Z", completed_at: status === "processing" ? null : "2026-11-06T09:01:00Z", recovery_required });
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
let rows: PrivateQueueStory[], calls: { path: string; query: URLSearchParams; init: RequestInit }[], permissions: string[];
let queueResponse: ((limit: number, offset: number) => Promise<Response>) | null;
let capabilityStatus: number;
function mount(identity: TestEditorialIdentity | undefined = new TestEditorialIdentity()) {
  const router = createMemoryRouter([{ path: "*", element: <App editorialIdentity={identity} /> }], { initialEntries: ["/review"] });
  return { ...render(<DemoDataProvider><RouterProvider router={router} /></DemoDataProvider>), router };
}
const queueCalls = () => calls.filter(call => call.path === "/api/editorial/queue");
const waitQueue = () => screen.findByRole("list", { name: "Priče u uredničkom redu" });
const snapshot = (limit = 20, offset = 0): PrivateEditorialQueue => ({ stories: rows.slice(offset, offset + limit), stories_total: rows.length,
  limit, offset, has_more: offset + Math.min(limit, Math.max(0, rows.length - offset)) < rows.length });
beforeEach(() => {
  rows = [row()]; calls = []; permissions = ["editorial:read"]; queueResponse = null; capabilityStatus = 200;
  installSessionTransport(null);
  vi.mocked(news.isDemoDataModeEnabled).mockReturnValue(false);
  vi.mocked(news.getDiscoverySources).mockResolvedValue([]);
  vi.mocked(news.getStories).mockResolvedValue({ stories: [], stories_total: 0 });
  // A public story must never leak into the private view, including on failures.
  vi.mocked(news.getEditorialQueue).mockResolvedValue({ stories: [{ ...editorial, headline: "PUBLIC FALLBACK MUST NOT APPEAR" }], stories_total: 1 });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input)); calls.push({ path: url.pathname, query: url.searchParams, init });
    if (url.pathname.endsWith("/capabilities")) return json({ roles: ["reader"], permissions, storage: "postgres", commands_enabled: false }, capabilityStatus);
    if (url.pathname === "/api/editorial/queue") {
      const limit = Number(url.searchParams.get("limit")), offset = Number(url.searchParams.get("offset"));
      return queueResponse ? queueResponse(limit, offset) : json(snapshot(limit, offset));
    }
    throw Error("Unexpected request");
  }));
});

describe("operational private editorial queue", () => {
  it("uses authenticated read-only transport and never displays public fallback stories", async () => {
    const local = vi.spyOn(Storage.prototype, "setItem");
    mount(); const list = await waitQueue();
    expect(list.textContent).toContain("Privatna priča 1"); expect(document.body.textContent).not.toContain("PUBLIC FALLBACK");
    expect(queueCalls()).toHaveLength(1);
    expect(queueCalls()[0].init).toMatchObject({ method: "GET", credentials: "omit", cache: "no-store", redirect: "error",
      headers: { Authorization: "Bearer fixture-editor-token" } });
    expect(calls.every(call => call.init.method === "GET")).toBe(true); expect(local).not.toHaveBeenCalled();
  });
  it("shows separate collection, editorial and every supported AI status without mutation actions", async () => {
    rows = [row(1), ...(["processing", "succeeded", "failed", "interrupted", "rejected", "accepted"] as AiStatus[]).map((status, index) => row(index + 2, {
      status: "collected", ai: ai(status, status === "processing"), editorial: { draft_id: uuid(index + 100), status: index ? "editing" : "approved", revision: 2, current_version_number: 1 },
    }))];
    mount(); const list = await waitQueue();
    for (const label of ["Nije započeto", "Nema AI predloga", "Prikupljeno", "Odobreno", "Uređivanje", "Obrada je u toku", "Predlog je spreman za proveru", "Obrada nije uspela", "Obrada je prekinuta", "Odbijen AI predlog", "Prihvaćen u uredničku verziju"]) expect(list.textContent).toContain(label);
    expect(list.textContent).toContain("Ova oznaka ne daje dozvolu za oporavak");
    expect(screen.queryByRole("button", { name: /Generiši|Oporavi|Prihvati|Odobri|Objavi/ })).toBeNull();
    expect(screen.getAllByText(/Izvori:/)).toHaveLength(7);
  });
  it("filters by headline, editorial state and AI state only within the loaded page", async () => {
    rows = [row(1, { headline: "Festival u Beogradu" }), row(2, { headline: "Festival u Nišu", ai: ai("processing", true),
      editorial: { draft_id: uuid(102), status: "in_review", revision: 2, current_version_number: 1 } }), row(3)];
    mount(); await waitQueue();
    fireEvent.change(screen.getByLabelText("Pretraga naslova"), { target: { value: "FESTIVAL" } });
    expect(screen.getByText("Prikazano posle filtera: 2 od 3 priča na učitanoj stranici.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Urednički status"), { target: { value: "in_review" } });
    fireEvent.change(screen.getByLabelText("AI status"), { target: { value: "recovery" } });
    expect(screen.getByText("Festival u Nišu")).toBeTruthy(); expect(screen.queryByText("Festival u Beogradu")).toBeNull();
    expect(screen.getByText("Ukupno sačuvanih priča: 3. Učitano na ovoj stranici: 3.")).toBeTruthy();
    expect(screen.getByText(/filteri važe samo za učitanu stranicu/)).toBeTruthy(); expect(queueCalls()).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("AI status"), { target: { value: "succeeded" } });
    expect(screen.getByText(/Nema podudaranja/)).toBeTruthy();
  });
  it("paginates with server metadata and has_more, including a full final page", async () => {
    rows = Array.from({ length: 40 }, (_, index) => row(index + 1)); mount(); await waitQueue();
    expect(screen.getAllByRole("link", { name: "Pregled priče" })).toHaveLength(20);
    fireEvent.click(screen.getByRole("button", { name: "Sledeća stranica" })); await screen.findByText("Privatna priča 40");
    expect(queueCalls()[1].query.toString()).toBe("limit=20&offset=20");
    expect(screen.getByRole("button", { name: "Sledeća stranica" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Prethodna stranica" })); await screen.findByText("Privatna priča 1");
    fireEvent.change(screen.getByLabelText("Priča po stranici"), { target: { value: "5" } }); await waitFor(() => expect(screen.getAllByRole("link", { name: "Pregled priče" })).toHaveLength(5));
    expect(queueCalls().at(-1)?.query.toString()).toBe("limit=5&offset=0");
  });
  it("links to existing story review and AI workspace with the persisted UUID", async () => {
    mount(); await waitQueue(); expect(screen.getByRole("link", { name: "Pregled priče" }).getAttribute("href")).toBe(`/review/${uuid(1)}`);
    expect(screen.getByRole("link", { name: "AI radni prostor" }).getAttribute("href")).toBe(`/review/${uuid(1)}/ai`);
    expect(calls.some(call => call.init.method === "POST")).toBe(false);
  });
  it("shows a loading state without public content until the private response arrives", async () => {
    const pending = deferred<Response>(); queueResponse=()=>pending.promise; mount();
    await screen.findByText("Učitavanje privatnog uredničkog reda…");
    expect(screen.queryByRole("list",{name:"Priče u uredničkom redu"})).toBeNull();
    expect(document.body.textContent).not.toContain("PUBLIC FALLBACK");
    await act(async()=>pending.resolve(json(snapshot()))); await waitQueue();
  });
  it("shows an empty queue and zero total without inventing stories", async () => {
    rows = []; mount(); await screen.findByText("Nema priča na ovoj stranici."); expect(screen.getByText("Ukupno sačuvanih priča: 0. Učitano na ovoj stranici: 0.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sledeća stranica" }).hasAttribute("disabled")).toBe(true);
  });
  it.each([401, 403, 503, 422, 0])("clears rows on refresh failure %s and permits an explicit retry without fallback", async status => {
    mount(); await waitQueue(); queueResponse = async () => { if (!status) throw Error("SENSITIVE NETWORK INFO"); return json({detail:"SENSITIVE SERVER INFO"},status); };
    fireEvent.click(screen.getByRole("button", { name: "Osveži red" })); await screen.findByRole("alert");
    expect(screen.queryByText("Privatna priča 1")).toBeNull(); expect(screen.queryByRole("list", { name: "Priče u uredničkom redu" })).toBeNull();
    expect(document.body.textContent).not.toContain("SENSITIVE"); expect(document.body.textContent).not.toContain("PUBLIC FALLBACK");
    queueResponse = null; fireEvent.click(screen.getByRole("button", { name: "Pokušaj ponovo" })); await waitQueue(); expect(queueCalls()).toHaveLength(3);
  });
  it("keeps unconfigured authentication unavailable without requesting a queue", async () => {
    const router = createMemoryRouter([{ path: "*", element: <App /> }], { initialEntries: ["/review"] });
    render(<DemoDataProvider><RouterProvider router={router} /></DemoDataProvider>);
    await screen.findByText(/Prijava nije podešena/); expect(queueCalls()).toHaveLength(0); expect(document.body.textContent).not.toContain("PUBLIC FALLBACK");
  });
  it.each([401,403,503])("does not request the queue when capabilities fail with %s", async status => {
    capabilityStatus=status; mount(); await screen.findByRole("alert"); expect(queueCalls()).toHaveLength(0);
  });
  it("requires read permission even when capability loading succeeds", async () => {
    permissions=[]; mount(); await screen.findByText(/Nemate dozvolu/); expect(queueCalls()).toHaveLength(0);
  });
  it("discards a pending queue response after logout and a reused session key", async () => {
    const pending = deferred<Response>(); queueResponse=()=>pending.promise; const identity = new TestEditorialIdentity(); mount(identity);
    await waitFor(()=>expect(queueCalls()).toHaveLength(1)); act(()=>identity.changeSession(null)); await screen.findByText(/Prijavite se za pregled/);
    rows=[row(2)];queueResponse=null;act(()=>identity.changeSession("test-session"));await screen.findByText("Privatna priča 2");
    await act(async()=>pending.resolve(json({...snapshot(),stories:[row(1)]})));expect(screen.queryByText("Privatna priča 1")).toBeNull();
  });
  it("aborts a pending request after navigation and ignores its late response", async () => {
    const pending=deferred<Response>();queueResponse=()=>pending.promise;const {router}=mount();await waitFor(()=>expect(queueCalls()).toHaveLength(1));
    await act(async()=>router.navigate("/collect"));await act(async()=>pending.resolve(json(snapshot())));
    expect(screen.queryByText("Privatna priča 1")).toBeNull();expect(queueCalls()[0].init.signal?.aborted).toBe(true);
  });
  it("clearly separates explicit demo mode even with an authenticated identity", async () => {
    vi.mocked(news.isDemoDataModeEnabled).mockReturnValue(true);
    vi.mocked(news.getEditorialQueue).mockResolvedValue({stories:[{...editorial,headline:"SAMPLE DEMO STORY"}],stories_total:1});
    mount();await screen.findByText("SAMPLE DEMO STORY"); expect(screen.getByText(/Ovo nisu podaci privatnog produkcionog reda/)).toBeTruthy();
    expect(screen.queryByText("Privatna priča 1")).toBeNull();expect(queueCalls()).toHaveLength(0);expect(screen.queryByRole("link",{name:"AI radni prostor"})).toBeNull();
  });
  it("rejects invalid identities, status and pagination data without rendering the response", async () => {
    queueResponse=async()=>json({...snapshot(),stories:[row(1,{id:"untrusted-id",headline:"UNVALIDATED PRIVATE ROW"})]});
    mount();await screen.findByRole("alert");expect(screen.queryByText("UNVALIDATED PRIVATE ROW")).toBeNull();
    for (const invalid of [{...snapshot(),limit:50},{...snapshot(),has_more:true},{...snapshot(),stories:[row(1,{ai:ai("succeeded",true)})]}]) {
      expect(()=>checkedPrivateQueue(invalid,20,0)).toThrow();
    }
  });
  it("preserves cookie-session transport rather than sending a bearer token or duplicating fetch", async () => {
    const transport=vi.fn(async (_path: string, _init?: RequestInit)=>json(snapshot()));installSessionTransport(transport);
    try {
      await new EditorialApi(async()=>"csrf-token","","session").queue(5,10);
      expect(transport).toHaveBeenCalledWith("/api/editorial/queue?limit=5&offset=10",expect.objectContaining({method:"GET",cache:"no-store"}));
      expect(transport.mock.calls[0][1]?.headers).not.toHaveProperty("Authorization");expect(calls).toHaveLength(0);
    } finally { installSessionTransport(null); }
  });
});
