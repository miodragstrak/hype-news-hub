import type { EditorialIdentityAdapter } from "../context/EditorialAccessContext";

export type Account = { id: string; email: string; role: "admin" | "editor"; active: boolean; revision: number };
type Session = { user: Account; csrf_token: string };
type State = { session: Session | null; busy: boolean; error: string; logoutPending: boolean };

export class SessionAccount implements EditorialIdentityAdapter {
  readonly authentication = "session" as const;
  private state: State = { session: null, busy: true, error: "", logoutPending: false };
  private snapshot: { key: string } | null = null;
  private listeners = new Set<() => void>();
  private generation = 0;
  private pendingCsrf = "";
  getSnapshot = () => this.snapshot;
  getState = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  getAccessToken = async () => null; // The authentication cookie is HttpOnly and never exposed here.
  getCsrfToken = async () => this.state.session?.csrf_token ?? null;
  private publish(value: State) { this.state = value; this.listeners.forEach(fn => fn()); }
  private clear(message: string) { this.generation++; this.snapshot = null; this.publish({ session: null, busy: false, error: message, logoutPending: false }); }
  private async raw(path: string, init?: RequestInit) {
    if (!path.startsWith("/api/") || new URL(path, location.origin).origin !== location.origin) throw Error("Nevažeća adresa servisa.");
    const headers = new Headers(init?.headers); headers.set("Accept", "application/json");
    return fetch(path, { ...init, credentials: "same-origin", redirect: "error", cache: "no-store",
      signal: init?.signal ?? AbortSignal.timeout(15000), headers });
  }
  private accept(value: Session) {
    if (!value?.user?.active || !["admin", "editor"].includes(value.user.role) || typeof value.user.id !== "string" ||
        typeof value.user.revision !== "number" || !/^[a-f0-9]{64}$/.test(value.csrf_token)) throw Error("Prijava nije potvrđena.");
    const old = this.state.session;
    if (!old || old.user.id !== value.user.id || old.user.revision !== value.user.revision || old.csrf_token !== value.csrf_token) {
      this.snapshot = { key: `${++this.generation}:${value.user.id}:${value.user.revision}` };
    }
    this.publish({ session: value, busy: false, error: "", logoutPending: false });
  }
  async bootstrap() {
    if (this.state.logoutPending) return;
    const ticket = this.generation;
    try {
      const response = await this.raw("/api/auth/session");
      if (ticket !== this.generation) return;
      if (response.status === 401) { this.clear(this.snapshot ? "Sesija je istekla. Prijavite se ponovo." : ""); return; }
      if (!response.ok) throw Error();
      const value = await response.json();
      if (ticket === this.generation) this.accept(value);
    } catch { if (ticket === this.generation) this.clear("Prijava nije dostupna. Pokušajte ponovo."); }
  }
  async login(email: string, password: string) {
    if (this.state.busy || this.state.logoutPending) return;
    const ticket = ++this.generation;
    this.snapshot = null; this.publish({ session: null, busy: true, error: "", logoutPending: false });
    try {
      const response = await this.raw("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
      if (!response.ok) throw Error(response.status === 429 ? "Previše pokušaja. Pokušajte kasnije." : "Prijava nije uspela.");
      const value = await response.json();
      if (ticket === this.generation) this.accept(value);
    } catch (error) {
      if (ticket === this.generation) this.clear(error instanceof Error ? error.message : "Prijava nije uspela.");
    }
  }
  async logout() {
    if (this.state.busy) return;
    this.pendingCsrf = this.state.session?.csrf_token ?? this.pendingCsrf;
    const ticket = ++this.generation;
    this.snapshot = null; this.publish({ session: null, busy: true, error: "", logoutPending: true });
    try {
      const response = await this.raw("/api/auth/logout", { method: "POST", headers: { "X-CSRF-Token": this.pendingCsrf } });
      if (!response.ok) throw Error();
      if (ticket === this.generation) { this.pendingCsrf = ""; this.clear(""); }
    } catch {
      if (ticket === this.generation) this.publish({ session: null, busy: false, error: "Odjava nije potvrđena. Pokušajte ponovo.", logoutPending: true });
    }
  }
  request = async (path: string, init?: RequestInit) => {
    const current = this.state.session, key = this.snapshot?.key;
    if (!current || !key) throw Error("Prijava je obavezna.");
    const headers = new Headers(init?.headers); headers.delete("Authorization"); headers.set("X-CSRF-Token", current.csrf_token);
    const response = await this.raw(path, { ...init, headers });
    if (this.snapshot?.key !== key) throw new DOMException("Obsolete session", "AbortError");
    if (response.status === 401) this.clear("Sesija je istekla. Prijavite se ponovo.");
    else if (response.status === 403) void this.bootstrap(); // Refresh current role without retrying the forbidden command.
    return response;
  };
}
