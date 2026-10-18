// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { apiDocuments, apiForm, apiPreview, HOSTILE, NAME, TEMPLATE_KEY } from "@/test/document-fixtures";
import { API_BASE_URL, COMPANY_ID, CONFIG, WEB_ORIGIN } from "@/test/fixtures";
import { CASE_ID } from "@/test/workflow-fixtures";

import { handleDocumentForm, handleDocumentPreview, handleDocumentsList, MAX_PREVIEW_BYTES } from "./bff";
import { SESSION_COOKIE } from "./cookies";
import { documentFieldsFromApiDetail } from "./heroos-api";
import { seal } from "./sealed";

const NOW = 1_800_000_000_000;
const ACCESS_TOKEN = "header.secret-access-token.signature";
const base = `/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/documents`;
const BODY = {
  templateVersion: 1,
  values: { recipient_name: NAME, discussion_points: ["[SYNTHETIC] Arrival times"] },
  choices: { meeting_format: ["online"] },
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const cookie = (exp = NOW / 1000 + 600) =>
  `${SESSION_COOKIE}=${seal({ accessToken: ACCESS_TOKEN, exp }, CONFIG.sessionSecret, "session")}`;

function post(path: string, body: unknown, { headers = {}, session = cookie() as string | null, raw = null as string | null } = {}) {
  return new Request(`${WEB_ORIGIN}${path}`, {
    method: "POST",
    headers: {
      origin: WEB_ORIGIN,
      "sec-fetch-site": "same-origin",
      "content-type": "application/json",
      ...(session ? { cookie: session } : {}),
      ...headers,
    },
    body: raw ?? JSON.stringify(body),
  });
}

function get(path: string, { headers = {}, session = cookie() as string | null } = {}) {
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

describe("handleDocumentsList / handleDocumentForm (reads)", () => {
  it("reads the list and a form with the token attached server-side, never cached", async () => {
    const deps = api(json(apiDocuments()));
    const response = await handleDocumentsList(get(base), CONFIG, COMPANY_ID, CASE_ID, deps);
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(((await response.json()) as { documents: { templates: unknown[] } }).documents.templates).toHaveLength(1);
    const [url, init] = deps.fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/companies/${COMPANY_ID}/cases/${CASE_ID}/documents`);
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${ACCESS_TOKEN}`);
    expect(init.method).toBe("GET");

    const formDeps = api(json(apiForm()));
    const opened = await handleDocumentForm(get(`${base}/${TEMPLATE_KEY}`), CONFIG, COMPANY_ID, CASE_ID, TEMPLATE_KEY, formDeps);
    expect(opened.status).toBe(200);
    expect(((await opened.json()) as { form: { template: { key: string } } }).form.template.key).toBe(TEMPLATE_KEY);
    expect((formDeps.fetchMock.mock.calls[0] as [string])[0]).toBe(
      `${API_BASE_URL}/companies/${COMPANY_ID}/cases/${CASE_ID}/documents/${TEMPLATE_KEY}`,
    );
  });

  it.each([
    ["a cross-site request", { "sec-fetch-site": "cross-site" }, 403, "forbidden_origin"],
    ["a foreign origin", { origin: "https://evil.example", "sec-fetch-site": "cross-site" }, 403, "forbidden_origin"],
  ])("refuses %s", async (_, headers, status, code) => {
    const deps = api(json(apiDocuments()));
    const response = await handleDocumentsList(get(base, { headers }), CONFIG, COMPANY_ID, CASE_ID, deps);
    expect([response.status, await response.json()]).toEqual([status, { error: code }]);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("needs a session, takes no query and checks ids before calling the API", async () => {
    const deps = api(json(apiDocuments()));
    expect((await handleDocumentsList(get(base, { session: null }), CONFIG, COMPANY_ID, CASE_ID, deps)).status).toBe(401);
    expect((await handleDocumentsList(get(`${base}?name=${encodeURIComponent(NAME)}`), CONFIG, COMPANY_ID, CASE_ID, deps)).status).toBe(422);
    expect((await handleDocumentsList(get(base), CONFIG, "not-a-company", CASE_ID, deps)).status).toBe(403);
    expect((await handleDocumentsList(get(base), CONFIG, COMPANY_ID, "not-a-case", deps)).status).toBe(404);
    for (const key of ["../workflow", "Synthetic.Key", "a".repeat(40)]) {
      const response = await handleDocumentForm(get(`${base}/x`), CONFIG, COMPANY_ID, CASE_ID, key, deps);
      expect(response.status, key).toBe(404);
    }
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("maps the API's refusals to fixed codes, never its text", async () => {
    for (const [status, code] of [
      [404, "not_found"],
      [409, "conflict"],
      [403, "refused"],
      [500, "unavailable"],
    ] as const) {
      const deps = api(json({ detail: "internal detail" }, status));
      const response = await handleDocumentForm(get(`${base}/${TEMPLATE_KEY}`), CONFIG, COMPANY_ID, CASE_ID, TEMPLATE_KEY, deps);
      const text = await response.text();
      expect(JSON.parse(text)).toEqual({ error: code });
      expect(text).not.toContain("internal detail");
    }
  });

  it("refuses a malformed API answer instead of passing it on", async () => {
    const deps = api(json({ ...apiDocuments(), templates: [{ key: "x" }] }));
    expect((await handleDocumentsList(get(base), CONFIG, COMPANY_ID, CASE_ID, deps)).status).toBe(503);
  });
});

describe("handleDocumentPreview (POST, nothing stored)", () => {
  const path = `${base}/${TEMPLATE_KEY}/preview`;

  it("rebuilds the request and returns the preview as structured text", async () => {
    const deps = api(json(apiPreview(HOSTILE)));
    const response = await handleDocumentPreview(post(path, BODY), CONFIG, COMPANY_ID, CASE_ID, TEMPLATE_KEY, deps);
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const body = (await response.json()) as { preview: { blocks: { segments: { text: string | null }[] }[] } };
    expect(body.preview.blocks[1].segments.slice(1).map((segment) => segment.text)).toEqual(HOSTILE);
    const [url, init] = deps.fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/companies/${COMPANY_ID}/cases/${CASE_ID}/documents/${TEMPLATE_KEY}/preview`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      template_version: 1,
      values: BODY.values,
      choices: BODY.choices,
    });
  });

  it.each([
    ["a foreign origin", { origin: "https://evil.example", "sec-fetch-site": "cross-site" }, 403, "forbidden_origin"],
    ["a form post", { "content-type": "application/x-www-form-urlencoded" }, 415, "unsupported_media_type"],
    ["a declared oversized body", { "content-length": String(MAX_PREVIEW_BYTES + 1) }, 413, "payload_too_large"],
  ])("refuses %s before calling the API", async (_, headers, status, code) => {
    const deps = api(json(apiPreview()));
    const response = await handleDocumentPreview(post(path, BODY, { headers }), CONFIG, COMPANY_ID, CASE_ID, TEMPLATE_KEY, deps);
    expect([response.status, await response.json()]).toEqual([status, { error: code }]);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("allows a whole letter's details (up to 32 KiB) but no more", async () => {
    const summary = "x".repeat(4000);
    const large = { ...BODY, values: Object.fromEntries(Array.from({ length: 6 }, (_, i) => [`summary_${i}`, summary])) };
    const deps = api(json(apiPreview()));
    const accepted = await handleDocumentPreview(post(path, large), CONFIG, COMPANY_ID, CASE_ID, TEMPLATE_KEY, deps);
    expect(accepted.status).toBe(200);
    const raw = JSON.stringify({ ...BODY, values: { a: "x".repeat(MAX_PREVIEW_BYTES) } });
    const refused = await handleDocumentPreview(post(path, null, { raw }), CONFIG, COMPANY_ID, CASE_ID, TEMPLATE_KEY, deps);
    expect(refused.status).toBe(413);
    expect(deps.fetchMock).toHaveBeenCalledTimes(1);
  });

  it("refuses unknown keys and malformed values, and needs a session", async () => {
    const deps = api(json(apiPreview()));
    for (const body of [{ ...BODY, extra: 1 }, { ...BODY, values: { "<b>": "x" } }, { ...BODY, templateVersion: "1" }]) {
      const response = await handleDocumentPreview(post(path, body), CONFIG, COMPANY_ID, CASE_ID, TEMPLATE_KEY, deps);
      expect([response.status, await response.json()]).toEqual([422, { error: "invalid", fields: [] }]);
    }
    const signedOut = await handleDocumentPreview(post(path, BODY, { session: null }), CONFIG, COMPANY_ID, CASE_ID, TEMPLATE_KEY, deps);
    expect(signedOut.status).toBe(401);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("passes on the names of refused fields, never their values", async () => {
    const detail = [
      { type: "value_error", loc: ["body", "values", "recipient_name"], msg: "must not contain control characters" },
      { type: "value_error", loc: ["body", "choices", "meeting_format"], msg: "must name exactly one option" },
      { type: "value_error", loc: ["body", "values"], msg: "has a field this template doesn't use" },
      { type: "value_error", loc: ["body", "values", "<script>"], msg: "x", input: NAME },
    ];
    expect(documentFieldsFromApiDetail(detail)).toEqual(["recipient_name", "meeting_format"]);
    const deps = api(json({ detail }, 422));
    const response = await handleDocumentPreview(post(path, BODY), CONFIG, COMPANY_ID, CASE_ID, TEMPLATE_KEY, deps);
    const text = await response.text();
    expect(JSON.parse(text)).toEqual({ error: "invalid", fields: ["recipient_name", "meeting_format"] });
    expect(text).not.toContain(NAME);
  });

  it("reports a template that can't be previewed now as a conflict", async () => {
    const deps = api(json({ detail: "Conflict" }, 409));
    const response = await handleDocumentPreview(post(path, BODY), CONFIG, COMPANY_ID, CASE_ID, TEMPLATE_KEY, deps);
    expect([response.status, await response.json()]).toEqual([409, { error: "conflict" }]);
  });

  it("refuses a preview for another template than the one asked for", async () => {
    const other = apiPreview(undefined, { template: { key: "synthetic.other", code: "TEST-09", title: "Other", kind: "letter", version: 1 } });
    const deps = api(json(other));
    const response = await handleDocumentPreview(post(path, BODY), CONFIG, COMPANY_ID, CASE_ID, TEMPLATE_KEY, deps);
    expect(response.status).toBe(503);
  });
});
