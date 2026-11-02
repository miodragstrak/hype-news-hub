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
const profile = await mkdtemp(path.join(tmpdir(), "hnh-ai-chrome-"));
const artifacts = process.env.AI_BROWSER_ARTIFACTS;
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
async function key(value, code) {
  await cdp("Input.dispatchKeyEvent", { type: "keyDown", key: value, code: value, windowsVirtualKeyCode: code });
  await cdp("Input.dispatchKeyEvent", { type: "keyUp", key: value, code: value, windowsVirtualKeyCode: code });
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
  for (const [width, height] of [[1440, 900], [390, 844], [320, 568], [640, 360]]) {
    await cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 768 });
    await cdp("Page.navigate", { url: `http://127.0.0.1:${address.port}/tests/browser/ai-workspace.html` });
    await until(() => js(`Boolean(document.querySelector('select')&&[...document.querySelectorAll('button')].some(b=>b.textContent.startsWith('Prikaži predlog')))`), "workspace load");
    await click("Prikaži predlog"); await until(() => js("Boolean(document.querySelector('article[aria-label=\"Sadržaj AI predloga\"]'))"), "lazy detail");
    const measurements = await js(`(() => { const grid=document.querySelector('[data-testid=ai-comparison]'), panels=[...grid.children].map(p=>{const r=p.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}}), regions=[...grid.querySelectorAll('[role=region]')];return {viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,columns:getComputedStyle(grid).gridTemplateColumns,panels,horizontalOverflow:[...grid.querySelectorAll('*')].some(e=>e.scrollWidth>e.clientWidth+2&&getComputedStyle(e).display!=='inline'&&e.clientWidth>0),regions:regions.map(r=>({height:r.clientHeight,scroll:r.scrollHeight})),posts:aiFixture.posts.length}; })()`);
    assert.ok(measurements.documentWidth <= width + 1, "No page overflow");
    assert.equal(measurements.horizontalOverflow, false, "Long words and hashes wrap");
    assert.equal(measurements.posts, 0, "History is read-only");
    if (width >= 1024) assert.ok(Math.abs(measurements.panels[0].y - measurements.panels[1].y) < 2, "Desktop comparison is adjacent");
    else assert.ok(measurements.panels[1].y > measurements.panels[0].y + measurements.panels[0].height - 2, "Mobile comparison stacks");
    assert.ok(measurements.regions.every(region => region.scroll > region.height && region.height > 50), "Long text has bounded scroll areas");
    await js(`document.querySelector('[aria-label="Tekst AI predloga"]').focus()`); await key("End", 35);
    await until(() => js(`document.querySelector('[aria-label="Tekst AI predloga"]').scrollTop>0`), "keyboard scrolling");
    assert.equal(await js("aiFixture.posts.length"), 0);
    if (artifacts) await writeFile(path.join(artifacts, `${width}x${height}.png`), Buffer.from((await cdp("Page.captureScreenshot", { format: "png" })).data, "base64"));
    results.push({ width, height, ...measurements });
  }
  await js("aiFixture.lose()"); await click("Generiši AI predlog");
  await until(() => js(`document.body.textContent.includes('Ishod komande nije potvrđen')`), "uncertain generation");
  assert.equal(await js("aiFixture.posts.length"), 1);
  await click("Oporavi istu komandu"); await click("Pošalji istu komandu");
  await until(() => js(`Boolean(document.querySelector('article'))&&!document.querySelector('[aria-label="Oporavak AI komande"]')`), "explicit recovery");
  assert.equal(await js("JSON.stringify(aiFixture.posts[0])===JSON.stringify(aiFixture.posts[1])"), true);
  await js("aiFixture.hold()"); await click("Generiši AI predlog");
  await until(() => js("aiFixture.posts.length===3"), "pending generation");
  await js("aiFixture.logout();aiFixture.release()");
  await until(() => js(`document.body.textContent.includes('Sign in through your newsroom identity provider')`), "logout");
  assert.equal(await js("Boolean(document.querySelector('article')||document.querySelector('[data-testid=ai-comparison]'))"), false);
  assert.deepEqual(errors, []);
  const report = { results, keyboardScrolling: "passed", sameCommandRecovery: "passed", logoutDuringGeneration: "passed", liveProviderCalls: 0, errors };
  if (artifacts) await writeFile(path.join(artifacts, "results.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally {
  socket?.close(); if (chrome && chrome.exitCode === null) { chrome.kill("SIGTERM"); await Promise.race([new Promise(resolve => chrome.once("exit", resolve)), delay(3000)]); if (chrome.exitCode === null) chrome.kill("SIGKILL"); }
  await server?.close(); await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
