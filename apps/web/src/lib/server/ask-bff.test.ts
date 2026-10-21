// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { parseAskStart } from "@/lib/workflows/requests";
import { API_BASE_URL, COMPANY_ID, CONFIG, WEB_ORIGIN } from "@/test/fixtures";
import { apiCaseSummary, apiView, CASE_ID, WORKFLOW_CASES_PATH } from "@/test/workflow-fixtures";

import { handleAskStart } from "./bff";
import { SESSION_COOKIE } from "./cookies";
import { seal } from "./sealed";

/**
 * Ask HeroOS's seam (`POST /bff/companies/{id}/ask`, M2-NEW-02): the founder's
 * words open a case through the existing workflow API, exactly as written,
 * with one key per write. No AI is involved.
 */

const NOW = 1_800_000_000_000;
const ACCESS_TOKEN = "header.secret-access-token.signature";
const REQUEST_KEY = "a1b2c3d4-0000-4000-8000-0000000000aa";
const SUBMISSION_KEY = "a1b2c3d4-0000-4000-8000-0000000000bb";
const TEXT = "[SYNTHETIC] One of my team hasn't come in for two days.\nPhone calls go unanswered.";
const ASK = { text: TEXT, title: "New case · 21 Oct, 09:12", requestKey: REQUEST_KEY, submissionKey: SUBMISSION_KEY };
const path = `/bff/companies/${COMPANY_ID}/ask`;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const cookie = (exp = NOW / 1000 + 600) =>
  `${SESSION_COOKIE}=${seal({ accessToken: ACCESS_TOKEN, exp }, CONFIG.sessionSecret, "session")}`;

function request(body: unknown, { headers = {}, session = cookie() as string | null } = {}) {
  return new Request(`${WEB_ORIGIN}${path}`, {
    method: "POST",
    headers: {
      origin: WEB_ORIGIN,
      "sec-fetch-site": "same-origin",
      "content-type": "application/json",
      ...(session ? { cookie: session } : {}),
      ...headers,
    },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

/** The API's answers, in call order. */
function api(...responses: (Response | Error)[]) {
  const queue = [...responses];
  const fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(async () => {
    const next = queue.shift() ?? new Error("no response queued");
    if (next instanceof Error) throw next;
    return next;
  });
  return { fetch: fetchMock as unknown as typeof fetch, fetchMock, now: () => NOW };
}

const ask = (body: unknown, deps: ReturnType<typeof api>, options = {}, companyId = COMPANY_ID) =>
  handleAskStart(request(body, options), CONFIG, companyId, deps);

const call = (deps: ReturnType<typeof api>, index: number) => {
  const [url, init] = deps.fetchMock.mock.calls[index] as [string, RequestInit];
  return { url, method: init.method ?? "GET", auth: (init.headers as Record<string, string>).Authorization, body: init.body ? JSON.parse(String(init.body)) : null };
};

describe("handleAskStart", () => {
  it("opens a Disciplinary case and saves the founder's words, exactly as written, as its first answer", async () => {
    const deps = api(json(apiCaseSummary(), 201), json(apiView({ revision: 3 })), json(apiView({ revision: 4 })));
    const response = await ask(ASK, deps);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ caseId: CASE_ID, narrativeSaved: true });
    const [create, read, save] = [call(deps, 0), call(deps, 1), call(deps, 2)];
    expect(create).toMatchObject({ url: `${API_BASE_URL}${WORKFLOW_CASES_PATH}`, method: "POST", auth: `Bearer ${ACCESS_TOKEN}` });
    expect(create.body).toEqual({ title: ASK.title, request_key: REQUEST_KEY });
    expect(read).toMatchObject({ url: `${API_BASE_URL}/companies/${COMPANY_ID}/cases/${CASE_ID}/workflow`, method: "GET" });
    expect(save).toMatchObject({ url: `${API_BASE_URL}/companies/${COMPANY_ID}/cases/${CASE_ID}/workflow/steps/initial_facts/answers`, method: "PUT" });
    expect(save.body).toEqual({ expected_revision: 3, submission_key: SUBMISSION_KEY, answers: { "incident.narrative": TEXT } });
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it.each([
    ["a foreign Origin", { headers: { origin: "https://evil.example.com", "sec-fetch-site": "cross-site" } }, 403],
    ["a form content type", { headers: { "content-type": "application/x-www-form-urlencoded" } }, 415],
    ["no session", { session: null }, 401],
    ["an expired session", { session: cookie(NOW / 1000 - 1) }, 401],
  ])("refuses %s before calling the API", async (_, options, status) => {
    const deps = api(json(apiCaseSummary(), 201));
    expect((await ask(ASK, deps, options)).status).toBe(status);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a Company id that isn't one before calling the API", async () => {
    const deps = api(json(apiCaseSummary(), 201));
    expect((await ask(ASK, deps, {}, "not-a-company")).status).toBe(403);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["no text", { ...ASK, text: "" }],
    ["whitespace around the text", { ...ASK, text: ` ${TEXT}` }],
    ["text over 4,000 characters", { ...ASK, text: "a".repeat(4001) }],
    ["a control character", { ...ASK, text: "one\u0007two" }],
    ["no title", { ...ASK, title: "" }],
    ["a request key that isn't one", { ...ASK, requestKey: "1" }],
    ["one key for both writes", { ...ASK, submissionKey: REQUEST_KEY }],
    ["an unknown field", { ...ASK, workflow: "probation" }],
  ])("refuses %s (422) before calling the API", async (_, body) => {
    const deps = api(json(apiCaseSummary(), 201));
    const response = await ask(body, deps);
    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({ error: "invalid", fields: [] });
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [403, "refused"],
    [409, "conflict"],
    [503, "unavailable"],
  ])("passes on a case the API wouldn't open (%i) as a fixed code, never its text", async (status, code) => {
    const deps = api(json({ detail: "internal detail" }, status));
    const response = await ask(ASK, deps);
    expect(await response.json()).toEqual({ error: code });
    expect(deps.fetchMock).toHaveBeenCalledTimes(1);
  });

  it("says when the case opened but the words couldn't be saved, without failing the case", async () => {
    const lostSave = api(json(apiCaseSummary(), 201), json(apiView()), json({ detail: "x" }, 503));
    expect(await (await ask(ASK, lostSave)).json()).toEqual({ caseId: CASE_ID, narrativeSaved: false });
    const lostRead = api(json(apiCaseSummary(), 201), json({ detail: "x" }, 503));
    expect(await (await ask(ASK, lostRead)).json()).toEqual({ caseId: CASE_ID, narrativeSaved: false });
    expect(lostRead.fetchMock).toHaveBeenCalledTimes(2);
  });

  it("never saves into a step the case can't answer now (a changed definition)", async () => {
    const view = apiView();
    const steps = (view.steps as Record<string, unknown>[]).map((step) =>
      step.key === "initial_facts" ? { ...step, available: false, unavailable_reason: "Not now." } : step,
    );
    const deps = api(json(apiCaseSummary(), 201), json({ ...view, steps }));
    expect(await (await ask(ASK, deps)).json()).toEqual({ caseId: CASE_ID, narrativeSaved: false });
    expect(deps.fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("parseAskStart", () => {
  it("keeps line breaks and tabs, as a free-text answer may", () => {
    const text = "line one\n\tline two";
    expect(parseAskStart({ ...ASK, text })).toEqual({ ok: true, value: { ...ASK, text } });
  });
});
