import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { EditorialApi, EditorialApiError } from "../services/editorialApi";
import type { EditorialCapabilities } from "../types/editorial";

/** Implement with a trusted identity SDK. No actor IDs/roles or browser token settings. */
export interface EditorialIdentityAdapter {
  readonly authentication?: "session";
  getCsrfToken?(): Promise<string | null>;
  getSnapshot(): { readonly key: string } | null;
  subscribe(listener: () => void): () => void;
  getAccessToken(): Promise<string | null>;
}
type Access = {
  state: "unconfigured" | "signed_out" | "checking" | "ready" | "error";
  sessionKey: string; capabilities: EditorialCapabilities | null; client: EditorialApi | null;
  error: unknown; refresh: () => void;
};
const noop = () => undefined;
const empty = () => null;
const subscribeNone = () => noop;
const Context = createContext<Access>({ state: "unconfigured", sessionKey: "", capabilities: null, client: null, error: null, refresh: noop });

type IdentityState = { state: "checking" | "ready" | "error"; key: string; revision: number };
const checking: IdentityState = { state: "checking", key: "", revision: 0 };
const identityError = new EditorialApiError(401, "The identity connection is unavailable.");

/** A session is usable only after its change subscription has been established. */
class IdentityConnection {
  private value = checking;
  private listeners = new Set<() => void>();
  private disconnect: (() => void) | null = null;
  private connected = false;
  private failed = false;
  private generation = 0;
  constructor(private readonly identity: EditorialIdentityAdapter) {}
  getSnapshot = () => this.value;
  private publish(state: IdentityState["state"], key = "") {
    if (this.value.state === state && this.value.key === key) return;
    // Preserve observed logout/login boundaries even when React batches updates
    // or an SDK reuses a session key. Ordinary same-session refresh stays stable.
    this.value = { state, key, revision: this.value.revision + 1 };
    this.listeners.forEach(listener => listener());
  }
  private stop() {
    this.connected = false; this.generation += 1;
    const disconnect = this.disconnect; this.disconnect = null;
    try { disconnect?.(); } catch { /* Detached listeners cannot restore access. */ }
  }
  private fail() {
    this.failed = true; this.stop(); this.publish("error");
  }
  private readKey() {
    const session = this.identity.getSnapshot();
    if (session === null) return "";
    if (!session || typeof session.key !== "string" || !session.key) throw identityError;
    return session.key;
  }
  private update() {
    try { this.publish("ready", this.readKey()); } catch { this.fail(); }
  }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    if (!this.connected && !this.failed) {
      const generation = ++this.generation;
      let initializing = true;
      try {
        const disconnect = this.identity.subscribe(() => {
          if (!initializing && this.connected && generation === this.generation) this.update();
        });
        if (typeof disconnect !== "function") throw identityError;
        this.disconnect = disconnect; this.connected = true; initializing = false;
        this.update();
      } catch { this.fail(); }
    }
    return () => {
      this.listeners.delete(listener);
      if (!this.listeners.size) {
        this.stop();
        if (!this.failed) this.publish("checking");
      }
    };
  };
  private assertSession(key: string, revision: number) {
    if (!this.connected || this.failed || this.value.state !== "ready") throw identityError;
    this.update();
    if (!this.connected || this.failed || this.value.key !== key || this.value.revision !== revision) throw identityError;
  }
  async token(key: string, revision: number) {
    this.assertSession(key, revision);
    const generation = this.generation;
    const sessionRevision = this.value.revision;
    // One SDK subscription can span several logins. Both completion paths must
    // belong to the session that initiated this token request.
    const isCurrentRequest = () => generation === this.generation && sessionRevision === this.value.revision;
    let token: string | null;
    try { token = this.identity.authentication === "session" ? await this.identity.getCsrfToken?.() ?? null : await this.identity.getAccessToken(); }
    catch { if (isCurrentRequest()) this.fail(); throw identityError; }
    if (!isCurrentRequest()) throw identityError;
    this.assertSession(key, sessionRevision);
    if (typeof token !== "string" || !token) { this.fail(); throw identityError; }
    return token;
  }
}

export function EditorialAccessProvider({ identity, children }: { identity?: EditorialIdentityAdapter; children: ReactNode }) {
  const [epoch, setEpoch] = useState(0);
  const refresh = useCallback(() => setEpoch(value => value + 1), []);
  // An explicit retry or adapter replacement establishes a new subscription.
  // Failures remain closed until then, even if an old SDK callback fires later.
  const connection = useMemo(() => identity ? new IdentityConnection(identity) : null, [identity, epoch]);
  const session = useSyncExternalStore(connection?.subscribe ?? subscribeNone, connection?.getSnapshot ?? empty, empty);
  const sessionKey = session?.key ?? "";
  const [result, setResult] = useState<{ client: EditorialApi | null; epoch: number; capabilities: EditorialCapabilities | null; error: unknown }>({ client: null, epoch: -1, capabilities: null, error: null });
  const client = useMemo(() => connection && session?.state === "ready" && sessionKey ? new EditorialApi(() => connection.token(sessionKey, session.revision), undefined, identity?.authentication === "session" ? "session" : "bearer") : null, [connection, identity, session?.state, session?.revision, sessionKey]);

  useEffect(() => {
    if (!client) return;
    const controller = new AbortController();
    void client.capabilities(controller.signal).then(capabilities => {
      if (capabilities.storage !== "postgres" || !Array.isArray(capabilities.permissions) || !Array.isArray(capabilities.roles) || typeof capabilities.commands_enabled !== "boolean") throw new EditorialApiError(502, "Invalid capability response.");
      if (!controller.signal.aborted) setResult({ client, epoch, capabilities, error: null });
    }).catch(error => { if (!controller.signal.aborted) setResult({ client, epoch, capabilities: null, error }); });
    return () => controller.abort();
  }, [client, epoch]);

  const current = result.client === client && result.epoch === epoch;
  const state = !identity ? "unconfigured" : session?.state === "error" ? "error" : session?.state !== "ready" ? "checking" : !sessionKey ? "signed_out" : !current ? "checking" : result.error ? "error" : "ready";
  return <Context.Provider value={{ state, sessionKey, client, capabilities: state === "ready" ? result.capabilities : null, error: session?.state === "error" ? identityError : current ? result.error : null, refresh }}>{children}</Context.Provider>;
}

export function useEditorialAccess() { return useContext(Context); }
