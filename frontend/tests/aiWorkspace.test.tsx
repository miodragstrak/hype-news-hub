import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { DemoDataProvider } from "../src/context/DemoDataContext";
import { matchesSelectedAiRecovery, reconcilePendingAiCommand } from "../src/lib/aiSuggestions";
import { AiSuggestionComparison } from "../src/components/AiSuggestionComparison";
import * as news from "../src/services/newsService";
import type { AiSuggestion, CreateAiSuggestion } from "../src/types/ai";
import { aiSuggestion, aiSummary, collectedWorkspace } from "./aiFixtures";
import { savedDraft, sourceRows, storyId, TestEditorialIdentity, uuid } from "./editorialFixtures";
import { deferred } from "./fixtures";

vi.mock("../src/services/newsService", async original => ({ ...await original<typeof import("../src/services/newsService")>(), isDemoDataModeEnabled: vi.fn(), getDiscoverySources: vi.fn(), getStories: vi.fn(), getEditorialQueue: vi.fn() }));
type Call = { path: string; query: URLSearchParams; body: CreateAiSuggestion; init: RequestInit };
let calls: Call[], suggestions: AiSuggestion[], permissions: string[], capabilityStatus: number, commands: boolean, generationEnabled: boolean;
let capturedConfirmation: (() => void) | null = null;
vi.mock("../src/components/ConfirmDiscardDialog", async original => {
  const actual = await original<typeof import("../src/components/ConfirmDiscardDialog")>();
  return { ...actual, ConfirmDiscardDialog: (props: Parameters<typeof actual.ConfirmDiscardDialog>[0]) => {
    capturedConfirmation = props.onConfirm;
    return <actual.ConfirmDiscardDialog {...props} />;
  } };
});
let getOverride: ((call: Call) => Promise<Response> | null) | null;
let postOverride: ((call: Call, commit: () => Response) => Promise<Response>) | null;
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const posts = () => calls.filter(call => call.init.method === "POST");
function mount(identity: TestEditorialIdentity | null = new TestEditorialIdentity(), id = storyId) {
  const router = createMemoryRouter([{ path: "*", element: <App editorialIdentity={identity ?? undefined} /> }], { initialEntries: [`/review/${id}/ai`] });
  return { ...render(<DemoDataProvider><RouterProvider router={router} /></DemoDataProvider>), router };
}
const loaded = () => screen.findByLabelText("Izvor za novu obradu");
const generate = () => screen.getByRole("button", { name: "Generiši AI predlog" });
const commandFor = (value: AiSuggestion): CreateAiSuggestion => ({ command_id:value.command_id, story_id:value.story_id,
  article_id:value.article_id, source_id:value.source_id, target_locale:value.target_locale, mode:value.mode });
const pendingSuggestion = (changes: Partial<AiSuggestion> = {}) => {
  const value = aiSuggestion(1, {status:"processing",output_hash:null,...changes});
  value.recovery_command = commandFor(value); return value;
};
const recoverPersisted = () => {
  fireEvent.click(screen.getByRole("button", {name:"Oporavi postojeću obradu"}));
  fireEvent.click(screen.getByRole("button", {name:"Pošalji istu komandu"}));
};
const inspectFirst = () => fireEvent.click(screen.getAllByRole("button", { name: /^Prikaži predlog/ })[0]);
beforeEach(() => {
  capturedConfirmation = null; calls = []; suggestions = []; permissions = ["editorial:read", "editorial:edit"]; capabilityStatus = 200; commands = true; generationEnabled = true; getOverride = null; postOverride = null;
  vi.mocked(news.isDemoDataModeEnabled).mockReturnValue(false); vi.mocked(news.getDiscoverySources).mockResolvedValue([]); vi.mocked(news.getStories).mockResolvedValue({ stories: [], stories_total: 0 }); vi.mocked(news.getEditorialQueue).mockResolvedValue({ stories: [], stories_total: 0 });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const call: Call = { path: url.pathname, query: url.searchParams, init, body: init.body ? JSON.parse(String(init.body)) : {} }; calls.push(call);
    if (call.path.endsWith("/capabilities")) return json({ roles: ["reader"], permissions, storage: "postgres", commands_enabled: commands, ai_generation_enabled: generationEnabled }, capabilityStatus);
    if (init.method === "POST") {
      expect(call.path === "/api/editorial/ai/suggestions" || call.path.endsWith("/recover")).toBe(true);
      if (call.path.endsWith("/recover")) {
        const selected = suggestions.find(row => row.id === call.path.split("/").at(-2));
        expect(selected).toBeDefined();
        expect(call.path).toBe(`/api/editorial/ai/suggestions/${selected!.id}/recover`);
        expect(call.body).toEqual(commandFor(selected!));
        expect(call.body.command_id).toBe(selected!.command_id);
      }
      const commit = () => {
        if (call.path.endsWith("/recover")) {
          const existing = suggestions.find(row => row.id === call.path.split("/").at(-2));
          if (!existing) return json({},404);
          expect(call.body).toEqual(commandFor(existing));
          return json(existing, existing.status === "processing" ? 202 : 200);
        }
        const existing = suggestions.find(row => row.command_id === call.body.command_id);
        if (existing) return json(existing);
        const result = aiSuggestion(suggestions.length + 1, call.body); suggestions.unshift(result); return json(result, 201);
      };
      return postOverride ? postOverride(call, commit) : commit();
    }
    const override = getOverride?.(call); if (override) return override;
    if (call.path.startsWith("/api/editorial-stories/")) return json(collectedWorkspace(call.path.split("/").at(-1)));
    if (call.path.endsWith("/sources")) return json(sourceRows);
    if (call.path === "/api/editorial/drafts") return call.query.get("story_id") === storyId ? json(savedDraft()) : json({}, 404);
    if (call.path === "/api/editorial/ai/suggestions") {
      const offset = Number(call.query.get("offset") || 0), limit = Number(call.query.get("limit") || 20);
      return json(suggestions.filter(row => row.story_id === call.query.get("story_id")).slice(offset, offset + limit).map(aiSummary));
    }
    if (call.path.startsWith("/api/editorial/ai/suggestions/")) return json(suggestions.find(row => row.id === call.path.split("/").at(-1)), 200);
    throw new Error("Unexpected route: " + call.path);
  }));
});

