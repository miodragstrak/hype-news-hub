/** Node 22+, existing Vite dependencies and Chrome. All HTTP/provider responses are fixtures. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
process.chdir(frontend);
const profile = await mkdtemp(path.join(tmpdir(), "hnh-queue-chrome-"));
const artifacts = process.env.QUEUE_BROWSER_ARTIFACTS;
if (artifacts) await mkdir(artifacts, { recursive: true });
let server, chrome, socket, sequence = 0;
const waiters = new Map(), errors = [], results = [];
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
async function until(test, label) {
  const end = Date.now() + 15000;
  while (Date.now() < end) { const result = await test(); if (result) return result; await delay(25); }
  throw new Error("Timed out: " + label);
}
function cdp(method, params = {}) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { waiters.delete(id); reject(new Error(method)); }, 15000);
    waiters.set(id, { resolve: value => { clearTimeout(timer); resolve(value); }, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
async function js(expression) {
  const result = await cdp("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || "Browser exception");
  return result.result.value;
}
const click = label => js(`(() => { const button=[...document.querySelectorAll('button')].find(b=>b.textContent.startsWith(${JSON.stringify(label)})); if(!button||button.disabled) throw Error('Missing enabled button');button.scrollIntoView({block:'center'});button.click(); })()`);
async function key(value, code, modifiers = 0) {
  await cdp("Input.dispatchKeyEvent", { type: "keyDown", key: value, code: value, windowsVirtualKeyCode: code, modifiers, ...(value === "Enter" ? { text: "\r", unmodifiedText: "\r" } : {}) });
  await cdp("Input.dispatchKeyEvent", { type: "keyUp", key: value, code: value, windowsVirtualKeyCode: code, modifiers });
}
try {
  server = await createServer({ root: frontend, server: { host: "127.0.0.1", port: 0 }, define: {
    "import.meta.env.VITE_API_URL": JSON.stringify("https://backend.invalid"), "import.meta.env.VITE_DEMO_MODE": JSON.stringify("false"),
  } });
  await server.listen(); const address = server.httpServer.address();
  chrome = spawn(process.env.CHROME_BIN || "google-chrome", ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--remote-debugging-port=0", `--user-data-dir=${profile}`, ...(process.env.CHROME_NO_SANDBOX === "1" ? ["--no-sandbox"] : []), "about:blank"], { stdio: "ignore" });
  const port = await until(async () => { try { return (await readFile(path.join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]; } catch { return null; } }, "Chrome startup");
  const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  socket = new WebSocket(pages.find(page => page.type === "page").webSocketDebuggerUrl);
  await new Promise(resolve => { socket.onopen = resolve; });
  socket.onmessage = event => { const data = JSON.parse(event.data); if (data.id) { const waiter = waiters.get(data.id); if (waiter) { waiters.delete(data.id); if (data.error) waiter.reject(new Error(JSON.stringify(data.error))); else waiter.resolve(data.result); } } else if (data.method === "Runtime.exceptionThrown") errors.push(data.params.exceptionDetails.text); };
  await cdp("Page.enable"); await cdp("Runtime.enable"); await cdp("Network.enable");
  await cdp("Network.setBlockedURLs", { urls: ["*fonts.googleapis.com*", "*fonts.gstatic.com*", "*generativelanguage.googleapis.com*", "*backend.invalid*"] });
  for (const [width,height] of [[1440,900],[390,844],[320,568]]) {
    await cdp("Emulation.setDeviceMetricsOverride",{width,height,deviceScaleFactor:1,mobile:width<768});
    await cdp("Page.navigate",{url:`http://127.0.0.1:${address.port}/tests/browser/editorial-queue.html`});
    await until(()=>js(`Boolean(document.querySelector('ul[aria-label="Priče u uredničkom redu"]'))`),'private queue');
    const metrics=await js(`(()=>{const list=document.querySelector('ul[aria-label="Priče u uredničkom redu"]');return {width:innerWidth,page:document.documentElement.scrollWidth,rows:list.children.length,overflow:[list,...list.querySelectorAll('*')].some(e=>e.clientWidth>0&&e.scrollWidth>e.clientWidth+2&&getComputedStyle(e).display!=='inline'),images:list.querySelectorAll('img').length,publicFallback:document.body.textContent.includes('PUBLIC FALLBACK'),recoveryButtons:[...list.querySelectorAll('button')].length};})()`);
    assert.ok(metrics.page<=width+1&&!metrics.overflow,'Queue wraps on mobile without clipping');
    assert.equal(metrics.rows,20);assert.equal(metrics.images,0);assert.equal(metrics.publicFallback,false);assert.equal(metrics.recoveryButtons,0);
    const review=await js(`document.querySelector('nav[aria-label^="Rad sa pričom"] a').getAttribute('href')`);
    const workspace=await js(`document.querySelector('nav[aria-label^="Rad sa pričom"] a:last-child').getAttribute('href')`);
    assert.equal(workspace,review+'/ai');
    await js(`document.querySelector('input[type=search]').focus()`);await key('Tab',9);
    assert.equal(await js(`document.activeElement.parentElement.textContent.startsWith('Urednički status')`),true);
    await key('Tab',9);assert.equal(await js(`document.activeElement.parentElement.textContent.startsWith('AI status')`),true);
    await click('Sledeća stranica');
    await until(()=>js(`Boolean(document.querySelector('ul[aria-label="Priče u uredničkom redu"]')?.textContent.includes('Privatna vest 23'))`),'last page');
    assert.equal(await js(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Sledeća stranica').disabled`),true);
    await js(`queueFixture.fail(503)`);await click('Osveži red');
    await until(()=>js(`Boolean(document.querySelector('[role=alert]'))`),'unavailable state');
    assert.equal(await js(`Boolean(document.querySelector('ul[aria-label="Priče u uredničkom redu"]'))||document.body.textContent.includes('PUBLIC FALLBACK')||document.body.textContent.includes('SENSITIVE')`),false);
    await js(`queueFixture.fail(0)`);await click('Pokušaj ponovo');
    await until(()=>js(`Boolean(document.querySelector('ul[aria-label="Priče u uredničkom redu"]'))`),'explicit retry');
    assert.equal(await js(`queueFixture.calls.every(call=>call.method==='GET')`),true);
    await js(`queueFixture.logout()`);await until(()=>js(`document.body.textContent.includes('Prijavite se za pregled')`),'logout clears queue');
    assert.equal(await js(`Boolean(document.querySelector('ul[aria-label="Priče u uredničkom redu"]'))`),false);
    results.push({width,height,...metrics,keyboard:'passed',pagination:'passed',retry:'passed',logout:'passed',mutations:0});
  }
  assert.deepEqual(errors,[]);
  const report={results,liveProviderCalls:0,errors};
  if(artifacts)await writeFile(path.join(artifacts,'results.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
} finally {
  socket?.close(); if (chrome && chrome.exitCode === null) { chrome.kill("SIGTERM"); await Promise.race([new Promise(resolve => chrome.once("exit", resolve)), delay(3000)]); if (chrome.exitCode === null) chrome.kill("SIGKILL"); }
  await server?.close(); await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
