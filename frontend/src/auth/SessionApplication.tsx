import { useEffect, useState, useSyncExternalStore, type FormEvent } from "react";
import App from "../App";
import { DemoDataProvider } from "../context/DemoDataContext";
import { Button } from "../components/ui/button";
import { SessionAccount, type Account } from "./session";

export function SessionApplication({ account }: { account: SessionAccount }) {
  const state = useSyncExternalStore(account.subscribe, account.getState);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [administration, setAdministration] = useState(false);
  useEffect(() => { if (state.session) setPassword(""); }, [state.session?.user.id]);
  useEffect(() => {
    void account.bootstrap();
    const refresh = () => { if (!document.hidden) void account.bootstrap(); };
    const timer = setInterval(refresh, 60_000);
    window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh);
    return () => { clearInterval(timer); window.removeEventListener("focus", refresh); document.removeEventListener("visibilitychange", refresh); };
  }, [account]);
  async function login(event: FormEvent) {
    event.preventDefault(); const secret = password; setPassword("");
    await account.login(email, secret);
  }
  if (!state.session) return <main lang="sr-Latn" className="mx-auto max-w-md space-y-5 p-6 text-white">
    <h1 className="text-3xl font-bold">Hype World News — prijava</h1>
    {state.error ? <p role="alert">{state.error}</p> : null}
    {state.busy ? <p role="status">Provera prijave…</p> : state.logoutPending ?
      <Button onClick={() => void account.logout()}>Ponovi odjavu</Button> : <form onSubmit={event => void login(event)} className="space-y-4">
        <label className="block">Email<input className="mt-1 w-full rounded p-3 text-black" type="email" autoComplete="username" required maxLength={254} value={email} onChange={e => setEmail(e.target.value)} /></label>
        <label className="block">Lozinka<input className="mt-1 w-full rounded p-3 text-black" type="password" autoComplete="current-password" required maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></label>
        <Button type="submit">Prijavi se</Button><Button type="button" variant="secondary" onClick={() => void account.bootstrap()}>Ponovo proveri sesiju</Button>
      </form>}
  </main>;
  return <div lang="sr-Latn">
    <header className="flex flex-wrap items-center gap-4 bg-[#07173d] p-3 text-white" aria-label="Prijavljeni nalog">
      <p className="min-w-0 [overflow-wrap:anywhere]">{state.session.user.email} · {state.session.user.role === "admin" ? "Administrator" : "Urednik"}</p>
      <Button onClick={() => void account.logout()}>Odjavi se</Button>
      {state.session.user.role === "admin" ? <Button variant="secondary" onClick={() => setAdministration(v => !v)}>Upravljanje korisnicima</Button> : null}
    </header>
    {administration && state.session.user.role === "admin" ? <Users key={account.getSnapshot()?.key} account={account} /> : null}
    <DemoDataProvider key={account.getSnapshot()?.key}><App editorialIdentity={account} /></DemoDataProvider>
  </div>;
}

function Users({ account }: { account: SessionAccount }) {
  const [users, setUsers] = useState<Account[]>([]), [email, setEmail] = useState(""), [password, setPassword] = useState("");
  const [role, setRole] = useState("editor"), [error, setError] = useState(""), [busy, setBusy] = useState(false), [offset, setOffset] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void account.request(`/api/admin/users?limit=20&offset=${offset}`, { signal: controller.signal }).then(async r => {
      if (!r.ok) throw Error(); const data = await r.json(); if (!controller.signal.aborted) setUsers(data);
    }).catch(() => { if (!controller.signal.aborted) setError("Spisak korisnika nije dostupan."); });
    return () => controller.abort();
  }, [account, offset]);
  async function write(path: string, method: string, data: unknown) {
    if (busy) return; setBusy(true); setError("");
    try {
      const response = await account.request(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
      if (!response.ok) throw Error();
      const list = await account.request(`/api/admin/users?limit=20&offset=${offset}`);
      if (!list.ok) throw Error(); setUsers(await list.json());
      await account.bootstrap();
    } catch { setError("Izmena nije potvrđena. Proverite dozvole, reviziju i poslednjeg administratora pre ponavljanja."); }
    finally { setBusy(false); }
  }
  return <section className="space-y-4 bg-[#0b2a67] p-5 text-white" aria-label="Administracija korisnika">
    <h2 className="text-xl font-bold">Korisnici</h2>{error ? <p role="alert">{error}</p> : null}
    <form className="flex flex-wrap gap-3" onSubmit={e => { e.preventDefault(); const secret = password; setPassword(""); void write("/api/admin/users", "POST", { email, password: secret, role }); }}>
      <label>Email novog korisnika<input type="email" required autoComplete="off" maxLength={254} className="block rounded p-2 text-black" value={email} onChange={e => setEmail(e.target.value)} disabled={busy} /></label>
      <label>Početna lozinka<input type="password" required minLength={15} maxLength={128} autoComplete="new-password" className="block rounded p-2 text-black" value={password} onChange={e => setPassword(e.target.value)} disabled={busy} /></label>
      <label>Uloga<select className="block rounded p-2 text-black" value={role} onChange={e => setRole(e.target.value)} disabled={busy}><option value="editor">Urednik</option><option value="admin">Administrator</option></select></label>
      <Button disabled={busy}>Kreiraj korisnika</Button>
    </form>
    <ul className="space-y-3">{users.map(u => <li key={u.id} className="flex flex-wrap items-center gap-3 [overflow-wrap:anywhere]">
      <span>{u.email} · {u.role} · {u.active ? "Aktivan" : "Neaktivan"}</span>
      <Button disabled={busy} onClick={() => { if (window.confirm(`Promeniti status naloga ${u.email}?`)) void write(`/api/admin/users/${u.id}`, "PATCH", { expected_revision: u.revision, role: u.role, active: !u.active }); }}>{u.active ? "Deaktiviraj" : "Aktiviraj"}</Button>
      <Button disabled={busy} onClick={() => { if (window.confirm(`Promeniti ulogu naloga ${u.email}?`)) void write(`/api/admin/users/${u.id}`, "PATCH", { expected_revision: u.revision, role: u.role === "admin" ? "editor" : "admin", active: u.active }); }}>Promeni ulogu</Button>
    </li>)}</ul>
    <Button disabled={busy || offset === 0} onClick={() => setOffset(v => Math.max(0, v - 20))}>Prethodna stranica</Button>
    <Button disabled={busy || users.length < 20} onClick={() => setOffset(v => v + 20)}>Sledeća stranica</Button>
  </section>;
}
