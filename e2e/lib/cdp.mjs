// Minimal Chrome DevTools Protocol driver for the end-to-end suite.
// No dependencies: Node 22's built-in WebSocket and the system Chrome.
//
// Each `newPage()` opens a tab in its own browser context (separate cookies and
// storage), so two founders never share a session by accident.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

export const CHROME = process.env.E2E_CHROME ?? "google-chrome";

export async function launchBrowser({ port, caCertificateSpki }) {
  const profile = mkdtempSync(join(tmpdir(), "heroos-e2e-chrome-"));
  const args = [
    "--headless=new",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-gpu",
    "--hide-scrollbars",
    "--force-color-profile=srgb",
    "--disable-features=Translate,OptimizationHints,MediaRouter",
    // Trust exactly this run's CA (by public-key pin), not "ignore all errors".
    `--ignore-certificate-errors-spki-list=${caCertificateSpki}`,
    "about:blank",
  ];
  if (process.env.CI) args.unshift("--no-sandbox");
  // Own process group: Chrome's helper processes are stopped with it.
  const chrome = spawn(CHROME, args, { stdio: "ignore", detached: true });
  let version;
  for (let attempt = 0; attempt < 150 && !version; attempt += 1) {
    try {
      version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
    } catch {
      await sleep(100);
    }
  }
  if (!version) throw new Error("Chrome did not start");
  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((done, fail) => {
    ws.addEventListener("open", done, { once: true });
    ws.addEventListener("error", fail, { once: true });
  });

  let nextId = 0;
  const pending = new Map();
  const listeners = new Set();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
    } else if (message.method) {
      for (const listener of listeners) listener(message);
    }
  });
  const send = (method, params = {}, sessionId) =>
    new Promise((resolve, reject) => {
      nextId += 1;
      pending.set(nextId, { resolve, reject });
      ws.send(JSON.stringify({ id: nextId, method, params, ...(sessionId ? { sessionId } : {}) }));
    });

  const browser = {
    send,
    async newPage() {
      const { browserContextId } = await send("Target.createBrowserContext", { disposeOnDetach: true });
      const { targetId } = await send("Target.createTarget", { url: "about:blank", browserContextId });
      const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
      return createPage({ send, listeners, sessionId, targetId, browserContextId });
    },
    async close() {
      const exited = new Promise((done) => (chrome.exitCode !== null ? done() : chrome.once("exit", done)));
      try {
        await send("Browser.close");
      } catch {
        // already gone
      }
      ws.close();
      await Promise.race([exited, sleep(5000)]);
      // Whatever is left of the group (helpers, a hung browser) goes too.
      try {
        process.kill(-chrome.pid, "SIGKILL");
      } catch {
        // group already gone
      }
      await sleep(500);
      rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
    },
  };
  return browser;
}