describe("private AI editorial workspace", () => {
  it("uses the selected story, stable source UUIDs and unambiguous portal evidence", async () => {
    mount(); await loaded(); expect(screen.getByText("Sačuvana regionalna priča")).toBeTruthy(); expect(screen.getByText(/Urednički status: Uređivanje/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "Originalni tekst izvora" }).textContent).toContain("CURRENT ORIGINAL 1");
    expect(screen.getByText("Jezik izvora: sl")).toBeTruthy(); expect(document.querySelector("script")).toBeNull();
    fireEvent.change(await loaded(), { target: { value: sourceRows[1].article_id } });
    expect(screen.getByRole("region", { name: "Originalni tekst izvora" }).textContent).toContain("CURRENT ORIGINAL 2");
    fireEvent.click(generate()); await screen.findByText("AI PRIVATE BODY 1");
    expect(posts()[0].body).toEqual({ command_id: expect.any(String), story_id: storyId, article_id: sourceRows[1].article_id, source_id: sourceRows[1].source_id, target_locale: "sr-Latn", mode: "translation" });
    expect(screen.getByRole("region", { name: "Originalni tekst izvora" }).textContent).toBe("SEALED ORIGINAL Portal Two");
    expect(document.querySelector('[data-testid="ai-comparison"]')?.className).toContain("lg:grid-cols-2");
  });
  it("reaches AI suggestions through the existing story navigation", async () => {
    const { router } = mount(); await loaded(); expect(screen.getByRole("link", { name: "AI predlozi" }).getAttribute("href")).toBe(`/review/${storyId}/ai`);
    await act(async () => { await router.navigate(`/review/${storyId}`); });
    fireEvent.click(await screen.findByRole("link", { name: "AI predlozi" })); await loaded(); expect(generate()).toBeTruthy();
  });
  it("loads details lazily and compares against frozen content rather than recollected material", async () => {
    suggestions = [aiSuggestion()]; mount(); await loaded();
    expect(calls.some(call => call.path === `/api/editorial/ai/suggestions/${suggestions[0].id}`)).toBe(false); expect(screen.queryByText("AI PRIVATE BODY 1")).toBeNull();
    inspectFirst(); await screen.findByText("AI PRIVATE BODY 1"); expect(screen.getByText("Zamrznuti izvor AI predloga")).toBeTruthy();
    expect(screen.queryByText(/CURRENT ORIGINAL/)).toBeNull(); expect(screen.getByText(/Obavezna ljudska provera/)).toBeTruthy();
    fireEvent.click(screen.getByText("Metapodaci obrade")); expect(screen.getByText(/fixture-response-id/)).toBeTruthy(); expect(screen.getByText(/gemini-fixture-version/)).toBeTruthy();
    expect(screen.getByText(/123 \/ 40 \/ 0 \/ 0 \/ 163/)).toBeTruthy(); expect(screen.getByText(/Trošak: nepoznat/)).toBeTruthy();
    expect(posts()).toHaveLength(0); expect(screen.queryByRole("button", { name: /Prihvati|Odobri|Objavi/ })).toBeNull();
  });
  it("opens the separate acceptance editor for the selected successful suggestion", async () => {
    suggestions = [aiSuggestion()]; mount(); await loaded(); inspectFirst(); await screen.findByText("AI PRIVATE BODY 1");
    expect(screen.getByRole("link", { name: "Uredi i pripremi prihvatanje" }).getAttribute("href")).toBe(`/review/${storyId}/ai/${suggestions[0].id}/edit`);
    fireEvent.click(screen.getByRole("link", { name: "Uredi i pripremi prihvatanje" })); await screen.findByRole("form", { name: "Uređivanje AI predloga" });
    expect((screen.getByLabelText(/^Body/) as HTMLTextAreaElement).value).toBe("AI PRIVATE BODY 1"); expect(posts()).toHaveLength(0);
  });
  it("labels the deterministic mock truthfully and preserves unknown frozen language", async () => {
    const value = aiSuggestion(1, { provenance: { provider: "mock", model: "deterministic-no-translation-v1", is_mock: true, adapter_version: "1" } });
    value.input.source.language = null; value.input.source.source_language = null; value.input.source.published_at = null; suggestions = [value];
    mount(); await loaded(); inspectFirst(); await screen.findByText(/DEMO \/ MOCK: nije stvarni prevod/); expect(screen.getByText("Jezik izvora: Nije zabeležen")).toBeTruthy(); expect(screen.getByText("Objavljeno: Datum nije dostupan")).toBeTruthy();
  });
  it("prevents rapid duplicate generation and does not claim success before a response", async () => {
    const pending = deferred<Response>(); postOverride = () => pending.promise; mount(); await loaded();
    fireEvent.click(generate()); fireEvent.click(generate()); await waitFor(() => expect(posts()).toHaveLength(1));
    expect(generate().hasAttribute("disabled")).toBe(true); expect(screen.queryByText("AI PRIVATE BODY 1")).toBeNull(); expect(screen.getByText(/Zahtev je u toku/)).toBeTruthy();
    const value = aiSuggestion(1, posts()[0].body); suggestions = [value];
    await act(async () => pending.resolve(json(value, 201))); await screen.findByText("AI PRIVATE BODY 1"); expect(posts()).toHaveLength(1);
  });
  it.each(["before", "after"])("retains an uncertain command and recovers it explicitly after loss %s commit", async timing => {
    let first = true;
    postOverride = async (_call, commit) => { if (first) { first = false; if (timing === "after") commit(); throw new Error("sensitive network details"); } return commit(); };
    mount(); await loaded(); fireEvent.click(generate()); await screen.findByText("Ishod komande nije potvrđen");
    expect(posts()).toHaveLength(1); expect(generate().hasAttribute("disabled")).toBe(true); expect(screen.queryByRole("article")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Oporavi istu komandu" })); expect(posts()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Pošalji istu komandu" })); await screen.findByText("AI PRIVATE BODY 1");
    expect(posts()).toHaveLength(2); expect(posts()[1].body).toEqual(posts()[0].body); expect(suggestions).toHaveLength(1);
    expect(document.body.textContent).not.toContain("sensitive network details");
  });
  it("treats HTTP 201 failed processing as failure and never as a generated article", async () => {
    postOverride = async call => json(aiSuggestion(1, { ...call.body, status: "failed", output_hash: null, error_code: "provider_refused" }), 201);
    mount(); await loaded(); fireEvent.click(generate()); await screen.findByText(/Kod greške obrade: provider_refused/);
    expect(screen.queryByRole("article")).toBeNull(); expect(screen.queryByText("AI PRIVATE BODY 1")).toBeNull(); expect(posts()).toHaveLength(1);
  });
  it("keeps processing commands guarded and performs recovery with the original payload", async () => {
    let first = true;
    postOverride = async call => { const value = aiSuggestion(1, { ...call.body, status: first ? "processing" : "interrupted", revision: first ? 1 : 2, output_hash: null, error_code: first ? null : "process_interrupted" }); value.recovery_command=first ? commandFor(value) : null; suggestions=[value]; first = false; return json(value, 202); };
    mount(); await loaded(); fireEvent.click(generate()); await screen.findByText("Postojeća obrada još nije završena"); expect(generate().hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Oporavi postojeću obradu" })); fireEvent.click(screen.getByRole("button", { name: "Pošalji istu komandu" })); await screen.findByText("Obrada je prekinuta", {selector:'[role="status"]'}); expect(posts()[1].body).toEqual(posts()[0].body);
  });
  it.each([409, 422, 503])("handles generation HTTP %s without exposing raw error details or simulating success", async status => {
    postOverride = async () => json({ detail: "SENSITIVE PROVIDER DETAILS" }, status);
    mount(); await loaded(); fireEvent.click(generate()); await screen.findByRole("alert");
    expect(screen.queryByRole("article")).toBeNull(); expect(posts()).toHaveLength(1); expect(document.body.textContent).not.toContain("SENSITIVE PROVIDER DETAILS");
    expect(generate().hasAttribute("disabled")).toBe(status !== 422);
  });
  it("paginates lightweight history without preloading complete suggestions", async () => {
    suggestions = Array.from({ length: 21 }, (_, index) => aiSuggestion(index + 1)); mount(); await loaded();
    expect(screen.getAllByRole("button", { name: /^Prikaži predlog/ })).toHaveLength(20);
    fireEvent.click(screen.getByRole("button", { name: "Sledeća stranica" })); await waitFor(() => expect(screen.getAllByRole("button", { name: /^Prikaži predlog/ })).toHaveLength(1));
    expect(calls.filter(call => call.path === "/api/editorial/ai/suggestions").at(-1)?.query.get("offset")).toBe("20"); expect(posts()).toHaveLength(0);
  });
  it.each([401, 403])("clears private content when details return %s", async status => {
    suggestions = [aiSuggestion()]; mount(); await loaded();
    getOverride = call => call.path.startsWith("/api/editorial/ai/suggestions/") ? Promise.resolve(json({ detail: "secret" }, status)) : null;
    inspectFirst(); await screen.findByRole("alert"); expect(screen.queryByLabelText("Izvor za novu obradu")).toBeNull(); expect(screen.queryByRole("region", { name: "Originalni tekst izvora" })).toBeNull();
  });
  it("clears state on logout and ignores a delayed generation response", async () => {
    const pending = deferred<Response>(); postOverride = () => pending.promise; const identity = new TestEditorialIdentity(); mount(identity); await loaded();
    fireEvent.click(generate()); await waitFor(() => expect(posts()).toHaveLength(1)); const value = aiSuggestion(1, posts()[0].body);
    act(() => identity.changeSession(null)); await screen.findByText(/Sign in through your newsroom identity provider/);
    await act(async () => pending.resolve(json(value, 201))); expect(screen.queryByText("AI PRIVATE BODY 1")).toBeNull(); expect(screen.queryByText(/CURRENT ORIGINAL/)).toBeNull();
  });
  it("ignores details from another story after navigation", async () => {
    suggestions = [aiSuggestion()]; const pending = deferred<Response>(); const { router } = mount(); await loaded();
    getOverride = call => call.path.startsWith("/api/editorial/ai/suggestions/") ? pending.promise : null;
    inspectFirst(); await waitFor(() => expect(calls.some(call => call.path.endsWith(suggestions[0].id))).toBe(true));
    const secondStory = uuid(99); await act(async () => { await router.navigate(`/review/${secondStory}/ai`); }); await loaded();
    await act(async () => pending.resolve(json(suggestions[0]))); expect(screen.queryByText("AI PRIVATE BODY 1")).toBeNull();
  });
  it("rejects mismatched immutable reference identities without displaying the output", async () => {
    suggestions = [aiSuggestion()]; suggestions[0].output!.source_references[0].source_id = sourceRows[1].source_id;
    mount(); await loaded(); inspectFirst(); await screen.findByRole("alert"); expect(screen.queryByText("AI PRIVATE BODY 1")).toBeNull();
  });
  it("warns before leaving an unconfirmed command and never retries during navigation", async () => {
    postOverride = async () => { throw new Error("offline"); }; mount(); await loaded(); fireEvent.click(generate()); await screen.findByText("Ishod komande nije potvrđen");
    const unload = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(unload); expect(unload.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole("link", { name: "Urednički red" })); const dialog = await screen.findByRole("alertdialog"); expect(within(dialog).getByText(/može nastaviti na serveru/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Ostani" })); expect(posts()).toHaveLength(1);
  });
  it.each(["reader", "disabled"])("allows read-only history but disables generation for %s", async mode => {
    if (mode === "reader") permissions = ["editorial:read"]; else commands = false;
    suggestions = [aiSuggestion()]; mount(); await loaded(); expect(generate().hasAttribute("disabled")).toBe(true); inspectFirst(); await screen.findByText("AI PRIVATE BODY 1"); expect(posts()).toHaveLength(0);
  });
  it("keeps private AI unavailable without identity configuration", async () => {
    mount(null); await screen.findByText(/Sign-in integration has not been configured/); expect(screen.queryByLabelText("Izvor za novu obradu")).toBeNull(); expect(calls).toHaveLength(0);
  });
  it("shows unavailable capability state without fetching private content", async () => {
    capabilityStatus = 503; mount(); await screen.findByText(/Production editorial editing is unavailable/); expect(calls).toHaveLength(1); expect(posts()).toHaveLength(0);
  });
  it("keeps frozen history available after source-list failure and preserves it through explicit context reload", async () => {
    suggestions = [aiSuggestion()];
    getOverride = call => call.path.endsWith("/sources") ? Promise.resolve(json({ detail: "SENSITIVE DATABASE" }, 503)) : null;
    mount(); await screen.findByText("Spisak trenutnih izvora nije dostupan."); expect(screen.queryByLabelText("Izvor za novu obradu")).toBeNull(); expect(document.body.textContent).not.toContain("SENSITIVE DATABASE");
    expect(generate().hasAttribute("disabled")).toBe(true); inspectFirst(); await screen.findByText("AI PRIVATE BODY 1");
    getOverride = null; fireEvent.click(screen.getByRole("button", { name: "Ponovo učitaj kontekst priče" }));
    expect(screen.getByText("AI PRIVATE BODY 1")).toBeTruthy(); await loaded(); await waitFor(() => expect(generate().hasAttribute("disabled")).toBe(false)); expect(posts()).toHaveLength(0);
  });
  it("works without an editorial draft and distinguishes collection from approval", async () => {
    getOverride = call => call.path === "/api/editorial/drafts" ? Promise.resolve(json({}, 404)) : null;
    mount(); await loaded(); expect(screen.getByText(/Nema sačuvanog uredničkog nacrta/)).toBeTruthy(); fireEvent.click(generate()); await screen.findByText("AI PRIVATE BODY 1"); expect(posts()).toHaveLength(1);
  });
  it("does not guess a full-text match from shared WordPress IDs or ambiguous URLs", async () => {
    const material = collectedWorkspace(); material.source_articles.push({ ...material.source_articles[0], content: "WRONG DUPLICATE" });
    getOverride = call => call.path.startsWith("/api/editorial-stories/") ? Promise.resolve(json(material)) : null;
    mount(); await loaded(); expect(screen.getByRole("region", { name: "Originalni tekst izvora" }).textContent).toContain("Pun tekst nije jednoznačno dostupan"); expect(document.body.textContent).not.toContain("WRONG DUPLICATE");
  });
  it("keeps an acknowledged processing command guarded if the subsequent history refresh fails validation", async () => {
    let generated = false;
    postOverride = async call => { generated = true; return json(aiSuggestion(1, { ...call.body, status: "processing", revision: 1, output_hash: null }), 202); };
    getOverride = call => generated && call.path === "/api/editorial/ai/suggestions" ? Promise.resolve(json({}, 422)) : null;
    mount(); await loaded(); fireEvent.click(generate()); await screen.findByText("Postojeća obrada još nije završena"); expect(generate().hasAttribute("disabled")).toBe(true); expect(posts()).toHaveLength(1);
  });
  it("does not enable private AI for public demo stories", async () => {
    vi.mocked(news.isDemoDataModeEnabled).mockReturnValue(true); mount(); await screen.findByText(/unavailable for sample demo stories/); expect(screen.queryByRole("button", { name: "Generiši AI predlog" })).toBeNull(); expect(calls.every(call => call.path.endsWith("/capabilities"))).toBe(true);
  });
  it("never saves private AI content to browser storage or public preview state", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem"); suggestions = [aiSuggestion()]; const { router } = mount(); await loaded(); inspectFirst(); await screen.findByText("AI PRIVATE BODY 1");
    await act(async () => { await router.navigate(`/portal-preview/${storyId}`); }); await waitFor(() => expect(screen.queryByText("AI PRIVATE BODY 1")).toBeNull()); expect(storage).not.toHaveBeenCalled(); expect(posts()).toHaveLength(0);
  });
  it.each(["story503", "draft422"])("retains paginated history and frozen evidence after optional %s failure", async failure => {
    suggestions = Array.from({ length: 21 }, (_, index) => aiSuggestion(index + 1));
    getOverride = call => failure === "story503" && call.path.startsWith("/api/editorial-stories/") ? Promise.resolve(json({ detail: "SENSITIVE UPSTREAM" }, 503)) : failure === "draft422" && call.path === "/api/editorial/drafts" ? Promise.resolve(json({}, 422)) : null;
    mount(); await screen.findByText(failure === "story503" ? "Trenutni izvorni materijal nije dostupan." : "Urednički status nije dostupan.");
    expect(generate().hasAttribute("disabled")).toBe(true); fireEvent.click(generate()); expect(posts()).toHaveLength(0);
    if (failure === "draft422") expect(screen.getByText(/Urednički status: Nije potvrđen/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /^Prikaži predlog/ })).toHaveLength(20);
    fireEvent.click(screen.getByRole("button", { name: "Sledeća stranica" })); await waitFor(() => expect(screen.getAllByRole("button", { name: /^Prikaži predlog/ })).toHaveLength(1));
    inspectFirst(); await screen.findByText("AI PRIVATE BODY 21"); expect(screen.getByRole("region", { name: "Originalni tekst izvora" }).textContent).toBe("SEALED ORIGINAL Portal One");
    expect(posts()).toHaveLength(0); expect(document.body.textContent).not.toContain("SENSITIVE UPSTREAM");
  });
  it("reads history while optional context is stalled, with generation disabled", async () => {
    suggestions = [aiSuggestion()]; const pending = deferred<Response>();
    getOverride = call => call.path.startsWith("/api/editorial-stories/") ? pending.promise : null;
    mount(); await screen.findByRole("button", { name: /^Prikaži predlog/ }); expect(generate().hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/Provera konteksta priče/)).toBeTruthy(); inspectFirst(); await screen.findByText("AI PRIVATE BODY 1");
    await act(async () => pending.resolve(json({}, 503))); await screen.findByText("Trenutni izvorni materijal nije dostupan."); expect(screen.getByText("AI PRIVATE BODY 1")).toBeTruthy(); expect(posts()).toHaveLength(0);
  });
  it("shows an independent history error and retries only that read", async () => {
    suggestions = [aiSuggestion()];
    getOverride = call => call.path === "/api/editorial/ai/suggestions" ? Promise.resolve(json({ detail: "SENSITIVE HISTORY" }, 503)) : null;
    mount(); await screen.findByText("AI radni prostor nije učitan."); expect(screen.queryByRole("button", { name: /^Prikaži predlog/ })).toBeNull(); expect(screen.queryByRole("button", { name: "Generiši AI predlog" })).toBeNull();
    const optionalCount = calls.filter(call => call.path.startsWith("/api/editorial-stories/") || call.path === "/api/editorial/drafts" || call.path.endsWith("/sources")).length;
    getOverride = null; fireEvent.click(screen.getByRole("button", { name: "Ponovo učitaj radni prostor" })); await screen.findByRole("button", { name: /^Prikaži predlog/ });
    expect(calls.filter(call => call.path.startsWith("/api/editorial-stories/") || call.path === "/api/editorial/drafts" || call.path.endsWith("/sources"))).toHaveLength(optionalCount);
    expect(posts()).toHaveLength(0); expect(document.body.textContent).not.toContain("SENSITIVE HISTORY");
  });
  it.each([401, 403])("fails closed for HTTP %s from every context/history read", async status => {
    for (const path of ["/api/editorial-stories/", "/sources", "/api/editorial/drafts", "/api/editorial/ai/suggestions"]) {
      suggestions = [aiSuggestion()];
      getOverride = call => (path === "/api/editorial-stories/" ? call.path.startsWith(path) : path === "/sources" ? call.path.endsWith(path) : call.path === path) ? Promise.resolve(json({ detail: "SENSITIVE AUTH" }, status)) : null;
      const view = mount(); await screen.findByRole("button", { name: "Ponovo proveri pristup" });
      expect(screen.queryByRole("button", { name: /^Prikaži predlog/ })).toBeNull(); expect(screen.queryByLabelText("Istorija AI predloga")).toBeNull(); expect(screen.queryByRole("region", { name: "Originalni tekst izvora" })).toBeNull();
      expect(posts()).toHaveLength(0); expect(document.body.textContent).not.toContain("SENSITIVE AUTH"); view.unmount();
    }
  });
  it("clears loaded history after a delayed optional authorization failure and ignores late details", async () => {
    suggestions = [aiSuggestion()]; const context = deferred<Response>(), detail = deferred<Response>();
    getOverride = call => call.path.startsWith("/api/editorial-stories/") ? context.promise : call.path.startsWith("/api/editorial/ai/suggestions/") ? detail.promise : null;
    mount(); await screen.findByRole("button", { name: /^Prikaži predlog/ }); inspectFirst();
    await act(async () => context.resolve(json({}, 403))); await screen.findByRole("button", { name: "Ponovo proveri pristup" });
    await act(async () => detail.resolve(json(suggestions[0]))); expect(screen.queryByText("AI PRIVATE BODY 1")).toBeNull(); expect(screen.queryByLabelText("Istorija AI predloga")).toBeNull(); expect(posts()).toHaveLength(0);
  });
});

