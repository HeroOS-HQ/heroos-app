// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { parseWorkflowView } from "@/lib/workflows/model";
import { API_BASE_URL, COMPANY_ID, CONFIG, WEB_ORIGIN } from "@/test/fixtures";
import { apiCaseSummary, apiProgression, apiView, CASE_ID, OTHER_CASE_ID, WORKFLOW_CASES_PATH } from "@/test/workflow-fixtures";

import { assistantLoad, caseState, casesState } from "./app-state";
import { handleAnswersSave, handleCaseCreate, handlePathwaySelect, handleTransitionRequest } from "./bff";
import { SESSION_COOKIE } from "./cookies";
import { answerKeysFromApiDetail, getCaseWorkflow, listWorkflowCases, saveStepAnswers } from "./heroos-api";
import { seal } from "./sealed";

const NOW = 1_800_000_000_000;
const ACCESS_TOKEN = "header.secret-access-token.signature";
const REQUEST_KEY = "a1b2c3d4-0000-4000-8000-0000000000aa";
const SUBMISSION_KEY = "a1b2c3d4-0000-4000-8000-0000000000bb";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const cookie = (exp = NOW / 1000 + 600) =>
  `${SESSION_COOKIE}=${seal({ accessToken: ACCESS_TOKEN, exp }, CONFIG.sessionSecret, "session")}`;

