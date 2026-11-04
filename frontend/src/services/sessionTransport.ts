/** Installed only by the self-hosted entry. Session cookies never enter JavaScript. */
type Transport = (path: string, init?: RequestInit) => Promise<Response>;
let transport: Transport | null = null;
export function installSessionTransport(value: Transport | null) { transport = value; }
export function hasSessionTransport() { return transport !== null; }
export function sessionFetch(path: string, init?: RequestInit) {
  if (!transport) return Promise.reject(new Error("Session authentication is not configured."));
  return transport(path, init);
}