describe("isolated frozen source provenance", () => {
  it.each([null, "FROZEN-42"])("keeps historical external ID %s independent of another portal's current ID", externalId => {
    const value = aiSuggestion(1, { article_id: sourceRows[1].article_id, source_id: sourceRows[1].source_id });
    value.input.source.external_id = externalId; value.input.source.published_at = "2025-01-01T12:00:00Z";
    const current = { ...sourceRows[0], external_id: "CURRENT-999" };
    render(<AiSuggestionComparison suggestion={value} source={current} article={{ ...collectedWorkspace().source_articles[0], language: "hr" }} />);
    expect(screen.getByText(`Izvorni ID: ${externalId ?? "Nije dostupan"}`)).toBeTruthy(); expect(screen.queryByText(/CURRENT-999/)).toBeNull();
    expect(screen.getByText("Članak UUID: " + sourceRows[1].article_id)).toBeTruthy(); expect(screen.getByText("Portal UUID: " + sourceRows[1].source_id)).toBeTruthy();
    expect(screen.getByText(sourceRows[1].source_name)).toBeTruthy(); expect(screen.getByRole("link").getAttribute("href")).toBe(sourceRows[1].original_url);
    expect(screen.getByText("Jezik izvora: sl")).toBeTruthy(); expect(screen.getByRole("region", { name: "Originalni tekst izvora" }).textContent).toBe("SEALED ORIGINAL Portal Two");
    expect(screen.getByText(/^Objavljeno:/).textContent).toContain("2025"); expect(screen.queryByText(/CURRENT ORIGINAL/)).toBeNull();
  });
  it("continues to display current source IDs and content without a historical suggestion", () => {
    render(<AiSuggestionComparison suggestion={null} source={{ ...sourceRows[0], external_id: "CURRENT-999" }} article={collectedWorkspace().source_articles[0]} />);
    expect(screen.getByText("Izvorni ID: CURRENT-999")).toBeTruthy(); expect(screen.getByText("Članak UUID: " + sourceRows[0].article_id)).toBeTruthy();
    expect(screen.getByRole("region", { name: "Originalni tekst izvora" }).textContent).toContain("CURRENT ORIGINAL 1");
  });
});


