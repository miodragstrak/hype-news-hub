import { describe, expect, it, vi } from "vitest";
import { EditorialApi, EditorialApiError } from "../src/services/editorialApi";
import { formFromPayload, normalizeEditorialText, readPublishingPayload, validateForm } from "../src/lib/editorialForm";
import { publishingPayload, sourceRows, storyId, uuid } from "./editorialFixtures";

describe("private editorial transport", () => {
  it("uses only the documented endpoints, Bearer credentials and no persistent browser cache", async () => {
    const fetcher = vi.fn().mockImplementation(async () => new Response("{}", { status: 200 })); vi.stubGlobal("fetch", fetcher);
    const api = new EditorialApi(async () => "verified-token", "https://backend.invalid");
    const command = { command_id: uuid(700), expected_revision: 0 as const, target_locale: "sr-Latn" as const, story_id: storyId, payload: publishingPayload() };
    await api.capabilities(); await api.sources(storyId, 50); await api.create(command); await api.find(storyId); await api.draft(uuid(2)); await api.save(uuid(2), { command_id: uuid(701), expected_revision: 1, payload: command.payload });
    expect(fetcher.mock.calls.map(([url]) => new URL(url).pathname)).toEqual(["/api/editorial/capabilities", `/api/editorial/stories/${storyId}/sources`, "/api/editorial/drafts", "/api/editorial/drafts", `/api/editorial/drafts/${uuid(2)}`, `/api/editorial/drafts/${uuid(2)}/revisions`]);
    expect(new URL(fetcher.mock.calls[1][0]).searchParams.get("offset")).toBe("50");
    for (const [, init] of fetcher.mock.calls) { expect(init.headers.Authorization).toBe("Bearer verified-token"); expect(init.credentials).toBe("omit"); expect(init.cache).toBe("no-store"); expect(init.redirect).toBe("error"); expect(init.headers["X-Role"]).toBeUndefined(); }
    expect(JSON.parse(fetcher.mock.calls[2][1].body)).toEqual(command);
  });
  it.each([401, 403, 409, 422, 503])("retains status %s without reflecting response bodies", async status => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("SENSITIVE CONNECTION DETAIL", { status })));
    const api = new EditorialApi(async () => "token", "https://backend.invalid");
    await expect(api.capabilities()).rejects.toMatchObject({ status });
    await expect(api.capabilities()).rejects.not.toThrow("SENSITIVE");
  });
  it("fails closed without credentials or when the identity SDK fails", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    await expect(new EditorialApi(async () => null, "https://backend.invalid").capabilities()).rejects.toMatchObject({ status: 401 });
    await expect(new EditorialApi(async () => { throw new Error("SECRET SDK TOKEN"); }, "https://backend.invalid").capabilities()).rejects.toThrow("Editorial session is unavailable.");
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("uses exact version, event and decision contracts with bounded page parameters", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}")); vi.stubGlobal("fetch", fetcher);
    const api = new EditorialApi(async () => "verified", "https://backend.invalid");
    const id = uuid(2), base = { command_id: uuid(800), expected_revision: 4, version_number: 2, content_hash: "a".repeat(64) };
    // Each response gets its own consumable JSON body.
    fetcher.mockImplementation(async () => new Response("{}"));
    await api.versions(id); await api.versions(id, 50, 20); await api.version(id, 2); await api.events(id, 20, 40);
    await api.submit(id, base); await api.approve(id, { ...base, reason: null }); await api.requestChanges(id, { ...base, reason: "Proveriti podatke." }); await api.reject(id, { ...base, reason: "Nepotvrđene tvrdnje." }); await api.reopen(id, { ...base, reason: "Dopunjeni izvori." });
    expect(fetcher.mock.calls.map(([url]) => new URL(url).pathname.split("/").slice(-1)[0])).toEqual(["versions", "versions", "2", "events", "submit", "approve", "request-changes", "reject", "reopen"]);
    expect(new URL(fetcher.mock.calls[0][0]).search).toBe("?limit=20&offset=0"); expect(new URL(fetcher.mock.calls[1][0]).search).toBe("?limit=50&offset=20"); expect(new URL(fetcher.mock.calls[3][0]).search).toBe("?limit=20&offset=40");
    expect(JSON.parse(fetcher.mock.calls[4][1].body)).toEqual(base); expect(JSON.parse(fetcher.mock.calls[5][1].body)).toEqual({ ...base, reason: null });
    expect(fetcher.mock.calls.every(([, init]) => init.credentials === "omit" && init.cache === "no-store")).toBe(true);
  });
  it("does not substitute demo data on invalid JSON or network errors", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response("bad-json")).mockRejectedValueOnce(new Error("offline")); vi.stubGlobal("fetch", fetcher);
    const api = new EditorialApi(async () => "token", "https://backend.invalid");
    await expect(api.capabilities()).rejects.toMatchObject({ status: 502 });
    await expect(api.find(storyId)).rejects.toBeInstanceOf(EditorialApiError);
  });
  it("uses the private AI contracts with UUID attribution, no implicit retries and no provider credentials", async () => {
    const fetcher = vi.fn().mockImplementation(async () => new Response("{}")); vi.stubGlobal("fetch", fetcher);
    const api = new EditorialApi(async () => "verified-token", "https://backend.invalid");
    const command = { command_id: uuid(999), story_id: storyId, article_id: sourceRows[1].article_id, source_id: sourceRows[1].source_id, mode: "translation" as const, target_locale: "sr-Latn" as const };
    await api.collectedStory(storyId); await api.aiSuggestions(storyId, 5, 20); await api.aiSuggestion(uuid(1001)); await api.generateAiSuggestion(command);
    expect(fetcher.mock.calls.map(([url]) => new URL(url).pathname)).toEqual([`/api/editorial-stories/${storyId}`, "/api/editorial/ai/suggestions", `/api/editorial/ai/suggestions/${uuid(1001)}`, "/api/editorial/ai/suggestions"]);
    expect(new URL(fetcher.mock.calls[1][0]).search).toBe(`?story_id=${storyId}&limit=5&offset=20`);
    expect(JSON.parse(fetcher.mock.calls[3][1].body)).toEqual(command);
    expect(fetcher.mock.calls.every(([, init]) => init.cache === "no-store" && init.credentials === "omit" && init.headers.Authorization === "Bearer verified-token")).toBe(true);
    fetcher.mockRejectedValue(new Error("offline")); await expect(api.generateAiSuggestion(command)).rejects.toMatchObject({ status: 0 }); expect(fetcher).toHaveBeenCalledTimes(5);
  });
  it("bounds stalled HTTP requests and reports an uncertain network outcome", async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal("fetch", vi.fn((_url, init: RequestInit) => new Promise((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))))));
      const pending = new EditorialApi(async () => "token", "https://backend.invalid").capabilities();
      const assertion = expect(pending).rejects.toMatchObject({ status: 0 });
      await vi.advanceTimersByTimeAsync(60000); await assertion;
    } finally { vi.useRealTimers(); }
  });
  it("sends explicit AI acceptance to the existing private endpoint without generation or implicit retry", async () => {
    const fetcher = vi.fn().mockImplementation(async () => new Response("{}")); vi.stubGlobal("fetch", fetcher);
    const api = new EditorialApi(async () => "verified", "https://backend.invalid");
    const command = { command_id: uuid(901), story_id: storyId, expected_revision: 5, payload: publishingPayload(), confirm_acceptance: true as const };
    await api.acceptAiSuggestion(uuid(1001), command);
    expect(fetcher.mock.calls[0][0]).toBe(`https://backend.invalid/api/editorial/ai/suggestions/${uuid(1001)}/accept`);
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(command);
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "POST", cache: "no-store", credentials: "omit", redirect: "error", headers: { Authorization: "Bearer verified" } });
    fetcher.mockRejectedValue(new Error("offline")); await expect(api.acceptAiSuggestion(uuid(1001), command)).rejects.toMatchObject({ status: 0 }); expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

