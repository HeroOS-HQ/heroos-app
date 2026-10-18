// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { API_BASE_URL, COMPANY_ID, CONFIG, WEB_ORIGIN } from "@/test/fixtures";
import { apiDecisions, apiEntry, apiRecord, apiTimeline, apiView, CASE_ID, RECORD_ID } from "@/test/workflow-fixtures";

import { handleDecisionCorrection, handleDecisionRecord, handleHistoryPage } from "./bff";
import { SESSION_COOKIE } from "./cookies";
import { decisionFieldsFromApiDetail } from "./heroos-api";
import { seal } from "./sealed";

const NOW = 1_800_000_000_000;
const ACCESS_TOKEN = "header.secret-access-token.signature";
const KEY = "a1b2c3d4-0000-4000-8000-0000000000aa";
const RECORD = {
  expectedRevision: 5,
  requestKey: KEY,
  category: "meeting_recorded",
  summary: "[SYNTHETIC] Check-in meeting held",
  explanation: "[SYNTHETIC] Notes were taken.",
  occurredOn: "2026-10-12",
  decisionMaker: "recorder",
  decisionMakerRole: null,
  evidenceStatus: "none",
  evidence: [],
};
const API_RECORD = {
  expected_revision: 5,
  request_key: KEY,
  category: "meeting_recorded",
  summary: "[SYNTHETIC] Check-in meeting held",
  explanation: "[SYNTHETIC] Notes were taken.",
  occurred_on: "2026-10-12",
  decision_maker: "recorder",
  decision_maker_role: null,
  evidence_status: "none",
  evidence: [],
};
const base = `/bff/companies/${COMPANY_ID}/cases/${CASE_ID}`;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const cookie = (exp = NOW / 1000 + 600) =>
  `${SESSION_COOKIE}=${seal({ accessToken: ACCESS_TOKEN, exp }, CONFIG.sessionSecret, "session")}`;