function request(path: string, body: unknown, { method = "POST", headers = {}, session = cookie() as string | null } = {}) {
  return new Request(`${WEB_ORIGIN}${path}`, {
    method,
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

function api(response: Response | Error) {
  const fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  return { fetch: fetchMock as unknown as typeof fetch, fetchMock, now: () => NOW };
}

const CREATE = { title: "[SYNTHETIC] Attendance concern", requestKey: REQUEST_KEY };
const SAVE = { expectedRevision: 0, submissionKey: SUBMISSION_KEY, answers: { "incident.history": "new" } };
const createPath = `/bff/companies/${COMPANY_ID}/workflows/disciplinary/cases`;
const savePath = `/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/steps/initial_facts/answers`;

const create = (body: unknown, deps: ReturnType<typeof api>, options = {}, companyId = COMPANY_ID, workflowKey = "disciplinary") =>
  handleCaseCreate(request(createPath, body, options), CONFIG, companyId, workflowKey, deps);
const save = (body: unknown, deps: ReturnType<typeof api>, options = {}, caseId = CASE_ID, stepKey = "initial_facts") =>
  handleAnswersSave(request(savePath, body, { method: "PUT", ...options }), CONFIG, COMPANY_ID, caseId, stepKey, deps);

describe("handleCaseCreate", () => {
  it("rebuilds the body, attaches the token server-side and returns the Case", async () => {
    const deps = api(json(apiCaseSummary(), 201));
    const response = await create(CREATE, deps);

    expect(response.status).toBe(200);
    expect(((await response.json()) as { case: { id: string } }).case.id).toBe(CASE_ID);
    const [url, init] = deps.fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}${WORKFLOW_CASES_PATH}`);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${ACCESS_TOKEN}`);
    expect(JSON.parse(String(init.body))).toEqual({ title: CREATE.title, request_key: REQUEST_KEY });
  });

  it.each([
    ["a foreign Origin", { headers: { origin: "https://evil.example.com", "sec-fetch-site": "cross-site" } }, 403],
    ["a form content type", { headers: { "content-type": "application/x-www-form-urlencoded" } }, 415],
    ["no session", { session: null }, 401],
    ["an expired session", { session: cookie(NOW / 1000 - 1) }, 401],
  ])("refuses %s before calling the API", async (_, options, status) => {
    const deps = api(json(apiCaseSummary(), 201));
    expect((await create(CREATE, deps, options)).status).toBe(status);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("refuses ids and bodies the API would never accept, without calling it", async () => {
    const deps = api(json(apiCaseSummary(), 201));
    expect((await create(CREATE, deps, {}, "not-a-uuid")).status).toBe(403);
    expect((await create(CREATE, deps, {}, COMPANY_ID, "Disciplinary/../x")).status).toBe(404);
    const invalid = await create({ ...CREATE, caseType: "probation" }, deps);
    expect(invalid.status).toBe(422);
    expect(await invalid.json()).toEqual({ error: "invalid", fields: [] });
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [401, 401, "session_expired"],
    [403, 403, "refused"],
    [404, 404, "not_found"],
    [409, 409, "conflict"],
    [500, 503, "unavailable"],
  ])("maps an API %i to %i %s with a fixed body", async (apiStatus, status, code) => {
    const deps = api(json({ detail: "internal detail that must not leak" }, apiStatus));
    const response = await create(CREATE, deps);
    expect(response.status).toBe(status);
    expect(await response.text()).toBe(JSON.stringify({ error: code }));
  });

  it("treats an unreachable API or a malformed answer as unavailable", async () => {
    expect((await create(CREATE, api(new Error("network down")))).status).toBe(503);
    expect((await create(CREATE, api(json({ id: "x" }, 201)))).status).toBe(503);
  });
});

describe("handleAnswersSave", () => {
  it("rebuilds the save and returns the Case after it", async () => {
    const deps = api(json(apiView({ answers: { "incident.history": "new" }, revision: 1 })));
    const response = await save(SAVE, deps);

    expect(response.status).toBe(200);
    const body = (await response.json()) as { view: { workflow: { revision: number }; answers: Record<string, string> } };
    expect(body.view.workflow.revision).toBe(1);
    expect(body.view.answers).toEqual({ "incident.history": "new" });
    const [url, init] = deps.fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/companies/${COMPANY_ID}/cases/${CASE_ID}/workflow/steps/initial_facts/answers`);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual({
      expected_revision: 0,
      submission_key: SUBMISSION_KEY,
      answers: { "incident.history": "new" },
    });
  });

  it("names only the refused questions of a 422, never the API's messages", async () => {
    const detail = [
      { type: "value_error", loc: ["body", "answers", "incident.date"], msg: "must not be in the future" },
      { type: "value_error", loc: ["body", "expected_revision"], msg: "x" },
    ];
    const response = await save(SAVE, api(json({ detail }, 422)));
    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({ error: "invalid", fields: ["incident.date"] });
  });

  it("reports a stale save as a conflict", async () => {
    const response = await save(SAVE, api(json({ detail: "Conflict" }, 409)));
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ error: "conflict" });
  });

  it("refuses an answer for a different Case than the one requested", async () => {
    expect((await save(SAVE, api(json(apiView({ caseId: OTHER_CASE_ID }))))).status).toBe(503);
  });

  it("refuses malformed ids and bodies without calling the API", async () => {
    const deps = api(json(apiView()));
    expect((await save(SAVE, deps, {}, "x")).status).toBe(404);
    expect((await save(SAVE, deps, {}, CASE_ID, "../blueprint")).status).toBe(404);
    expect((await save({ ...SAVE, expectedRevision: -1 }, deps)).status).toBe(422);
    expect((await save({ ...SAVE, answers: { "incident.history": 3 } }, deps)).status).toBe(422);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });
});

describe("workflow API client", () => {
  it("never calls the API with an id that isn't a UUID", async () => {
    const deps = api(json([]));
    expect(await listWorkflowCases(ACCESS_TOKEN, CONFIG, "x", "disciplinary", deps.fetch)).toEqual({ ok: false, failure: "forbidden" });
    expect(await getCaseWorkflow(ACCESS_TOKEN, CONFIG, COMPANY_ID, "x", deps.fetch)).toEqual({ ok: false, failure: "not_found" });
    expect(
      await saveStepAnswers(ACCESS_TOKEN, CONFIG, COMPANY_ID, CASE_ID, "Bad Step", { expected_revision: 0, submission_key: SUBMISSION_KEY, answers: {} }, deps.fetch),
    ).toEqual({ ok: false, failure: "not_found" });
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("lists and reads, checking the Case is the one asked for", async () => {
    const listed = await listWorkflowCases(ACCESS_TOKEN, CONFIG, COMPANY_ID, "disciplinary", api(json([apiCaseSummary()])).fetch);
    expect(listed.ok && listed.data.map((c) => c.id)).toEqual([CASE_ID]);
    expect((await getCaseWorkflow(ACCESS_TOKEN, CONFIG, COMPANY_ID, CASE_ID, api(json(apiView())).fetch)).ok).toBe(true);
    expect(await getCaseWorkflow(ACCESS_TOKEN, CONFIG, COMPANY_ID, CASE_ID, api(json(apiView({ caseId: OTHER_CASE_ID }))).fetch)).toEqual({
      ok: false,
      failure: "unavailable",
    });
  });

  it("extracts question keys from 422 locations only", () => {
    expect(
      answerKeysFromApiDetail([
        { loc: ["body", "answers", "incident.narrative"] },
        { loc: ["body", "answers", "incident.narrative"] },
        { loc: ["body", "answers", "<script>"] },
        { loc: ["body", "title"] },
        "junk",
      ]),
    ).toEqual(["incident.narrative"]);
    expect(answerKeysFromApiDetail(null)).toEqual([]);
  });
});

describe("page states", () => {
  const withRole = (role: "company_admin" | "member" | null) => ({
    ok: true as const,
    data: {
      company: { id: COMPANY_ID, name: "[SYNTHETIC] Alpha" },
      membership: role === null ? null : { companyId: COMPANY_ID, membershipId: "m", role, canUpdateBlueprint: role === "company_admin" },
      blueprint: null,
      cases: [],
    },
  });
  const admin = withRole("company_admin");
  const workspaces = { ok: true as const, data: [] };

  it("separates an API without workflow routes from other failures", () => {
    expect(casesState(admin, workspaces, { ok: false, failure: "not_found" }).kind).toBe("workflow_unavailable");
    expect(casesState(admin, workspaces, { ok: false, failure: "unauthenticated" }).kind).toBe("session_expired");
    expect(casesState(admin, workspaces, { ok: false, failure: "unavailable" }).kind).toBe("api_unavailable");
    expect(casesState({ ok: false, failure: "forbidden" }, workspaces, null).kind).toBe("access_denied");
    expect(casesState(admin, workspaces, { ok: true, data: [] }).kind).toBe("cases_ready");
  });

  it("is administrator-only: a member (or an unknown role) never gets case data", () => {
    // Even if case data were handed over, a non-administrator state wins.
    expect(casesState(withRole("member"), workspaces, { ok: true, data: [] }).kind).toBe("admin_only");
    expect(casesState(withRole(null), workspaces, null).kind).toBe("admin_only");
    // Demoted since the membership was read: the API's 403 also means admin-only.
    expect(casesState(admin, workspaces, { ok: false, failure: "forbidden" }).kind).toBe("admin_only");
    const list = { ok: true as const, data: [] };
    expect(caseState(admin, workspaces, list, { ok: false, failure: "forbidden" }).kind).toBe("admin_only");
    expect(caseState(withRole("member"), workspaces, null, null).kind).toBe("admin_only");
  });

  it("shows a missing Case as not found, like another Company's", () => {
    const list = { ok: true as const, data: [] };
    expect(caseState(admin, workspaces, list, { ok: false, failure: "not_found" }).kind).toBe("case_not_found");
    expect(caseState(admin, workspaces, list, { ok: false, failure: "unavailable" }).kind).toBe("api_unavailable");
  });

  it("reads the Hannah AI demo's status with the Case, and never fails the Case page over it", () => {
    const notice = "Hannah AI Demo";
    const ready = { available: true, reason: null, notice };
    expect(assistantLoad({ ok: true, data: ready })).toEqual({ state: "ready", status: ready });
    const unset = { available: false, reason: "not_configured" as const, notice };
    expect(assistantLoad({ ok: true, data: unset })).toEqual({ state: "ready", status: unset });
    // Switched off, refused, unknown Case, an API without the demo: out of sight.
    expect(assistantLoad({ ok: true, data: { available: false, reason: "disabled", notice } })).toEqual({ state: "hidden" });
    for (const failure of ["forbidden", "not_found", "unauthenticated", "invalid"] as const) {
      expect(assistantLoad({ ok: false, failure })).toEqual({ state: "hidden" });
    }
    // A waking or failing API (or an answer this page can't read): said plainly on the page.
    expect(assistantLoad({ ok: false, failure: "unavailable" })).toEqual({ state: "unreachable" });

    const list = { ok: true as const, data: [] };
    const view = { ok: true as const, data: parseWorkflowView(apiView())! };
    const state = caseState(admin, workspaces, list, view, { state: "unreachable" });
    expect(state.kind === "case_ready" && state.assistant).toEqual({ state: "unreachable" });
    const plain = caseState(admin, workspaces, list, view);
    expect(plain.kind === "case_ready" && plain.assistant).toEqual({ state: "hidden" });
  });
});

// --- M2-03 progression -------------------------------------------------------------

const PROGRESSION_KEY = "a1b2c3d4-0000-4000-8000-0000000000dd";
const pathwayPath = `/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/progression/pathway`;
const transitionPath = `/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/progression/transitions`;
const PATHWAY = { expectedRevision: 4, requestKey: PROGRESSION_KEY, pathway: "less_serious" };
const TRANSITION = { expectedRevision: 5, requestKey: PROGRESSION_KEY, transition: "start:test_check_in" };

const choose = (body: unknown, deps: ReturnType<typeof api>, options = {}, caseId = CASE_ID) =>
  handlePathwaySelect(request(pathwayPath, body, options), CONFIG, COMPANY_ID, caseId, deps);
const move = (body: unknown, deps: ReturnType<typeof api>, options = {}, caseId = CASE_ID) =>
  handleTransitionRequest(request(transitionPath, body, options), CONFIG, COMPANY_ID, caseId, deps);

describe("handlePathwaySelect and handleTransitionRequest", () => {
  it("rebuild the body, attach the token server-side and return the view", async () => {
    const deps = api(json(apiView({ progression: apiProgression() })));
    const response = await choose(PATHWAY, deps);
    expect(response.status).toBe(200);
    const [url, init] = deps.fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/companies/${COMPANY_ID}/cases/${CASE_ID}/workflow/progression/pathway`);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${ACCESS_TOKEN}`);
    expect(JSON.parse(String(init.body))).toEqual({
      expected_revision: 4,
      request_key: PROGRESSION_KEY,
      pathway: "less_serious",
      acknowledged_warnings: [],
    });

    const moved = api(json(apiView({ progression: apiProgression() })));
    expect((await move(TRANSITION, moved)).status).toBe(200);
    const [movedUrl, movedInit] = moved.fetchMock.mock.calls[0] as [string, RequestInit];
    expect(movedUrl).toBe(`${API_BASE_URL}/companies/${COMPANY_ID}/cases/${CASE_ID}/workflow/progression/transitions`);
    expect(JSON.parse(String(movedInit.body))).toMatchObject({ transition: "start:test_check_in" });
  });

  it.each([
    ["a foreign Origin", { headers: { origin: "https://evil.example.com", "sec-fetch-site": "cross-site" } }, 403],
    ["a form content type", { headers: { "content-type": "application/x-www-form-urlencoded" } }, 415],
    ["no session", { session: null }, 401],
  ])("refuse %s before calling the API", async (_, options, status) => {
    const deps = api(json(apiView()));
    expect((await choose(PATHWAY, deps, options)).status).toBe(status);
    expect((await move(TRANSITION, deps, options)).status).toBe(status);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("refuse malformed requests and other ids without calling the API", async () => {
    const deps = api(json(apiView()));
    expect((await choose({ ...PATHWAY, pathway: "pathway:serious" }, deps)).status).toBe(422);
    expect((await move({ ...TRANSITION, transition: "pathway:serious" }, deps)).status).toBe(422);
    expect((await move({ ...TRANSITION, extra: 1 }, deps)).status).toBe(422);
    expect((await move(TRANSITION, deps, {}, "not-a-case")).status).toBe(404);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [409, 409, "conflict"],
    [403, 403, "refused"],
    [404, 404, "not_found"],
    [401, 401, "session_expired"],
    [500, 503, "unavailable"],
  ])("map an API %i to %i %s with a fixed body", async (apiStatus, status, code) => {
    const deps = api(json({ detail: "API detail that must not leak" }, apiStatus));
    const response = await move(TRANSITION, deps);
    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ error: code });
  });

  it("refuse an API answer for another case", async () => {
    const deps = api(json(apiView({ caseId: OTHER_CASE_ID, progression: apiProgression() })));
    expect((await choose(PATHWAY, deps)).status).toBe(503);
  });
});
