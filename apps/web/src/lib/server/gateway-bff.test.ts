// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { API_BASE_URL, COMPANY_ID, CONFIG, WEB_ORIGIN } from "@/test/fixtures";

import { askGateway } from "./app-state";
import {
  handleConversationDetail,
  handleConversationList,
  handleConversationMessages,
  handleGatewayMessage,
  MAX_ASSISTANT_BYTES,
} from "./bff";
import { SESSION_COOKIE } from "./cookies";
import { GATEWAY_TIMEOUT_MS } from "./heroos-api";
import { seal } from "./sealed";

const NOW = 1_800_000_000_000;
const ACCESS_TOKEN = "header.secret-access-token.signature";
const path = `/bff/companies/${COMPANY_ID}/assistant/messages`;
const CONVERSATION_ID = "9b1f3c3e-6a52-4b8f-9d0a-2c1e5f6a7b8c";
const CASE_ID = "1a2b3c4d-5e6f-4a1b-8c9d-0e1f2a3b4c5d";
const TURN_KEY = "0f9e8d7c-6b5a-4c3d-9e2f-1a0b9c8d7e6f";
const BODY = {
  message: "He improved after that and hasn't been late again.",
  turnKey: TURN_KEY,
  conversationId: CONVERSATION_ID,
  expectedRevision: 2,
};
const OUTCOME = {
  kind: "block",
  title: "Not yet: Written warning",
  message: "Don't take this step yet: a written warning can't safely proceed yet.",
  items: [
    { kind: "block", text: "Written warning: can't safely proceed yet" },
    { kind: "guidance", text: "Workplace reminder: no HeroOS rule prevents it on what's established so far" },
  ],
};
const AT = "2026-10-22T10:00:00Z";
const API_STATUS = {
  lifecycle: "in_progress",
  workflow: { key: "disciplinary", title: "Disciplinary" },
  attention: {
    needs_information: false,
    jurisdiction: null,
    expert_review: { active: true, scope: "action", actions: ["Dismissal without notice"], service_available: false },
  },
  checks: "ready",
  latest_outcome: "guidance",
};
const STATUS = {
  lifecycle: "in_progress",
  workflow: { key: "disciplinary", title: "Disciplinary" },
  attention: {
    needsInformation: false,
    jurisdiction: null,
    expertReview: { active: true, scope: "action", actions: ["Dismissal without notice"], serviceAvailable: false },
  },
  checks: "ready",
  latestOutcome: "guidance",
};
const API_CONVERSATION = {
  id: CONVERSATION_ID,
  title: "Disciplinary case · 22 Oct",
  case: { id: CASE_ID, title: "Disciplinary case · 22 Oct" },
  created_at: AT,
  updated_at: AT,
  revision: 3,
  status: API_STATUS,
};
const CONVERSATION = {
  id: CONVERSATION_ID,
  title: "Disciplinary case · 22 Oct",
  case: { id: CASE_ID, title: "Disciplinary case · 22 Oct" },
  createdAt: AT,
  updatedAt: AT,
  revision: 3,
  status: STATUS,
};
const API_MESSAGES = [
  { sequence: 5, author: "you", text: BODY.message, safe_next_step: null, conversation_state: null, outcome: null, created_at: AT },
  {
    sequence: 6,
    author: "heroos",
    text: "That's good to hear: improvement after a conversation can be where this ends.",
    safe_next_step: "Keep a short note of the conversation and the improvement.",
    conversation_state: "responded",
    outcome: null,
    created_at: AT,
  },
];
const MESSAGES = [
  { sequence: 5, author: "you", text: BODY.message, safeNextStep: null, conversationState: null, outcome: null, createdAt: AT },
  {
    sequence: 6,
    author: "heroos",
    text: API_MESSAGES[1].text,
    safeNextStep: API_MESSAGES[1].safe_next_step,
    conversationState: "responded",
    outcome: null,
    createdAt: AT,
  },
];
const API_TURN = { conversation: API_CONVERSATION, messages: API_MESSAGES, replayed: false };

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
const cookie = () =>
  `${SESSION_COOKIE}=${seal({ accessToken: ACCESS_TOKEN, exp: NOW / 1000 + 600 }, CONFIG.sessionSecret, "session")}`;
const headers = { origin: WEB_ORIGIN, "sec-fetch-site": "same-origin", cookie: cookie() };

