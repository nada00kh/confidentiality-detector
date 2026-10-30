// Automated checks of the frontend API client (js/api.js) and of the workspace's answer check
// (js/workspace.js), without a browser and without packages:
//   node --test frontend/tests/api_client.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const CONFIG = read("js/config.js");
const API = read("js/api.js");
const WORKSPACE = read("js/workspace.js");

// Loads config.js and api.js as the pages do, with a stubbed fetch and a short scan timeout.
function client(fetchStub, timeoutMs = 100) {
  const calls = [];
  const sandbox = {
    window: {}, setTimeout, clearTimeout, AbortController, URLSearchParams,
    fetch: (url, options) => { calls.push({ url, options }); return fetchStub(url, options); }
  };
  vm.createContext(sandbox);
  vm.runInContext(CONFIG, sandbox);
  sandbox.window.WASHQ_CONFIG.CHECK_TIMEOUT_MS = timeoutMs;
  vm.runInContext(API, sandbox);
  return { api: sandbox.window.WashqAPI, calls };
}
const answer = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const ALLOW = { operation_id: "WSQ-000001", decision: "ALLOW", reason: "No sensitive data found",
  detected: [], safe_text: "hi", spans: [], pattern_hints: [] };
const BLOCK = { ...ALLOW, decision: "BLOCK", reason: "Sensitive data found, masked copy returned", safe_text: "[EMAIL]",
  detected: [{ type: "EMAIL", label: "Email address", count: 1 }], spans: [{ start: 0, end: 2, type: "EMAIL" }] };

test("the shipped configuration uses the local backend and a 60-second scan timeout", () => {
  assert.match(CONFIG, /USE_MOCK:\s*false/);
  assert.match(CONFIG, /API_BASE:\s*"http:\/\/localhost:8000"/);
  assert.match(CONFIG, /CHECK_TIMEOUT_MS:\s*60000/);
});

test("a normal answer is returned unchanged, and nothing is aborted", async () => {
  const { api, calls } = client(async () => answer(200, ALLOW));
  assert.deepEqual(await api.check("hi"), ALLOW);
  await delay(150);
  assert.equal(calls[0].options.signal.aborted, false);
});

test("a backend that never answers is stopped at the timeout", async () => {
  const { api, calls } = client((url, { signal }) => new Promise((_, reject) => {
    signal.addEventListener("abort", () => reject(new Error("aborted")));
  }));
  const started = Date.now();
  await assert.rejects(api.check("hi"), /No answer within \d+ seconds, so the scan was stopped/);
  assert.ok(Date.now() - started < 1000);
  assert.equal(calls[0].options.signal.aborted, true);
});

test("an answer that arrives after the timeout is never used", async () => {
  // This fetch ignores the abort signal and answers late.
  const { api } = client(async () => { await delay(300); return answer(200, ALLOW); });
  const outcomes = [];
  await api.check("hi").then(() => outcomes.push("result"), (e) => outcomes.push(e.message));
  await delay(400);
  assert.equal(outcomes.length, 1);
  assert.match(outcomes[0], /No answer within/);
});

test("network errors, error statuses and unreadable answers are failures, never results", async () => {
  await assert.rejects(client(async () => { throw new TypeError("Failed to fetch"); }).api.check("hi"),
    /Couldn’t reach the WASHQ server/);
  await assert.rejects(client(async () => answer(503, { detail: "Detection is not available right now." })).api.check("hi"),
    /Detection is not available right now/);
  await assert.rejects(client(async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError("bad"); } }))
    .api.check("hi"));
});

test("dashboard and logs requests are unchanged: no timeout, no abort signal", async () => {
  const { api, calls } = client(async () => answer(200, {}));
  await api.stats(7);
  await api.logs({ days: 7 });
  assert.deepEqual(calls.map((c) => c.options.signal), [undefined, undefined]);
});

test("only a complete answer is shown as a result", () => {
  const validCheck = new Function(`${WORKSPACE.match(/function validCheck\(r\) \{[\s\S]*?\n  \}/)[0]}; return validCheck;`)();
  assert.equal(validCheck(ALLOW), true);
  assert.equal(validCheck(BLOCK), true);
  assert.equal(validCheck({ ...BLOCK, safe_text: null }), true); // BLOCK that could not be masked: no copy offered
  for (const bad of [null, {}, "ALLOW", { ...ALLOW, decision: "MAYBE" }, { ...ALLOW, safe_text: "" },
    { ...ALLOW, safe_text: null }, { ...ALLOW, detected: null }, { ...BLOCK, pattern_hints: "hint" }]) {
    assert.equal(validCheck(bad), false);
  }
});