describe("AI generation availability and daily budget", () => {
  it("keeps historical suggestions readable while generation is disabled", async () => {
    generationEnabled = false; suggestions = [aiSuggestion()]; mount(); await loaded();
    expect(generate().hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/AI generisanje nije uključeno/)).toBeTruthy();
    inspectFirst(); await screen.findByText("AI PRIVATE BODY 1"); expect(posts()).toHaveLength(0);
  });
  it("does not recover or retry a definitively rejected daily budget reservation", async () => {
    postOverride = async () => json({},429); mount(); await loaded(); fireEvent.click(generate());
    await screen.findByText(/Dnevni budžet AI obrade je dostignut/);
    expect(posts()).toHaveLength(1); expect(screen.queryByRole("button", {name:"Oporavi istu komandu"})).toBeNull();
    expect(generate().hasAttribute("disabled")).toBe(false);
  });
});


it("links from the individual story review to the existing private AI workspace without mutation", async () => {
  const {router} = mount(); await loaded();
  await act(async () => { await router.navigate(`/review/${storyId}`); });
  const action = await screen.findByRole("link", {name:"Generiši srpski nacrt"});
  expect(action.getAttribute("href")).toBe(`/review/${storyId}/ai`);
  fireEvent.click(action); await loaded(); expect(posts()).toHaveLength(0);
});