function post(body: unknown, { headers: extra = {}, raw = null as string | null, companyPath = path } = {}) {
  return new Request(`${WEB_ORIGIN}${companyPath}`, {
    method: "POST",
    headers: { ...headers, cookie: cookie(), "content-type": "application/json", ...extra },
    body: raw ?? JSON.stringify(body),
  });
}

function get(target: string, extra: Record<string, string> = {}) {
  return new Request(`${WEB_ORIGIN}${target}`, { method: "GET", headers: { ...headers, cookie: cookie(), ...extra } });
}

function api(response: Response | Error) {
  const fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  return { fetch: fetchMock as unknown as typeof fetch, fetchMock, now: () => NOW };
}

describe("handleGatewayMessage (Ask HeroOS, persistent)", () => {
  it("forwards only the words, turn key, conversation and revision; passes on the stored turn", async () => {
    const deps = api(json(API_TURN));
    const response = await handleGatewayMessage(post(BODY), CONFIG, COMPANY_ID, deps);
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual({ conversation: CONVERSATION, messages: MESSAGES, replayed: false });
    const [url, init] = deps.fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE_URL}/companies/${COMPANY_ID}/assistant/messages`);
    expect(init?.method).toBe("POST");
    expect(init?.redirect).toBe("error");
    expect((init?.headers as Record<string, string>).Authorization).toBe(`Bearer ${ACCESS_TOKEN}`);
    expect(JSON.parse(String(init?.body))).toEqual({
      message: BODY.message,
      turn_key: TURN_KEY,
      expected_revision: 2,
      conversation_id: CONVERSATION_ID,
    });
  });

  it("starts a new conversation at revision 0 with no conversation id", async () => {
    const deps = api(json(API_TURN));
    const first = { message: "Hello", turnKey: TURN_KEY, conversationId: null, expectedRevision: 0 };
    expect((await handleGatewayMessage(post(first), CONFIG, COMPANY_ID, deps)).status).toBe(200);
    expect(JSON.parse(String(deps.fetchMock.mock.calls[0][1]?.body))).toEqual({
      message: "Hello",
      turn_key: TURN_KEY,
      expected_revision: 0,
    });
  });

  it("passes on nothing but the turn's own fields, and refuses anything more inside them", async () => {
    const extra = { ...API_TURN, provider: "groq" };
    expect((await handleGatewayMessage(post(BODY), CONFIG, COMPANY_ID, api(json(extra)))).status).toBe(503);
    for (const broken of [
      { ...API_TURN, conversation: { ...API_CONVERSATION, checkpoint: {} } },
      { ...API_TURN, conversation: { ...API_CONVERSATION, status: { ...API_STATUS, lifecycle: "closed" } } },
      { ...API_TURN, conversation: { ...API_CONVERSATION, status: { ...API_STATUS, record: {} } } },
      { ...API_TURN, messages: [API_MESSAGES[0], { ...API_MESSAGES[1], actor_user_id: "x" }] },
      { ...API_TURN, messages: [API_MESSAGES[0], { ...API_MESSAGES[1], outcome: { ...OUTCOME, rule: "fictional_cap" } }] },
      { ...API_TURN, messages: [API_MESSAGES[0], { ...API_MESSAGES[1], outcome: { ...OUTCOME, kind: "allow" } }] },
      { ...API_TURN, messages: [API_MESSAGES[0], { ...API_MESSAGES[1], author: "you" }] },
      { ...API_TURN, messages: [API_MESSAGES[0]] },
    ]) {
      const refused = await handleGatewayMessage(post(BODY), CONFIG, COMPANY_ID, api(json(broken)));
      expect(refused.status).toBe(503);
    }
    const card = { ...API_TURN, messages: [API_MESSAGES[0], { ...API_MESSAGES[1], outcome: OUTCOME }] };
    const body = await (await handleGatewayMessage(post(BODY), CONFIG, COMPANY_ID, api(json(card)))).json();
    expect(body.messages[1].outcome).toEqual(OUTCOME);
  });

  it.each([
    ["history", { history: [{ role: "user", content: "Earlier." }] }],
    ["a continuation", { continuation: "e1.abcdefgh.AAAA" }],
    ["facts", { facts: { x: "yes" } }],
    ["an outcome", { outcome: "guidance" }],
    ["conditions", { conditions: [] }],
    ["a workflow", { workflow: "disciplinary" }],
    ["a jurisdiction", { jurisdiction: "difc" }],
    ["a case id", { caseId: CASE_ID }],
    ["an evaluation", { evaluation: {} }],
    ["a checkpoint", { checkpoint: {} }],
    ["a chosen model", { model: "gpt-4" }],
    ["a blank message", { message: "   " }],
    ["a control character", { message: "a\u0000b" }],
    ["a long message", { message: "x".repeat(2001) }],
    ["a missing turn key", { turnKey: undefined }],
    ["a malformed turn key", { turnKey: "not-a-uuid" }],
    ["a malformed conversation", { conversationId: "x" }],
    ["a negative revision", { expectedRevision: -1 }],
    ["a revision as text", { expectedRevision: "2" }],
    ["a new conversation past revision 0", { conversationId: null, expectedRevision: 2 }],
  ])("refuses %s before reaching the API", async (_label, change) => {
    const deps = api(json(API_TURN));
    const response = await handleGatewayMessage(post({ ...BODY, ...change }), CONFIG, COMPANY_ID, deps);
    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({ error: "invalid", fields: [] });
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("refuses cross-site, oversized and session-less requests and a malformed company id", async () => {
    const deps = api(json(API_TURN));
    const crossSite = post(BODY, { headers: { origin: "https://evil.example", "sec-fetch-site": "cross-site" } });
    expect((await handleGatewayMessage(crossSite, CONFIG, COMPANY_ID, deps)).status).toBe(403);
    const big = post(null, { raw: JSON.stringify({ ...BODY, pad: "y".repeat(MAX_ASSISTANT_BYTES) }) });
    expect((await handleGatewayMessage(big, CONFIG, COMPANY_ID, deps)).status).toBe(413);
    const anonymous = post(BODY, { headers: { cookie: "" } });
    expect((await handleGatewayMessage(anonymous, CONFIG, COMPANY_ID, deps)).status).toBe(401);
    expect((await handleGatewayMessage(post(BODY), CONFIG, "not-a-uuid", deps)).status).toBe(403);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [json({ detail: "Too many requests" }, 429, { "Retry-After": "30" }), 429, "rate_limited"],
    [json({ detail: "Timed out" }, 504), 504, "timeout"],
    [json({ detail: "Not configured" }, 503), 503, "not_configured"],
    [json({ detail: "Knowledge unavailable" }, 503), 503, "knowledge_unavailable"],
    [new Response("<html>waking</html>", { status: 503 }), 503, "unavailable"],
    [json({ detail: "Unavailable" }, 502), 503, "unavailable"],
    [json({ detail: "Conflict" }, 409), 409, "conflict"],
    [json({ detail: "Forbidden" }, 403), 403, "refused"],
    [json({ detail: "Not found" }, 404), 404, "not_found"],
    [json({ detail: "x" }, 401), 401, "session_expired"],
    [json({ ...API_TURN, replayed: "no" }), 503, "unavailable"],
  ])("maps the API's answer to a fixed code (%#)", async (apiResponse, status, code) => {
    const response = await handleGatewayMessage(post(BODY), CONFIG, COMPANY_ID, api(apiResponse));
    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ error: code });
    if (status === 429) expect(response.headers.get("retry-after")).toBe("30");
  });

  it("says timeout when the API doesn't answer in time", async () => {
    const abort = new Error("The operation timed out.");
    abort.name = "TimeoutError";
    const response = await handleGatewayMessage(post(BODY), CONFIG, COMPANY_ID, api(abort));
    expect(response.status).toBe(504);
    expect(GATEWAY_TIMEOUT_MS).toBeLessThan(58_000);
  });
});

describe("conversation reads (GET only)", () => {
  const base = `/bff/companies/${COMPANY_ID}/assistant/conversations`;
  const CURSOR = `1792620000000000.${"a".repeat(32)}`;

  it("lists conversations field by field, passing on only the API's own cursor", async () => {
    const summary = { ...API_CONVERSATION } as Record<string, unknown>;
    delete summary.revision;
    delete summary.status;
    const deps = api(json({ items: [summary], next_before: CURSOR }));
    const response = await handleConversationList(get(`${base}?before=${CURSOR}`), CONFIG, COMPANY_ID, deps);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      items: [{ id: CONVERSATION_ID, title: CONVERSATION.title, case: CONVERSATION.case, createdAt: AT, updatedAt: AT }],
      nextBefore: CURSOR,
    });
    expect(deps.fetchMock.mock.calls[0][0]).toBe(`${API_BASE_URL}/companies/${COMPANY_ID}/assistant/conversations?before=${CURSOR}`);
    for (const query of ["?before=x", "?other=1", `?before=${CURSOR}&before=${CURSOR}`]) {
      const refused = await handleConversationList(get(`${base}${query}`), CONFIG, COMPANY_ID, api(json({})));
      expect(refused.status).toBe(422);
    }
  });

  it("finds one Case's conversation, and never mixes that with a page cursor", async () => {
    const summary = { ...API_CONVERSATION } as Record<string, unknown>;
    delete summary.revision;
    delete summary.status;
    const deps = api(json({ items: [summary], next_before: null }));
    const response = await handleConversationList(get(`${base}?caseId=${CASE_ID}`), CONFIG, COMPANY_ID, deps);
    expect(response.status).toBe(200);
    expect((await response.json()).items).toHaveLength(1);
    expect(deps.fetchMock.mock.calls[0][0]).toBe(`${API_BASE_URL}/companies/${COMPANY_ID}/assistant/conversations?case_id=${CASE_ID}`);
    for (const query of ["?caseId=not-a-case", `?caseId=${CASE_ID}&before=${CURSOR}`, `?caseId=${CASE_ID}&caseId=${CASE_ID}`]) {
      const refused = await handleConversationList(get(`${base}${query}`), CONFIG, COMPANY_ID, api(json({})));
      expect(refused.status).toBe(422);
    }
  });

  it("reads one conversation and older messages", async () => {
    const deps = api(json({ conversation: API_CONVERSATION, messages: API_MESSAGES, next_before: 5 }));
    const detail = await handleConversationDetail(get(`${base}/${CONVERSATION_ID}`), CONFIG, COMPANY_ID, CONVERSATION_ID, deps);
    expect(await detail.json()).toEqual({ conversation: CONVERSATION, messages: MESSAGES, nextBefore: 5 });
    const older = api(json({ messages: API_MESSAGES, next_before: null }));
    const page = await handleConversationMessages(
      get(`${base}/${CONVERSATION_ID}/messages?before=5`),
      CONFIG,
      COMPANY_ID,
      CONVERSATION_ID,
      older,
    );
    expect(await page.json()).toEqual({ messages: MESSAGES, nextBefore: null });
    expect(older.fetchMock.mock.calls[0][0]).toBe(
      `${API_BASE_URL}/companies/${COMPANY_ID}/assistant/conversations/${CONVERSATION_ID}/messages?before=5`,
    );
  });

  it("refuses a cross-site or session-less read, a malformed id and an internal field", async () => {
    const deps = api(json({}));
    const crossSite = get(base, { origin: "https://evil.example", "sec-fetch-site": "cross-site" });
    expect((await handleConversationList(crossSite, CONFIG, COMPANY_ID, deps)).status).toBe(403);
    expect((await handleConversationList(get(base, { cookie: "" }), CONFIG, COMPANY_ID, deps)).status).toBe(401);
    expect((await handleConversationDetail(get(`${base}/x`), CONFIG, COMPANY_ID, "x", deps)).status).toBe(404);
    expect((await handleConversationDetail(get(`${base}/${CONVERSATION_ID}?x=1`), CONFIG, COMPANY_ID, CONVERSATION_ID, deps)).status).toBe(422);
    const messages = get(`${base}/${CONVERSATION_ID}/messages?before=1`);
    expect((await handleConversationMessages(messages, CONFIG, COMPANY_ID, CONVERSATION_ID, deps)).status).toBe(422);
    expect(deps.fetchMock).not.toHaveBeenCalled();
    const leaky = api(json({ conversation: { ...API_CONVERSATION, checkpoint: {} }, messages: [], next_before: null }));
    expect((await handleConversationDetail(get(`${base}/${CONVERSATION_ID}`), CONFIG, COMPANY_ID, CONVERSATION_ID, leaky)).status).toBe(503);
  });
});

describe("askGateway (the Ask page)", () => {
  it("uses the conversation only when the API says it can answer here", () => {
    const ready = { available: true, reason: null, notice: null };
    expect(askGateway({ ok: true, data: ready })).toEqual(ready);
    expect(askGateway({ ok: true, data: { available: false, reason: "disabled", notice: null } })).toBeNull();
    expect(askGateway({ ok: true, data: { available: false, reason: "knowledge_unavailable", notice: null } })).toBeNull();
    expect(askGateway({ ok: false, failure: "forbidden" })).toBeNull();
    expect(askGateway({ ok: false, failure: "not_found" })).toBeNull();
    expect(askGateway({ ok: false, failure: "unavailable" })).toBeNull();
  });
});
