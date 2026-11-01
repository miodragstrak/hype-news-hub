/** Run with Node 22+, Chrome, and the existing frontend dependencies:
 * node frontend/tests/browser/confirmation-dialog.mjs
 * Optional: CHROME_BIN, CHROME_NO_SANDBOX=1 (isolated CI), DIALOG_BROWSER_ARTIFACTS.
 */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
process.chdir(frontend);
const profile = await mkdtemp(path.join(tmpdir(), "hnh-dialog-chrome-"));
const artifacts = process.env.DIALOG_BROWSER_ARTIFACTS;
if (artifacts) await mkdir(artifacts, { recursive: true });
const results = [], errors = [], waiters = new Map(); let chrome, server, socket, sequence = 0;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const deadline = (test, label, milliseconds = 15_000) => (async () => {
  const end = Date.now() + milliseconds;
  while (Date.now() < end) { const value = await test(); if (value) return value; await delay(25); }
  throw new Error(`Timed out: ${label}`);
})();
function cdp(method, params = {}) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { waiters.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15_000);
    waiters.set(id, { resolve: value => { clearTimeout(timer); resolve(value); }, reject: error => { clearTimeout(timer); reject(error); } });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
async function js(expression) {
  const result = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result.value;
}
const settled = () => js("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
async function key(key, code, modifiers = 0) {
  await cdp("Input.dispatchKeyEvent", { type: "keyDown", key, code: key === " " ? "Space" : key, windowsVirtualKeyCode: code, modifiers });
  await cdp("Input.dispatchKeyEvent", { type: "keyUp", key, code: key === " " ? "Space" : key, windowsVirtualKeyCode: code, modifiers });
}
async function open(kind) {
  await js(`document.getElementById(${JSON.stringify("open-" + kind)}).focus(); document.getElementById(${JSON.stringify("open-" + kind)}).click()`);
  await deadline(() => js('Boolean(document.querySelector("[role=alertdialog]"))'), "open dialog"); await settled();
}
async function clickAction(confirm) {
  const target = await js(`(() => { const button = document.querySelectorAll('[role=alertdialog] button')[${confirm ? 1 : 0}], rect = button.getBoundingClientRect(), x = rect.left + rect.width / 2, y = rect.top + rect.height / 2; return { x, y, reachable: document.elementFromPoint(x, y)?.closest('button') === button }; })()`);
  assert.equal(target.reachable, true, "Action passes real pointer hit testing");
  await cdp("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", clickCount: 1 });
  await cdp("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", clickCount: 1 });
  await deadline(() => js('!document.querySelector("[role=alertdialog]")'), "close dialog");
}
async function measure() {
  await settled();
  return js(`(() => {
    const dialog = document.querySelector('[role=alertdialog]'), region = dialog.querySelector('[role=region]'), overlay = dialog.parentElement, rect = e => { const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height}; };
    const viewport = visualViewport || {offsetTop:0,offsetLeft:0,width:innerWidth,height:innerHeight}, textStyle = getComputedStyle(region);
    return {dialog:rect(dialog),region:rect(region),actions:[...dialog.querySelectorAll('button')].map(rect),viewport:{top:viewport.offsetTop,left:viewport.offsetLeft,width:viewport.width,height:viewport.height},padding:['Top','Right','Bottom','Left'].map(side=>parseFloat(getComputedStyle(overlay)['padding'+side])),scrollHeight:region.scrollHeight,clientHeight:region.clientHeight,scrollWidth:region.scrollWidth,clientWidth:region.clientWidth,lineHeight:parseFloat(textStyle.lineHeight),fontSize:parseFloat(textStyle.fontSize),horizontalOverflow:dialog.scrollWidth>dialog.clientWidth+1||region.scrollWidth>region.clientWidth+1||document.documentElement.scrollWidth>innerWidth+1,exact:document.getElementById(dialog.getAttribute('aria-describedby')).textContent===dialogFixture.expectedMessage,reasonLength:[...dialogFixture.reason].length,language:dialog.lang||document.documentElement.lang};
  })()`);
}
function assertLayout(value, label) {
  const { viewport: v, padding: p, dialog: d } = value;
  assert.ok(d.top >= v.top + p[0] - 1 && d.bottom <= v.top + v.height - p[2] + 1, `${label}: vertical bounds`);
  assert.ok(d.left >= v.left + p[3] - 1 && d.right <= v.left + v.width - p[1] + 1, `${label}: horizontal bounds`);
  assert.equal(value.horizontalOverflow, false, `${label}: horizontal overflow`);
  assert.equal(value.exact, true, `${label}: complete exact message`);
  assert.equal(value.fontSize, 16, `${label}: readable font size is unchanged`);
  assert.ok(Number.isFinite(value.lineHeight) && value.clientHeight >= value.lineHeight * 1.5, `${label}: message has practical reading space`);
  for (const action of value.actions) assert.ok(action.top >= d.top && action.bottom <= d.bottom && action.left >= d.left && action.right <= d.right, `${label}: actions reachable`);
}
try {
  server = await createServer({ root: frontend, configFile: path.join(frontend, "vite.config.ts"), server: { host: "127.0.0.1", port: 0 } });
  await server.listen(); const address = server.httpServer.address(); assert.ok(address && typeof address !== "string");
  chrome = spawn(process.env.CHROME_BIN || "google-chrome", ["--headless=new", "--disable-gpu", "--disable-dev-shm-usage", "--disable-background-networking", "--no-first-run", "--no-default-browser-check", ...(process.env.CHROME_NO_SANDBOX === "1" ? ["--no-sandbox"] : []), "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  let chromeFailure; chrome.on("error", error => { chromeFailure = error; });
  const port = await deadline(async () => { if (chromeFailure) throw chromeFailure; try { return (await readFile(path.join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]; } catch { return null; } }, "Chrome startup");
  const endpoint = `http://127.0.0.1:${port}`;
  const protocol = await (await fetch(`${endpoint}/json/protocol`)).json();
  const safeAreaCommand = protocol.domains.find(domain => domain.domain === "Emulation")?.commands.find(command => /^setSafeAreaInsets(?:Override)?$/.test(command.name));
  const page = (await (await fetch(`${endpoint}/json/list`)).json()).find(target => target.type === "page");
  socket = new WebSocket(page.webSocketDebuggerUrl); await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  socket.addEventListener("message", event => { const message = JSON.parse(String(event.data)); const waiter = waiters.get(message.id); if (waiter) { waiters.delete(message.id); message.error ? waiter.reject(new Error(JSON.stringify(message.error))) : waiter.resolve(message.result); } else if (message.method === "Runtime.exceptionThrown") errors.push(message.params.exceptionDetails.text); });
  await cdp("Page.enable"); await cdp("Runtime.enable"); await cdp("Network.enable"); await cdp("Network.setBlockedURLs", { urls: ["*fonts.googleapis.com*", "*fonts.gstatic.com*"] });
  for (const [width, height, kind] of [[390, 844, "decision"], [320, 568, "unbroken"], [320, 320, "decision"], [390, 300, "url"], [320, 240, "decision"], [640, 360, "unbroken"], [320, 240, "discard"], [320, 320, "discard"], [320, 568, "discard"], [390, 844, "discard"], [390, 300, "discard"], [640, 360, "discard"], [1440, 900, "discard"]]) {
    const label = `${width}x${height}-${kind}`;
    await cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 768 });
    await cdp("Page.navigate", { url: `http://127.0.0.1:${address.port}/tests/browser/confirmation-dialog.html` });
    await deadline(() => js('Boolean(document.getElementById("open-decision"))'), "fixture"); await open(kind);
    const value = await measure(); assertLayout(value, label);
    assert.equal(value.language, kind === "discard" ? "en" : "sr-Latn");
    if (kind !== "discard") { assert.equal(value.reasonLength, 2000); assert.ok(value.scrollHeight > value.clientHeight, `${label}: content scrolls`); }
    assert.equal(await js('document.activeElement===document.querySelectorAll("[role=alertdialog] button")[0]'), true);
    await key("Tab", 9); assert.equal(await js('document.activeElement===document.querySelectorAll("[role=alertdialog] button")[1]'), true);
    await key("Tab", 9); assert.equal(await js('document.activeElement===document.querySelector("[role=region]")'), true);
    // Enter/Space on message content must never activate a destructive action.
    await key("Enter", 13); await key(" ", 32);
    assert.deepEqual(await js('({confirmed:dialogFixture.confirmed,cancelled:dialogFixture.cancelled})'), { confirmed: 0, cancelled: 0 });
    if (value.scrollHeight > value.clientHeight) {
      await key("Home", 36); await deadline(() => js('document.querySelector("[role=region]").scrollTop===0'), "keyboard scroll to start");
      await key("ArrowDown", 40); await deadline(() => js('document.querySelector("[role=region]").scrollTop>0'), "keyboard scroll down");
      await key("End", 35); await deadline(() => js('(()=>{const r=document.querySelector("[role=region]");return r.scrollTop>=r.scrollHeight-r.clientHeight-1;})()'), "keyboard scroll to full message end");
      assert.equal(await js('(()=>{const r=document.querySelector("[role=region]"),t=r.querySelector("p").firstChild,a=document.createRange();a.setStart(t,t.length-1);a.setEnd(t,t.length);const glyph=a.getBoundingClientRect(),visible=r.getBoundingClientRect();return glyph.top>=visible.top&&glyph.bottom<=visible.bottom+1;})()'), true);
    }
    assert.deepEqual(await js('({confirmed:dialogFixture.confirmed,cancelled:dialogFixture.cancelled})'), { confirmed: 0, cancelled: 0 });
    await key("Tab", 9, 8); assert.equal(await js('document.activeElement===document.querySelectorAll("[role=alertdialog] button")[1]'), true);
    await key("Escape", 27); await deadline(() => js('!document.querySelector("[role=alertdialog]")'), "Escape cancels");
    assert.equal(await js(`document.activeElement.id===${JSON.stringify("open-" + kind)}`), true);
    await open(kind); await clickAction(false); await open(kind);
    if (artifacts) await writeFile(path.join(artifacts, `${label}.png`), Buffer.from((await cdp("Page.captureScreenshot", { format: "png" })).data, "base64"));
    await clickAction(true); assert.deepEqual(await js('({confirmed:dialogFixture.confirmed,cancelled:dialogFixture.cancelled})'), { confirmed: 1, cancelled: 2 });
    results.push({ viewport: label, dialogHeight: value.dialog.height, scrollHeight: value.scrollHeight, visibleContentHeight: value.clientHeight, lineHeight: value.lineHeight, fontSize: value.fontSize, actionBounds: value.actions, horizontalOverflow: value.horizontalOverflow, actionsReachable: true, exactMessage: value.exact });
  }
  await cdp("Emulation.setDeviceMetricsOverride", { width: 320, height: 568, deviceScaleFactor: 1, mobile: true }); await open("discard");
  await cdp("Emulation.setDeviceMetricsOverride", { width: 320, height: 240, deviceScaleFactor: 1, mobile: true });
  await deadline(() => js('document.querySelector("[role=alertdialog]").parentElement.style.height==="240px"'), "live compact discard resize");
  assertLayout(await measure(), "live compact discard resize"); await clickAction(false);
  // Resize an already-open dialog, as when mobile browser chrome/keyboard reduces space.
  await cdp("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true }); await open("decision");
  await cdp("Emulation.setDeviceMetricsOverride", { width: 390, height: 300, deviceScaleFactor: 1, mobile: true });
  await deadline(() => js('document.querySelector("[role=alertdialog]").parentElement.style.height==="300px"'), "live visual viewport resize");
  assertLayout(await measure(), "live height reduction");
  await cdp("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true }); await settled();
  await cdp("Emulation.setPageScaleFactor", { pageScaleFactor: 1.5 }); await settled(); assertLayout(await measure(), "visual viewport zoom");
  await cdp("Emulation.setPageScaleFactor", { pageScaleFactor: 1 }); await settled();
  if (safeAreaCommand) {
    await cdp("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
    await cdp(`Emulation.${safeAreaCommand.name}`, { insets: { top: 47, bottom: 34, left: 0, right: 0 } });
    const value = await measure(); assertLayout(value, "safe areas"); assert.equal(value.padding[0], 47); assert.equal(value.padding[2], 34);
    results.push({ viewport: "390x844-safe-areas", dialogHeight: value.dialog.height, padding: value.padding, actionsReachable: true });
    await cdp("Emulation.setDeviceMetricsOverride", { width: 640, height: 360, deviceScaleFactor: 1, mobile: true });
    await cdp(`Emulation.${safeAreaCommand.name}`, { insets: { top: 0, bottom: 21, left: 44, right: 44 } });
    const landscape = await measure(); assertLayout(landscape, "landscape safe areas");
    assert.equal(landscape.padding[1], 44); assert.equal(landscape.padding[3], 44);
    results.push({ viewport: "640x360-safe-areas", dialogHeight: landscape.dialog.height, padding: landscape.padding, actionsReachable: true });
  }
  await clickAction(false); assert.deepEqual(errors, []);
  const report = { results, liveResize: "passed", visualViewportZoom: "passed", safeAreas: safeAreaCommand ? "passed" : "unsupported by installed Chrome", errors };
  if (artifacts) await writeFile(path.join(artifacts, "results.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally {
  socket?.close(); if (chrome && chrome.exitCode === null) { chrome.kill("SIGTERM"); await Promise.race([new Promise(resolve => chrome.once("exit", resolve)), delay(3000)]); if (chrome.exitCode === null) chrome.kill("SIGKILL"); }
  await server?.close(); await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