function post(path: string, body: unknown, { headers = {}, session = cookie() as string | null } = {}) {
  return new Request(`${WEB_ORIGIN}${path}`, {
    method: "POST",
    headers: {
      origin: WEB_ORIGIN,
      "sec-fetch-site": "same-origin",
      "content-type": "application/json",
      ...(session ? { cookie: session } : {}),
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

function get(path: string, { headers = {}, session = cookie() as string | null } = {}) {
  // A same-origin fetch() GET: no Origin header, Sec-Fetch-Site says same-origin.
  return new Request(`${WEB_ORIGIN}${path}`, {
    headers: { "sec-fetch-site": "same-origin", ...(session ? { cookie: session } : {}), ...headers },
  });
}

function api(response: Response | Error) {
  const fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  return { fetch: fetchMock as unknown as typeof fetch, fetchMock, now: () => NOW };
}

const savedView = () => apiView({ revision: 6, decisions: apiDecisions([apiRecord()], { saved: RECORD_ID }), timeline: apiTimeline() });

describe("handleDecisionRecord", () => {
  it("rebuilds the record, attaches the token server-side and returns the view", async () => {
    const deps = api(json(savedView()));
    const response = await handleDecisionRecord(post(`${base}/decisions`, RECORD), CONFIG, COMPANY_ID, CASE_ID, deps);
    expect(response.status).toBe(200);
    const body = (await response.json()) as { view: { decisions: { saved: string } } };
    expect(body.view.decisions.saved).toBe(RECORD_ID);
    const [url, init] = deps.fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/companies/${COMPANY_ID}/cases/${CASE_ID}/decisions`);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${ACCESS_TOKEN}`);
    expect(JSON.parse(String(init.body))).toEqual(API_RECORD);
  });

  it.each([
    ["a foreign Origin", { headers: { origin: "https://evil.example.com", "sec-fetch-site": "cross-site" } }, 403],
    ["a form content type", { headers: { "content-type": "application/x-www-form-urlencoded" } }, 415],
    ["no session", { session: null }, 401],
    ["an expired session", { session: cookie(NOW / 1000 - 1) }, 401],
  ])("refuses %s before calling the API", async (_, options, status) => {
    const deps = api(json(savedView()));
    expect((await handleDecisionRecord(post(`${base}/decisions`, RECORD, options), CONFIG, COMPANY_ID, CASE_ID, deps)).status).toBe(status);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("refuses unsafe categories, forged actors and unknown fields without calling the API", async () => {
    const deps = api(json(savedView()));
    for (const body of [
      { ...RECORD, category: "formal_warning_issued" },
      { ...RECORD, recordedByUserId: KEY },
      { ...RECORD, legalApproval: true },
    ]) {
      const response = await handleDecisionRecord(post(`${base}/decisions`, body), CONFIG, COMPANY_ID, CASE_ID, deps);
      expect(response.status).toBe(422);
      expect(await response.json()).toEqual({ error: "invalid", fields: [] });
    }
    expect((await handleDecisionRecord(post(`${base}/decisions`, RECORD), CONFIG, "x", CASE_ID, deps)).status).toBe(403);
    expect((await handleDecisionRecord(post(`${base}/decisions`, RECORD), CONFIG, COMPANY_ID, "x", deps)).status).toBe(404);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [409, 409, { error: "conflict" }],
    [403, 403, { error: "refused" }],
    [404, 404, { error: "not_found" }],
    [500, 503, { error: "unavailable" }],
  ])("maps an API %i to %i with a fixed code", async (status, expected, body) => {
    const deps = api(json({ detail: "[SYNTHETIC] never echoed" }, status));
    const response = await handleDecisionRecord(post(`${base}/decisions`, RECORD), CONFIG, COMPANY_ID, CASE_ID, deps);
    expect(response.status).toBe(expected);
    expect(await response.json()).toEqual(body);
  });

  it("passes on which fields the API refused, never what was in them", async () => {
    const detail = [
      { type: "value_error", loc: ["body", "evidence", 0, "description"], msg: "Value error, must describe the evidence" },
      { type: "value_error", loc: ["body", "occurred_on"], msg: "Value error, must not be in the future" },
    ];
    const deps = api(json({ detail }, 422));
    const response = await handleDecisionRecord(post(`${base}/decisions`, RECORD), CONFIG, COMPANY_ID, CASE_ID, deps);
    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({ error: "invalid", fields: ["evidence", "occurred_on"] });
    expect(decisionFieldsFromApiDetail([{ loc: ["body", "recorded_by_user_id"] }, { loc: ["query", "before"] }])).toEqual([]);
  });
});

describe("handleDecisionCorrection", () => {
  const path = `${base}/decisions/${RECORD_ID}/corrections`;
  const correction = { ...RECORD, relation: "correction", changeReason: "[SYNTHETIC] The date was wrong." };

  it("sends a correction of that record only", async () => {
    const deps = api(json(savedView()));
    const response = await handleDecisionCorrection(post(path, correction), CONFIG, COMPANY_ID, CASE_ID, RECORD_ID, deps);
    expect(response.status).toBe(200);
    const [url, init] = deps.fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/companies/${COMPANY_ID}/cases/${CASE_ID}/decisions/${RECORD_ID}/corrections`);
    expect(JSON.parse(String(init.body))).toEqual({
      ...API_RECORD,
      relation: "correction",
      change_reason: "[SYNTHETIC] The date was wrong.",
    });
  });

  it("refuses a malformed record id or a correction without a reason", async () => {
    const deps = api(json(savedView()));
    expect((await handleDecisionCorrection(post(path, correction), CONFIG, COMPANY_ID, CASE_ID, "../x", deps)).status).toBe(404);
    const noReason = await handleDecisionCorrection(post(path, { ...RECORD, relation: "correction" }), CONFIG, COMPANY_ID, CASE_ID, RECORD_ID, deps);
    expect(noReason.status).toBe(422);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });
});

describe("handleHistoryPage", () => {
  const page = apiTimeline([apiEntry("created")], { total: 26 });

  it("reads an older page for a same-origin signed-in request", async () => {
    const deps = api(json(page));
    const response = await handleHistoryPage(get(`${base}/history?before=decision%3Aabc`), CONFIG, COMPANY_ID, CASE_ID, deps);
    expect(response.status).toBe(200);
    expect(((await response.json()) as { page: { total: number } }).page.total).toBe(26);
    const [url, init] = deps.fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/companies/${COMPANY_ID}/cases/${CASE_ID}/history?before=decision%3Aabc`);
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${ACCESS_TOKEN}`);
  });

  it.each([
    ["a cross-site request", { headers: { "sec-fetch-site": "cross-site" } }, 403],
    ["a foreign Origin", { headers: { origin: "https://evil.example.com" } }, 403],
    ["no session", { session: null }, 401],
  ])("refuses %s before calling the API", async (_, options, status) => {
    const deps = api(json(page));
    expect((await handleHistoryPage(get(`${base}/history`, options), CONFIG, COMPANY_ID, CASE_ID, deps)).status).toBe(status);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("refuses malformed cursors and unknown parameters", async () => {
    const deps = api(json(page));
    for (const query of ["?before=Not%20A%20Cursor", "?before=x&limit=1000", `?before=${"x".repeat(201)}`]) {
      const response = await handleHistoryPage(get(`${base}/history${query}`), CONFIG, COMPANY_ID, CASE_ID, deps);
      expect(response.status).toBe(422);
    }
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("refuses an API answer that isn't a history page", async () => {
    const deps = api(json({ entries: "nope" }));
    const response = await handleHistoryPage(get(`${base}/history`), CONFIG, COMPANY_ID, CASE_ID, deps);
    expect(response.status).toBe(503);
  });
});