async function createPage({ send, listeners, sessionId, targetId, browserContextId }) {
  const call = (method, params) => send(method, params, sessionId);
  const console = [];
  const network = [];
  const responses = [];
  let currentUrl = "about:blank";
  let interceptor = null;
  const listener = (message) => {
    if (message.sessionId !== sessionId) return;
    const { method, params } = message;
    if (method === "Page.frameNavigated" && !params.frame.parentId) currentUrl = params.frame.url;
    if (method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(params.type)) {
      console.push({ url: currentUrl, level: params.type, text: params.args.map((a) => a.value ?? a.description).join(" ") });
    }
    if (method === "Runtime.exceptionThrown") {
      console.push({ url: currentUrl, level: "exception", text: params.exceptionDetails.exception?.description ?? params.exceptionDetails.text });
    }
    if (method === "Log.entryAdded") {
      console.push({ url: currentUrl, level: params.entry.level, source: params.entry.source, text: params.entry.text });
    }
    if (method === "Network.requestWillBeSent") {
      network.push({ url: params.request.url, method: params.request.method, documentUrl: params.documentURL });
    }
    if (method === "Network.responseReceived") {
      responses.push({ url: params.response.url, status: params.response.status, headers: params.response.headers });
    }
    if (method === "Fetch.requestPaused" && interceptor) {
      interceptor(params).catch(() => {});
    }
  };
  listeners.add(listener);
  await call("Page.enable");
  await call("Runtime.enable");
  await call("Log.enable");
  await call("Network.enable");

  const page = {
    console,
    network,
    responses,
    get url() {
      return currentUrl;
    },
    call,
    async close() {
      listeners.delete(listener);
      try {
        await send("Target.closeTarget", { targetId });
        await send("Target.disposeBrowserContext", { browserContextId });
      } catch {
        // context may already be gone
      }
    },
    async viewport(width, height = 900, { deviceScaleFactor = 1 } = {}) {
      await call("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor, mobile: width < 768 });
    },
    async emulateMedia(features) {
      await call("Emulation.setEmulatedMedia", { features });
    },
    async eval(expression) {
      const result = await call("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
      if (result.exceptionDetails) {
        throw new Error(`eval failed: ${result.exceptionDetails.exception?.description ?? result.exceptionDetails.text}`);
      }
      return result.result.value;
    },
    async waitFor(expression, { timeout = 30_000, message } = {}) {
      const start = Date.now();
      for (;;) {
        try {
          if (await page.eval(`Boolean(${expression})`)) return;
        } catch {
          // navigating
        }
        if (Date.now() - start > timeout) throw new Error(`timeout: ${message ?? expression}`);
        await sleep(100);
      }
    },
    async goto(url) {
      // Mark the current document: the outgoing page still reports "complete"
      // until the navigation commits, so waiting on readyState alone could act
      // on the old page (a lost click or save). Wait for the new document.
      await page.eval("window.__e2eOutgoing = true").catch(() => {});
      await call("Page.navigate", { url });
      await page.waitFor("!window.__e2eOutgoing && document.readyState === 'complete'", { message: `load ${url}` });
    },
    async waitForText(text, options) {
      try {
        await page.waitFor(`document.body && document.body.innerText.includes(${JSON.stringify(text)})`, {
          message: `text "${text}"`,
          ...options,
        });
      } catch (error) {
        // Say what the page showed instead (synthetic test data only).
        const seen = await page
          .eval("`${location.pathname} | ${document.body ? document.body.innerText.replace(/\\s+/g, ' ').slice(0, 400) : ''}`")
          .catch(() => "unavailable");
        throw new Error(`${error.message} (page: ${seen})`);
      }
    },
    /** Waits until React has hydrated the element (its props are attached). */
    async waitForHydrated(selector) {
      await page.waitFor(
        `(() => { const el = document.querySelector(${JSON.stringify(selector)}); return el && Object.keys(el).some((k) => k.startsWith("__reactProps")); })()`,
        { message: `hydrated ${selector}` },
      );
    },
    async text() {
      return page.eval("document.body ? document.body.innerText : ''");
    },
    async html() {
      return page.eval("document.documentElement.outerHTML");
    },
    async type(selector, value) {
      await page.eval(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) throw new Error("no element " + ${JSON.stringify(selector)});
        el.focus();
        const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, "value").set.call(el, ${JSON.stringify(value)});
        el.dispatchEvent(new Event("input", { bubbles: true }));
        return true;
      })()`);
    },
    async click(selector) {
      await page.eval(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) throw new Error("no element " + ${JSON.stringify(selector)});
        el.click();
        return true;
      })()`);
    },
    async clickText(selector, text) {
      await page.eval(`(() => {
        const el = [...document.querySelectorAll(${JSON.stringify(selector)})]
          .find((e) => e.offsetParent !== null && e.textContent.trim().startsWith(${JSON.stringify(text)}));
        if (!el) throw new Error("no visible element with text " + ${JSON.stringify(text)});
        el.click();
        return true;
      })()`);
    },
    /** Real keyboard input (Tab, Enter, Escape, ...) through the browser. */
    async press(key) {
      const codes = { Tab: 9, Enter: 13, Escape: 27, Space: 32, ArrowDown: 40 };
      const base = { key, code: key, windowsVirtualKeyCode: codes[key] ?? 0 };
      await call("Input.dispatchKeyEvent", { type: "keyDown", ...base, ...(key === "Enter" ? { text: "\r" } : {}) });
      await call("Input.dispatchKeyEvent", { type: "keyUp", ...base });
    },
    async overflow() {
      return page.eval("document.documentElement.scrollWidth - window.innerWidth");
    },
    async screenshot(path) {
      await page.eval("window.scrollTo({ top: 0, behavior: 'instant' })");
      const { cssContentSize } = await call("Page.getLayoutMetrics");
      const shot = await call("Page.captureScreenshot", {
        format: "png",
        captureBeyondViewport: true,
        clip: { x: 0, y: 0, width: Math.ceil(cssContentSize.width), height: Math.min(Math.ceil(cssContentSize.height), 8000), scale: 1 },
      });
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, Buffer.from(shot.data, "base64"));
    },
    /** A screenshot of one element (its full box, even beyond the viewport), at most 8000 px tall. */
    async screenshotOf(path, selector) {
      // From the top, as for a full page: a sticky header then sits above the
      // element instead of being drawn over it.
      await page.eval("window.scrollTo({ top: 0, behavior: 'instant' })");
      const box = await page.eval(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) throw new Error("no element " + ${JSON.stringify(selector)});
        const r = el.getBoundingClientRect();
        return { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height };
      })()`);
      const shot = await call("Page.captureScreenshot", {
        format: "png",
        captureBeyondViewport: true,
        clip: { x: Math.floor(box.x), y: Math.floor(box.y), width: Math.ceil(box.width), height: Math.min(Math.ceil(box.height), 8000), scale: 1 },
      });
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, Buffer.from(shot.data, "base64"));
    },
    async setCookie(cookie) {
      await call("Network.setCookie", cookie);
    },
    async cookies(urls) {
      return (await call("Network.getCookies", { urls })).cookies;
    },
    /**
     * Intercept responses whose URL matches `urlPattern`; `handler(params)`
     * decides (continue, fail, ...). Pass null to stop intercepting.
     */
    async interceptResponses(urlPattern, handler) {
      if (!handler) {
        interceptor = null;
        await call("Fetch.disable");
        return;
      }
      interceptor = handler;
      await call("Fetch.enable", { patterns: [{ urlPattern, requestStage: "Response" }] });
    },
    async addInitScript(source) {
      await call("Page.addScriptToEvaluateOnNewDocument", { source });
    },
  };
  return page;
}