describe("persisted AI generation recovery", () => {
  it("recovers the original persisted fields after a lost response and browser remount", async () => {
    const noLocal = vi.spyOn(Storage.prototype,"setItem");
    postOverride = async call => { suggestions=[pendingSuggestion(call.body)]; throw Error("lost after reservation"); };
    const view=mount(); await loaded();
    fireEvent.change(await loaded(),{target:{value:sourceRows[1].article_id}});
    fireEvent.click(generate()); await screen.findByText("Ishod komande nije potvrđen");
    const original=posts()[0].body; view.unmount(); postOverride=null; generationEnabled=false;
    mount(); await loaded(); inspectFirst(); await screen.findByRole("button",{name:"Oporavi postojeću obradu"});
    expect(posts()).toHaveLength(1); expect(generate().hasAttribute("disabled")).toBe(true);
    recoverPersisted(); await waitFor(()=>expect(posts()).toHaveLength(2));
    expect(posts()[1].path).toBe(`/api/editorial/ai/suggestions/${suggestions[0].id}/recover`);
    expect(posts()[1].body).toEqual(original); expect(suggestions).toHaveLength(1);
    expect(screen.queryByText("AI PRIVATE BODY 1")).toBeNull(); expect(noLocal).not.toHaveBeenCalled();
  });
  it("recovers an expired reservation without optional current-source or draft context", async () => {
    suggestions=[pendingSuggestion({recovery_required:true})]; generationEnabled=false;
    getOverride=call => call.path.includes("editorial-stories") || call.path.endsWith("/sources") || call.path==="/api/editorial/drafts" ? Promise.resolve(json({},503)) : null;
    postOverride=async (_call,commit)=> { suggestions[0]={...suggestions[0],status:"interrupted",revision:2,error_code:"process_interrupted",recovery_required:false,recovery_command:null};return commit(); };
    mount(); await screen.findByRole("button",{name:/^Prikaži predlog/}); inspectFirst();
    await screen.findByRole("button",{name:"Oporavi postojeću obradu"}); recoverPersisted();
    await screen.findByText(/Kod greške obrade: process_interrupted/);
    expect(posts()).toHaveLength(1); expect(posts()[0].path.endsWith("/recover")).toBe(true);
    expect(screen.queryByRole("button",{name:"Oporavi postojeću obradu"})).toBeNull();
    expect(suggestions).toHaveLength(1);
  });
  it.each([404,409,503])("never falls back to generation after strict recovery HTTP %s", async status => {
    suggestions=[pendingSuggestion()]; postOverride=async()=>json({},status);
    mount(); await loaded(); inspectFirst(); await screen.findByRole("button",{name:"Oporavi postojeću obradu"});
    recoverPersisted(); await screen.findByRole("alert");
    expect(posts()).toHaveLength(1); expect(posts()[0].path.endsWith("/recover")).toBe(true);
    expect(generate().hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button",{name:"Oporavi postojeću obradu"})).toBeTruthy();
  });
  it.each([null,"test-session","rotated-session"])("isolates pending recovery after logout and next session %s", async nextSession => {
    suggestions=[pendingSuggestion()]; const pending=deferred<Response>(); postOverride=()=>pending.promise;
    const identity=new TestEditorialIdentity(); mount(identity); await loaded(); inspectFirst();
    await screen.findByRole("button",{name:"Oporavi postojeću obradu"});
    fireEvent.click(screen.getByRole("button",{name:"Oporavi postojeću obradu"}));
    const confirm=screen.getByRole("button",{name:"Pošalji istu komandu"});fireEvent.click(confirm);fireEvent.click(confirm);
    await waitFor(()=>expect(posts()).toHaveLength(1));
    act(()=>identity.changeSession(null));
    if (nextSession) { act(()=>identity.changeSession(nextSession)); await loaded(); }
    await act(async()=>pending.resolve(json({...suggestions[0],status:"interrupted",revision:2,recovery_command:null})));
    expect(screen.queryByText("SEALED ORIGINAL Portal One")).toBeNull();
    expect(screen.queryByRole("button",{name:"Oporavi postojeću obradu"})).toBeNull();expect(posts()).toHaveLength(1);
  });
  it.each([401,403])("clears protected recovery state on HTTP %s", async status => {
    suggestions=[pendingSuggestion()];postOverride=async()=>json({},status);
    mount(); await loaded();inspectFirst();await screen.findByRole("button",{name:"Oporavi postojeću obradu"});recoverPersisted();
    await screen.findByRole("alert");expect(screen.queryByTestId("ai-comparison")).toBeNull();
    expect(screen.queryByRole("button",{name:"Oporavi postojeću obradu"})).toBeNull();
  });
  it("rejects a recovery command that changes the persisted source UUID", async () => {
    suggestions=[pendingSuggestion()];suggestions[0].recovery_command!.article_id=uuid(9999);
    mount();await loaded();inspectFirst();await screen.findByRole("alert");
    expect(screen.queryByRole("button",{name:"Oporavi postojeću obradu"})).toBeNull();expect(posts()).toHaveLength(0);
  });
  it("does not offer another editor or a Reader the owner's recovery command", async () => {
    suggestions=[pendingSuggestion()];suggestions[0].recovery_command=null;permissions=["editorial:read"];
    mount();await loaded();inspectFirst();await screen.findByText(/Oporavak ove rezervacije zahteva prvobitnog urednika/);
    expect(screen.queryByRole("button",{name:"Oporavi postojeću obradu"})).toBeNull();expect(posts()).toHaveLength(0);
  });
});


describe("selected recovery identity and history transitions", () => {
  const historyButton = (index: number) => screen.getAllByRole("button", {name:/^Prikaži predlog/})[index];
  const recoveryPanel = () => document.querySelector('[aria-label="Oporavak AI komande"]');
  const anotherPending = () => pendingSuggestion({id:uuid(7001),command_id:uuid(7002)});
  const inspect = async (index: number) => {
    fireEvent.click(historyButton(index));
    await waitFor(()=>expect(historyButton(index).getAttribute("aria-pressed")).toBe("true"));
    await waitFor(()=>expect(historyButton(index).hasAttribute("disabled")).toBe(false));
  };
  const assertReplay = (index: number, value: AiSuggestion) => {
    expect(posts()[index].path).toBe(`/api/editorial/ai/suggestions/${value.id}/recover`);
    expect(posts()[index].body).toEqual(commandFor(value));
    expect(posts()[index].body.command_id).toBe(value.command_id);
  };
  it("binds processing A → processing B → A and sends only each selected original command", async () => {
    const a=pendingSuggestion(), b=anotherPending(); suggestions=[a,b]; mount();await loaded();
    for (const [index,value] of [[0,a],[1,b],[0,a]] as const) {
      await inspect(index);
      expect(recoveryPanel()!.textContent).toContain(value.command_id);
      expect(recoveryPanel()!.textContent).not.toContain(value===a ? b.command_id : a.command_id);
      recoverPersisted(); await waitFor(()=>expect(historyButton(index).hasAttribute("disabled")).toBe(false));
      assertReplay(posts().length-1,value);
    }
    expect(posts()).toHaveLength(3);
  });
  it.each(["terminal","not-owned"])("removes A's recovery when B is %s", async kind => {
    const a=pendingSuggestion();const b=kind==="terminal" ? aiSuggestion(2) : anotherPending();
    b.recovery_command=null;suggestions=[a,b];mount();await loaded();await inspect(0);await inspect(1);
    expect(recoveryPanel()).toBeNull();expect(screen.queryByRole("button",{name:"Oporavi postojeću obradu"})).toBeNull();
    expect(posts()).toHaveLength(0);
    await inspect(0);recoverPersisted();await waitFor(()=>expect(posts()).toHaveLength(1));assertReplay(0,a);
  });
  it("invalidates A's confirmation immediately while B's delayed detail fails", async () => {
    const a=pendingSuggestion(),b=anotherPending();suggestions=[a,b];const delayed=deferred<Response>();
    getOverride=call=>call.path.endsWith(b.id) ? delayed.promise : null;
    mount();await loaded();await inspect(0);
    fireEvent.click(screen.getByRole("button",{name:"Oporavi postojeću obradu"}));
    const staleConfirmation=screen.getByRole("button",{name:"Pošalji istu komandu"});
    // Deliberate programmatic selection behind the modal exercises stale callbacks.
    fireEvent.click(historyButton(1));fireEvent.click(staleConfirmation);
    expect(recoveryPanel()).toBeNull();expect(screen.queryByRole("alertdialog")).toBeNull();expect(posts()).toHaveLength(0);
    await act(async()=>delayed.resolve(json({},503)));await screen.findByRole("alert");
    expect(recoveryPanel()).toBeNull();expect(posts()).toHaveLength(0);
    await inspect(0);recoverPersisted();await waitFor(()=>expect(posts()).toHaveLength(1));assertReplay(0,a);
  });
  it("clears selected recovery on refresh and pagination without posting stale commands", async () => {
    const a=pendingSuggestion();suggestions=[a,...Array.from({length:20},(_,i)=>aiSuggestion(i+2))];
    mount();await loaded();await inspect(0);
    fireEvent.click(screen.getByRole("button",{name:"Osveži istoriju AI predloga"}));
    await waitFor(()=>expect(recoveryPanel()).toBeNull());expect(posts()).toHaveLength(0);
    await waitFor(()=>expect(historyButton(0).hasAttribute("disabled")).toBe(false));await inspect(0);
    fireEvent.click(screen.getByRole("button",{name:"Sledeća stranica"}));
    await waitFor(()=>expect(screen.getAllByRole("button",{name:/^Prikaži predlog/})).toHaveLength(1));
    expect(recoveryPanel()).toBeNull();expect(posts()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button",{name:"Prethodna stranica"}));
    await waitFor(()=>expect(screen.getAllByRole("button",{name:/^Prikaži predlog/})).toHaveLength(20));
    await inspect(0);recoverPersisted();await waitFor(()=>expect(posts()).toHaveLength(1));assertReplay(0,a);
  });
  it("keeps A selected after failed recovery; switching to B changes retry target to B", async () => {
    const a=pendingSuggestion(),b=anotherPending();suggestions=[a,b];let fail=true;
    postOverride=async(_call,commit)=>{if(fail){fail=false;return json({},503);}return commit();};
    mount();await loaded();await inspect(0);recoverPersisted();await screen.findByRole("alert");assertReplay(0,a);
    expect(historyButton(0).getAttribute("aria-pressed")).toBe("true");expect(recoveryPanel()!.textContent).toContain(a.command_id);
    recoverPersisted();await waitFor(()=>expect(posts()).toHaveLength(2));assertReplay(1,a);
    await waitFor(()=>expect(historyButton(1).hasAttribute("disabled")).toBe(false));await inspect(1);
    recoverPersisted();await waitFor(()=>expect(posts()).toHaveLength(3));assertReplay(2,b);
  });
  it("preserves an id:null page command separately while inspecting and recovering B", async () => {
    const b=anotherPending();suggestions=[b];let first=true;
    postOverride=async(call,commit)=>{if(first){first=false;throw Error("unreceived request");}return commit();};
    mount();await loaded();fireEvent.click(generate());await screen.findByText("Ishod komande nije potvrđen");
    const original=posts()[0].body;await inspect(0);
    expect(document.querySelector('[aria-label="Nepotvrđena komanda ove stranice"]')!.textContent).toContain(original.command_id);
    expect(recoveryPanel()!.textContent).toContain(b.command_id);expect(recoveryPanel()!.textContent).not.toContain(original.command_id);
    recoverPersisted();await waitFor(()=>expect(posts()).toHaveLength(2));assertReplay(1,b);
    await waitFor(()=>expect(historyButton(0).hasAttribute("disabled")).toBe(false));
    fireEvent.click(screen.getByRole("button",{name:"Oporavi istu komandu"}));fireEvent.click(screen.getByRole("button",{name:"Pošalji istu komandu"}));
    await waitFor(()=>expect(posts()).toHaveLength(3));
    expect(posts()[2].path).toBe("/api/editorial/ai/suggestions");expect(posts()[2].body).toEqual(original);
    expect(posts()[2].body.command_id).toBe(original.command_id);
  });
  it("rejects a previously captured confirmation after selection changes to B", async () => {
    const a=pendingSuggestion(),b=anotherPending();suggestions=[a,b];mount();await loaded();await inspect(0);
    fireEvent.click(screen.getByRole("button",{name:"Oporavi postojeću obradu"}));
    const staleConfirm=capturedConfirmation!;await inspect(1);
    act(()=>staleConfirm());await screen.findByText(/Oporavak ne odgovara izabranom predlogu/);
    expect(posts()).toHaveLength(0);expect(recoveryPanel()!.textContent).toContain(b.command_id);
    expect(historyButton(1).getAttribute("aria-pressed")).toBe("true");
    recoverPersisted();await waitFor(()=>expect(posts()).toHaveLength(1));assertReplay(0,b);
  });
  it("rejects every mismatched persisted recovery plan", () => {
    const a=pendingSuggestion(),b=anotherPending(),plan={id:a.id,command:commandFor(a)};
    expect(matchesSelectedAiRecovery(plan,a.id,a)).toBe(true);
    for (const [candidate,selected,detail] of [[plan,b.id,b],[plan,null,null],[{...plan,id:b.id},a.id,a],
        [{...plan,command:{...plan.command,command_id:b.command_id}},a.id,a],
        [{...plan,command:{...plan.command,article_id:uuid(9999)}},a.id,a],
        [plan,a.id,{...a,status:"succeeded",recovery_command:null}]] as const) {
      expect(matchesSelectedAiRecovery(candidate,selected,detail)).toBe(false);
    }
    expect(posts()).toHaveLength(0);
  });
});


describe("pending command reconciliation from validated history", () => {
  const pendingPanel = () => document.querySelector('[aria-label="Nepotvrđena komanda ove stranice"]');
  const refresh = () => fireEvent.click(screen.getByRole("button", { name: "Osveži istoriju AI predloga" }));
  async function loseAndBind() {
    postOverride = async () => { throw Error("lost response"); };
    mount(); await loaded(); fireEvent.click(generate()); await screen.findByText("Ishod komande nije potvrđen");
    const a = pendingSuggestion(posts()[0].body);
    suggestions = [a, aiSuggestion(2)]; refresh();
    await screen.findByRole("button", { name: /Prikaži predlog.*1001/ });
    inspectFirst(); await screen.findByRole("button", { name: "Oporavi postojeću obradu" });
    return a;
  }
  it("unblocks generation and editing when only refreshed history observes terminal A", async () => {
    const a = await loseAndBind();
    fireEvent.click(screen.getAllByRole("button", { name: /^Prikaži predlog/ })[1]);
    await screen.findByText("AI PRIVATE BODY 2");
    expect(pendingPanel()!.textContent).toContain(a.id); expect(generate().hasAttribute("disabled")).toBe(true);
    suggestions[0] = aiSuggestion(1, commandFor(a)); refresh();
    await waitFor(() => expect(pendingPanel()).toBeNull()); expect(generate().hasAttribute("disabled")).toBe(false);
    fireEvent.click(screen.getAllByRole("button", { name: /^Prikaži predlog/ })[1]);
    await screen.findByRole("link", { name: "Uredi i pripremi prihvatanje" });
    expect(posts()).toHaveLength(1); expect(posts()[0].path).toBe("/api/editorial/ai/suggestions");
  });
  it("reconciles terminal A in the history refreshed after recovering unrelated B", async () => {
    const a = await loseAndBind(), b = pendingSuggestion({ id: uuid(9101), command_id: uuid(9201) });
    b.input.request_id = b.id; suggestions = [a, b]; refresh();
    await waitFor(() => expect(screen.getAllByRole("button", { name: /^Prikaži predlog/ })).toHaveLength(2));
    fireEvent.click(screen.getAllByRole("button", { name: /^Prikaži predlog/ })[1]);
    await screen.findByRole("button", { name: "Oporavi postojeću obradu" });
    postOverride = async (call) => {
      expect(call.path).toBe(`/api/editorial/ai/suggestions/${b.id}/recover`); expect(call.body).toEqual(commandFor(b));
      suggestions = [aiSuggestion(1, commandFor(a)), aiSuggestion(2, { ...commandFor(b), id: b.id })];
      return json(suggestions[1]);
    };
    recoverPersisted(); await screen.findByRole("link", { name: "Uredi i pripremi prihvatanje" });
    expect(pendingPanel()).toBeNull(); expect(generate().hasAttribute("disabled")).toBe(false); expect(posts()).toHaveLength(2);
  });
  it("retains uncertain X when history contains only unrelated terminal B", async () => {
    suggestions = [aiSuggestion(2)]; postOverride = async () => { throw Error("not received"); };
    mount(); await loaded(); fireEvent.click(generate()); await screen.findByText("Ishod komande nije potvrđen");
    const original = posts()[0].body; refresh();
    await waitFor(() => expect(screen.getByRole("button", { name: "Osveži istoriju AI predloga" }).hasAttribute("disabled")).toBe(false));
    inspectFirst(); await screen.findByText("AI PRIVATE BODY 2");
    expect(pendingPanel()!.textContent).toContain(original.command_id); expect(generate().hasAttribute("disabled")).toBe(true);
    expect(screen.queryByRole("link", { name: "Uredi i pripremi prihvatanje" })).toBeNull(); expect(posts()).toHaveLength(1);
  });
  it("preserves processing A and pending A when paginating to a page without A", async () => {
    const a = await loseAndBind(); suggestions = [a, ...Array.from({length:20}, (_, i) => aiSuggestion(i+2))]; refresh();
    await waitFor(() => expect(screen.getByRole("button", { name: "Sledeća stranica" }).hasAttribute("disabled")).toBe(false));
    expect(pendingPanel()!.textContent).toContain(a.id);
    fireEvent.click(screen.getByRole("button", { name: "Sledeća stranica" }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: /^Prikaži predlog/ })).toHaveLength(1));
    expect(pendingPanel()!.textContent).toContain(a.id); expect(generate().hasAttribute("disabled")).toBe(true); expect(posts()).toHaveLength(1);
  });
  it.each(["succeeded", "failed", "interrupted", "rejected", "accepted"] as const)("resolves a matching %s initial-history snapshot without requiring a bound ID", status => {
    const a = aiSuggestion(1, {status}), command = commandFor(a);
    expect(reconcilePendingAiCommand({ id:null, command }, [aiSummary(a)])).toBeNull();
    expect(reconcilePendingAiCommand({ id:a.id, command }, [aiSummary(a)])).toBeNull();
    expect(posts()).toHaveLength(0);
  });
  it("preserves missing, processing, mismatched IDs and every mismatched command field", () => {
    const a = aiSuggestion(), pending = { id:a.id, command:commandFor(a) };
    for (const rows of [[], [aiSummary(pendingSuggestion())], [aiSummary({...a,id:uuid(9999)})]]) {
      expect(reconcilePendingAiCommand(pending, rows)).toBe(pending);
    }
    for (const field of Object.keys(pending.command) as (keyof CreateAiSuggestion)[]) {
      const mismatched = { ...aiSummary(a), [field]: "different" };
      expect(reconcilePendingAiCommand(pending, [mismatched])).toBe(pending);
      expect(reconcilePendingAiCommand({...pending,id:null}, [mismatched])).not.toBeNull();
    }
    expect(reconcilePendingAiCommand(null, [aiSummary(a)])).toBeNull(); expect(posts()).toHaveLength(0);
  });
});
