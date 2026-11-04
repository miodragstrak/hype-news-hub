import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SessionAccount } from "../src/auth/session";
import { SessionApplication } from "../src/auth/SessionApplication";
import { installSessionTransport } from "../src/services/sessionTransport";
import { EditorialApi } from "../src/services/editorialApi";

vi.mock("../src/App", () => ({ default: () => <p>Protected newsroom</p> }));
vi.mock("../src/context/DemoDataContext", () => ({ DemoDataProvider: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
const account = (id="user-a", revision=1, role="editor") => ({ user: { id, email: `${id}@example.invalid`, role, active: true, revision }, csrf_token: "a".repeat(64) });
const response = (data: unknown, status=200) => ({ ok: status>=200&&status<300, status, json: async () => data }) as Response;
function deferred<T>() { let resolve!: (value:T)=>void; const promise=new Promise<T>(r=>{resolve=r;});return {promise,resolve}; }
beforeEach(() => { installSessionTransport(null);vi.stubGlobal("fetch",vi.fn()); });

describe("self-hosted cookie authentication", () => {
  it("shows login before mounting protected pages and clears content on logout", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({},401));
    const store=new SessionAccount();render(<SessionApplication account={store}/>);
    await screen.findByRole("button",{name:"Prijavi se"});
    expect(screen.queryByText("Protected newsroom")).toBeNull();
    fireEvent.change(screen.getByLabelText("Email"),{target:{value:"user-a@example.invalid"}});
    fireEvent.change(screen.getByLabelText("Lozinka"),{target:{value:"editor confirmed password"}});
    vi.mocked(fetch).mockResolvedValueOnce(response(account()));
    fireEvent.click(screen.getByRole("button",{name:"Prijavi se"}));
    await screen.findByText("Protected newsroom");
    expect(screen.getByText(/user-a@example.invalid/)).toBeTruthy();
    vi.mocked(fetch).mockResolvedValueOnce(response(null,204));
    fireEvent.click(screen.getByRole("button",{name:"Odjavi se"}));
    await screen.findByRole("button",{name:"Prijavi se"});
    expect(screen.queryByText("Protected newsroom")).toBeNull();
  });
  it("sends same-origin cookies and CSRF without bearer or browser storage", async () => {
    const store=new SessionAccount();vi.mocked(fetch).mockResolvedValue(response(account()));await store.bootstrap();
    installSessionTransport(store.request);
    const api=new EditorialApi(store.getCsrfToken,"","session");await api.capabilities();
    const [url,init]=vi.mocked(fetch).mock.calls.at(-1)!;
    expect(url).toBe('/api/editorial/capabilities');expect(init?.credentials).toBe('same-origin');
    const headers=new Headers(init?.headers);expect(headers.get('Authorization')).toBeNull();expect(headers.get('X-CSRF-Token')).toBe('a'.repeat(64));
    expect(localStorage.length+sessionStorage.length).toBe(0);
  });
  it("ignores old-session unauthorized responses after a new login", async () => {
    const store=new SessionAccount();vi.mocked(fetch).mockResolvedValueOnce(response(account()));await store.bootstrap();
    const old=deferred<Response>();vi.mocked(fetch).mockReturnValueOnce(old.promise);
    const request=store.request('/api/stories');const outcome=request.catch(e=>e);
    vi.mocked(fetch).mockResolvedValueOnce(response(null,204));await store.logout();
    vi.mocked(fetch).mockResolvedValueOnce(response(account('user-b',1,'admin')));await store.login('user-b@example.invalid','another editor password');
    old.resolve(response({},401));expect((await outcome).name).toBe('AbortError');
    expect(store.getState().session?.user.id).toBe('user-b');
  });
  it("clears on active-session expiry but preserves identity on forbidden responses", async () => {
    const store=new SessionAccount();vi.mocked(fetch).mockResolvedValueOnce(response(account()));await store.bootstrap();
    vi.mocked(fetch).mockResolvedValueOnce(response({},403)).mockResolvedValueOnce(response(account()));await store.request('/api/admin/users');expect(store.getSnapshot()).not.toBeNull();
    vi.mocked(fetch).mockResolvedValueOnce(response({},401));await store.request('/api/stories');expect(store.getSnapshot()).toBeNull();
    expect(store.getState().error).toMatch(/istekla/);
  });
  it("keeps same-session refresh stable and invalidates on role/revision change", async () => {
    const store=new SessionAccount();vi.mocked(fetch).mockResolvedValue(response(account()));await store.bootstrap();const before=store.getSnapshot();
    await store.bootstrap();expect(store.getSnapshot()).toBe(before);
    vi.mocked(fetch).mockResolvedValueOnce(response(account('user-a',2,'admin')));await store.bootstrap();expect(store.getSnapshot()).not.toBe(before);
  });
  it("does not claim logout success after an uncertain outcome and supports safe retry", async () => {
    const store=new SessionAccount();vi.mocked(fetch).mockResolvedValueOnce(response(account()));await store.bootstrap();
    vi.mocked(fetch).mockRejectedValueOnce(new Error('network'));await store.logout();expect(store.getSnapshot()).toBeNull();
    expect(store.getState().logoutPending).toBe(true);await store.bootstrap();expect(store.getSnapshot()).toBeNull();
    vi.mocked(fetch).mockResolvedValueOnce(response(null,204));await store.logout();expect(store.getState().logoutPending).toBe(false);
  });
  it("fails closed on unavailable bootstrap and avoids duplicate login submissions", async () => {
    const store=new SessionAccount();vi.mocked(fetch).mockResolvedValueOnce(response({},503));await store.bootstrap();expect(store.getSnapshot()).toBeNull();
    const pending=deferred<Response>();vi.mocked(fetch).mockReturnValueOnce(pending.promise);const before=vi.mocked(fetch).mock.calls.length;
    const a=store.login('user@example.invalid','example editor password');await store.login('user@example.invalid','example editor password');
    expect(vi.mocked(fetch).mock.calls.length).toBe(before+1);pending.resolve(response(account()));await a;
    await expect(store.request('https://attacker.invalid/api/steal')).rejects.toThrow();
  });
});