describe("publishing form contract", () => {
  // Confirmed against backend Text's strip_whitespace=True, not JS trim or the
  // larger Python str.isspace() set (U+001C–U+001F are rejected by Text).
  const backendWhitespace = [...Array.from({ length: 5 }, (_, index) => 9 + index), 0x20, 0x85, 0xa0, 0x1680,
    ...Array.from({ length: 11 }, (_, index) => 0x2000 + index), 0x2028, 0x2029, 0x202f, 0x205f, 0x3000];
  it.each(backendWhitespace)("matches backend U+%s boundary stripping across every scalar Text field", point => {
    const edge = String.fromCodePoint(point), payload = publishingPayload();
    payload.images = [{ url: "https://media.invalid/image.jpg", alt: "Opis fotografije", credit: "Portal", source_article_id: sourceRows[0].article_id }];
    const form = formFromPayload(payload);
    for (const key of ["headline", "body", "excerpt", "seoTitle", "seoDescription"] as const) form[key] = edge + form[key] + edge;
    form.images[0].alt = edge + form.images[0].alt + edge; form.images[0].credit = edge + form.images[0].credit + edge;
    expect(validateForm(form)).toEqual({ payload, errors: {} });
    expect(form.body).toBe(edge + payload.body + edge); expect(normalizeEditorialText(edge + edge)).toBe("");
  });
  it.each([0x1c, 0x1d, 0x1e, 0x1f])("rejects Python-only U+%s boundary controls instead of silently stripping them", point => {
    const form = formFromPayload(publishingPayload()), value = String.fromCodePoint(point) + "Tekst" + String.fromCodePoint(point); form.body = value;
    expect(normalizeEditorialText(value)).toBe(value); expect(validateForm(form).errors.body).toBeTruthy();
  });
  it("preserves internal whitespace and backend-valid FEFF/zero-width boundaries exactly", () => {
    const value = "\ufeffPrvi\tred\r\nDrugi\u0085red\u00a0čćšžđ\u2028Treći\u2029red\ufeff";
    const form = formFromPayload({ ...publishingPayload(), body: value });
    expect(validateForm(form).errors).toEqual({}); expect(validateForm(form).payload.body).toBe(value);
    for (const edge of ["\ufeff", "\u180e", "\u200b", "\u2060"]) expect(normalizeEditorialText(edge + "Tekst" + edge)).toBe(edge + "Tekst" + edge);
  });
  it("rejects scalar Text fields containing only backend whitespace", () => {
    const form = formFromPayload(publishingPayload()); form.body = "\u0085\u00a0\u3000";
    expect(validateForm(form).payload.body).toBe(""); expect(validateForm(form).errors.body).toBe("This field is required.");
  });
  it("roundtrips all payload fields, multiple images and UUID attribution", () => {
    const payload = publishingPayload(); payload.images = [1, 2].map((value, index) => ({ url: `https://media.invalid/${value}`, alt: `Foto ${value}`, credit: "Izvor", source_article_id: sourceRows[index].article_id })); payload.source_attribution = sourceRows.map(({ article_id, source_id }) => ({ article_id, source_id }));
    expect(validateForm(formFromPayload(payload))).toEqual({ payload, errors: {} });
    expect(readPublishingPayload(payload)).toEqual(payload);
    expect(readPublishingPayload({ ...payload, unsupported: true })).toBeNull();
    expect(readPublishingPayload(null)).toBeNull();
  });
  it("rejects unsafe markup, Cyrillic, missing fields, duplicates and image/source mismatches", () => {
    const form = formFromPayload(publishingPayload());
    const invalid = { ...form, headline: "<img src=x>", body: "Ћирилица", slug: "bad slug", categories: ["Zabava", "zabava"], sources: [], images: [{ url: "javascript:alert(1)", alt: "", credit: "", source_article_id: uuid(999) }] };
    const result = validateForm(invalid);
    expect(Object.keys(result.errors)).toEqual(expect.arrayContaining(["headline", "body", "slug", "categories", "sources", "image-0-url", "image-0-alt", "image-0-credit", "image-0-source"]));
  });
  it("accepts valid Serbian Latin Unicode and surrogate pairs", () => {
    const form = formFromPayload({ ...publishingPayload(), body: "Tekst čćšžđ. Događaj 😀." });
    expect(validateForm(form).errors).toEqual({});
  });
  it("roundtrips unusual labels byte-for-byte without splitting or normalizing", () => {
    const payload = { ...publishingPayload(), categories: ["Pop\nkultura", "Film, TV", "Dva\r\nreda", "Tab\tlabel", "\ufeffBOM\ufeff"], tags: ["Festival\rMuzika", "Rock & pop", "Čćšžđ 😀", "Unicode\u2028line", "Unutrašnji\u00a0razmak"] };
    const form = formFromPayload(payload);
    form.body = "Only the article body changed.";
    const result = validateForm(form);
    expect(result.errors).toEqual({});
    expect(JSON.stringify(result.payload.categories)).toBe(JSON.stringify(payload.categories));
    expect(JSON.stringify(result.payload.tags)).toBe(JSON.stringify(payload.tags));
    expect(form.categories).not.toBe(payload.categories);
    expect(form.tags).not.toBe(payload.tags);
  });
  it("requires explicit correction of empty or padded labels instead of changing them", () => {
    const form = formFromPayload(publishingPayload()); form.categories = [" Pop ", ""]; form.tags = ["\u0085Tag"];
    const result = validateForm(form);
    expect(result.errors).toMatchObject({ "categories-0": expect.any(String), "categories-1": expect.any(String), "tags-0": expect.any(String) });
    expect(result.payload.categories).toEqual(form.categories);
    expect(result.payload.tags).toEqual(form.tags);
  });
});
