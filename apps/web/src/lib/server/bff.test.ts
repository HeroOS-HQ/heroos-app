// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { API_BASE_URL, COMPANY_ID, CONFIG, WEB_ORIGIN } from "@/test/fixtures";

import { handleBlueprintUpdate, handleRegistration, MAX_BODY_BYTES } from "./bff";
import { SESSION_COOKIE } from "./cookies";
import { seal } from "./sealed";

const NOW = 1_800_000_000_000;
const ACCESS_TOKEN = "header.secret-access-token.signature";
const MEMBERSHIP_ID = "d3e0a000-0000-4000-8000-0000000000a1";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function sessionCookie(exp = NOW / 1000 + 600): string {
  return `${SESSION_COOKIE}=${seal({ accessToken: ACCESS_TOKEN, exp }, CONFIG.sessionSecret, "session")}`;
}

function request(
  path: string,
  body: unknown,
  { method = "POST", headers = {}, cookie = sessionCookie() }: { method?: string; headers?: Record<string, string>; cookie?: string | null } = {},
): Request {
  return new Request(`${WEB_ORIGIN}${path}`, {
    method,
    headers: {
      origin: WEB_ORIGIN,
      "sec-fetch-site": "same-origin",
      "content-type": "application/json",
      ...(cookie ? { cookie } : {}),
      ...headers,
    },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

function api(response: Response | Error) {
  const fetchMock = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  return { fetch: fetchMock as unknown as typeof fetch, fetchMock, now: () => NOW };
}

const VALID = {
  company_name: "Gamma Trading",
  blueprint: {
    legal_name: "Gamma Trading FZ-LLC",
    employee_count: 8,
    licensing: { location: "other", authority: "Example Free Zone Authority" },
  },
};
const CREATED = { outcome: "created", company_id: COMPANY_ID, membership_id: MEMBERSHIP_ID, role: "company_admin" };

async function body(response: Response): Promise<Record<string, unknown>> {
  return (await response.json()) as Record<string, unknown>;
}

describe("handleRegistration: request checks (CSRF, type, size, session)", () => {
  it.each([
    ["a foreign Origin", { origin: "https://evil.example.com", "sec-fetch-site": "cross-site" }],
    ["Origin null from another site", { origin: "null", "sec-fetch-site": "cross-site" }],
    ["no Origin and no Sec-Fetch-Site", { origin: "", "sec-fetch-site": "" }],
  ])("refuses %s before reading the session or calling the API", async (_, headers) => {
    const deps = api(json(CREATED, 201));
    const clean = Object.fromEntries(Object.entries(headers).filter(([, value]) => value !== ""));
    const req = new Request(`${WEB_ORIGIN}/bff/registrations`, {
      method: "POST",
      headers: { "content-type": "application/json", cookie: sessionCookie(), ...clean },
      body: JSON.stringify(VALID),
    });
    const response = await handleRegistration(req, CONFIG, deps);
    expect(response.status).toBe(403);
    expect(await body(response)).toEqual({ error: "forbidden_origin" });
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it.each(["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", ""])(
    "refuses content type %j (what a cross-site form can send)",
    async (type) => {
      const deps = api(json(CREATED, 201));
      const response = await handleRegistration(
        request("/bff/registrations", VALID, { headers: { "content-type": type } }),
        CONFIG,
        deps,
      );
      expect(response.status).toBe(415);
      expect(deps.fetchMock).not.toHaveBeenCalled();
    },
  );

  it("refuses an oversized body", async () => {
    const deps = api(json(CREATED, 201));
    const big = { ...VALID, padding: "x".repeat(MAX_BODY_BYTES) };
    const response = await handleRegistration(request("/bff/registrations", big), CONFIG, deps);
    expect(response.status).toBe(413);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["no session cookie", null],
    ["an expired session", sessionCookie(NOW / 1000 - 1)],
    ["a tampered session", `${SESSION_COOKIE}=v1.AAAA.BBBB.CCCC`],
  ])("answers 401 session_expired for %s", async (_, cookie) => {
    const deps = api(json(CREATED, 201));
    const response = await handleRegistration(request("/bff/registrations", VALID, { cookie }), CONFIG, deps);
    expect(response.status).toBe(401);
    expect(await body(response)).toEqual({ error: "session_expired" });
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("answers 400 for a body that is not JSON", async () => {
    const response = await handleRegistration(request("/bff/registrations", "{not json"), CONFIG, api(json({})));
    expect(response.status).toBe(400);
  });
});

describe("handleRegistration: strict body (no mass assignment)", () => {
  it.each([
    ["company_id", { ...VALID, company_id: COMPANY_ID }],
    ["user_id", { ...VALID, user_id: COMPANY_ID }],
    ["issuer", { ...VALID, issuer: "https://evil.example.com/" }],
    ["subject", { ...VALID, subject: "someone-else" }],
    ["role", { ...VALID, role: "company_admin" }],
    ["email", { ...VALID, email: "ceo@example.com" }],
    ["administrator", { ...VALID, administrator: COMPANY_ID }],
    ["jurisdiction confirmation", { ...VALID, blueprint: { ...VALID.blueprint, employment_jurisdiction: "difc" } }],
    ["readiness", { ...VALID, blueprint: { ...VALID.blueprint, jurisdiction: { readiness: "supported_confirmed" } } }],
    ["a licensing extra", { ...VALID, blueprint: { ...VALID.blueprint, licensing: { location: "difc", confirmed: true } } }],
  ])("refuses a body with %s and never calls the API", async (_, payload) => {
    const deps = api(json(CREATED, 201));
    const response = await handleRegistration(request("/bff/registrations", payload), CONFIG, deps);
    expect(response.status).toBe(422);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["an untrimmed name", { ...VALID, company_name: " Gamma" }, "companyName"],
    ["an empty name", { ...VALID, company_name: "" }, "companyName"],
    ["a control character", { ...VALID, company_name: "Gamma\u0000" }, "companyName"],
    ["a string employee count", { ...VALID, blueprint: { ...VALID.blueprint, employee_count: "8" } }, "employeeCount"],
    ["a too-large employee count", { ...VALID, blueprint: { ...VALID.blueprint, employee_count: 10_000_001 } }, "employeeCount"],
    ["an authority with DIFC", { ...VALID, blueprint: { licensing: { location: "difc", authority: "DIFC" } } }, "licensingAuthority"],
    ["an unknown location", { ...VALID, blueprint: { licensing: { location: "adgm" } } }, "licensingLocation"],
    ["no licensing answer", { ...VALID, blueprint: { legal_name: "x" } }, "licensingLocation"],
  ])("refuses %s with the field name only", async (_, payload, field) => {
    const deps = api(json(CREATED, 201));
    const response = await handleRegistration(request("/bff/registrations", payload), CONFIG, deps);
    expect(response.status).toBe(422);
    expect(await body(response)).toEqual({ error: "invalid", fields: [field] });
  });

  it("sends the API a body rebuilt from validated values, with the token on the server side only", async () => {
    const deps = api(json(CREATED, 201));
    const response = await handleRegistration(request("/bff/registrations", VALID), CONFIG, deps);

    expect(response.status).toBe(201);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const answer = await body(response);
    expect(answer).toEqual({ outcome: "created", companyId: COMPANY_ID });
    expect(JSON.stringify(answer)).not.toContain(ACCESS_TOKEN);

    const [url, init] = deps.fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/company-registrations`);
    expect(init.headers).toMatchObject({ Authorization: `Bearer ${ACCESS_TOKEN}` });
    expect(JSON.parse(String(init.body))).toEqual(VALID);
  });

  it("drops a blank-equivalent authority rather than sending it", async () => {
    const deps = api(json(CREATED, 201));
    const payload = { company_name: "Gamma", blueprint: { licensing: { location: "other", authority: null } } };
    await handleRegistration(request("/bff/registrations", payload), CONFIG, deps);
    const [, init] = deps.fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ company_name: "Gamma", blueprint: { licensing: { location: "other" } } });
  });
});

describe("handleRegistration: API outcomes", () => {
  it("passes an existing registration on as 200 existing", async () => {
    const response = await handleRegistration(
      request("/bff/registrations", VALID),
      CONFIG,
      api(json({ ...CREATED, outcome: "existing" })),
    );
    expect(response.status).toBe(200);
    expect(await body(response)).toEqual({ outcome: "existing", companyId: COMPANY_ID });
  });

  it.each([
    [401, 401, { error: "session_expired" }],
    [403, 403, { error: "refused" }],
    [404, 404, { error: "registration_unavailable" }],
    [500, 503, { error: "unavailable" }],
    [502, 503, { error: "unavailable" }],
  ])("maps API %i to %i with a fixed code and no API text", async (status, expected, answer) => {
    const response = await handleRegistration(
      request("/bff/registrations", VALID),
      CONFIG,
      api(json({ detail: "Traceback: internal secret" }, status)),
    );
    expect(response.status).toBe(expected);
    const text = await response.text();
    expect(JSON.parse(text)).toEqual(answer);
    expect(text).not.toContain("secret");
  });

  it("passes on the field names of an API 422, never its messages", async () => {
    const detail = [{ type: "string_too_long", loc: ["body", "blueprint", "industry"], msg: "too long: secret" }];
    const response = await handleRegistration(request("/bff/registrations", VALID), CONFIG, api(json({ detail }, 422)));
    expect(response.status).toBe(422);
    const text = await response.text();
    expect(JSON.parse(text)).toEqual({ error: "invalid", fields: ["industry"] });
    expect(text).not.toContain("secret");
  });

  it("a network failure is 503 unavailable (outcome unknown), never success", async () => {
    const response = await handleRegistration(request("/bff/registrations", VALID), CONFIG, api(new Error("timeout")));
    expect(response.status).toBe(503);
  });
});

const BLUEPRINT = {
  company_id: COMPANY_ID,
  legal_name: "Gamma Trading FZ-LLC",
  industry: "Retail",
  employee_count: 8,
  licensing: { location: "difc", authority: null },
  jurisdiction: {
    readiness: "unconfirmed",
    reason: "awaiting_confirmation",
    employment_jurisdiction: null,
    confirmed_at: null,
    guidance_allowed: false,
  },
  updated_at: "2026-10-14T08:00:00Z",
};
const BLUEPRINT_PATH = `/bff/companies/${COMPANY_ID}/blueprint`;

describe("handleBlueprintUpdate", () => {
  it("PATCHes only the validated changes for the URL's Company and returns the saved Blueprint", async () => {
    const deps = api(json(BLUEPRINT));
    const response = await handleBlueprintUpdate(
      request(BLUEPRINT_PATH, { industry: "Retail", licensing: { location: "difc" } }, { method: "PATCH" }),
      CONFIG,
      COMPANY_ID,
      deps,
    );
    expect(response.status).toBe(200);
    expect(await body(response)).toMatchObject({ blueprint: { companyId: COMPANY_ID, industry: "Retail" } });
    const [url, init] = deps.fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/companies/${COMPANY_ID}/blueprint`);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ industry: "Retail", licensing: { location: "difc" } });
  });

  it("forwards the company context and a primary contact, and maps the API's refusal of the contact to its field", async () => {
    const contact = "d3e0a000-0000-4000-8000-00000000a001";
    const patch = {
      website_url: "https://gamma.example",
      company_summary: "Two shops.\n\nEight staff.",
      hr_support: "internal",
      primary_contact_membership_id: contact,
    };
    const deps = api(json(BLUEPRINT));
    expect((await handleBlueprintUpdate(request(BLUEPRINT_PATH, patch, { method: "PATCH" }), CONFIG, COMPANY_ID, deps)).status).toBe(200);
    const [, init] = deps.fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual(patch);

    const refused = await handleBlueprintUpdate(
      request(BLUEPRINT_PATH, { primary_contact_membership_id: contact }, { method: "PATCH" }),
      CONFIG,
      COMPANY_ID,
      api(json({ detail: [{ type: "value_error", loc: ["body", "primary_contact_membership_id"], msg: "invalid" }] }, 422)),
    );
    expect(refused.status).toBe(422);
    expect(await body(refused)).toEqual({ error: "invalid", fields: ["primaryContact"] });
  });

  it("allows clearing an optional field with null", async () => {
    const deps = api(json(BLUEPRINT));
    await handleBlueprintUpdate(request(BLUEPRINT_PATH, { legal_name: null }, { method: "PATCH" }), CONFIG, COMPANY_ID, deps);
    const [, init] = deps.fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ legal_name: null });
  });

  it.each(["not-a-uuid", "../../me/companies", COMPANY_ID.toUpperCase()])(
    "never calls the API for the malformed company id %s",
    async (id) => {
      const deps = api(json(BLUEPRINT));
      const response = await handleBlueprintUpdate(request(BLUEPRINT_PATH, { industry: "x" }, { method: "PATCH" }), CONFIG, id, deps);
      expect(response.status).toBe(403);
      expect(deps.fetchMock).not.toHaveBeenCalled();
    },
  );

  it.each([
    ["an empty change", {}],
    ["a role", { role: "company_admin" }],
    ["a company id", { company_id: COMPANY_ID }],
    ["a confirmation", { employment_jurisdiction: "difc" }],
    ["the legacy label", { primary_jurisdiction: "DIFC" }],
    ["the company name", { company_name: "Renamed" }],
    ["an unsafe website", { website_url: "javascript:alert(1)" }],
    ["people", { people: [] }],
    ["policy documents", { policy_documents: ["handbook.pdf"] }],
  ])("refuses %s", async (_, payload) => {
    const deps = api(json(BLUEPRINT));
    const response = await handleBlueprintUpdate(request(BLUEPRINT_PATH, payload, { method: "PATCH" }), CONFIG, COMPANY_ID, deps);
    expect(response.status).toBe(422);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("a member (or another Company) gets the API's 403 as refused", async () => {
    const response = await handleBlueprintUpdate(
      request(BLUEPRINT_PATH, { industry: "x" }, { method: "PATCH" }),
      CONFIG,
      COMPANY_ID,
      api(json({ detail: "Forbidden" }, 403)),
    );
    expect(response.status).toBe(403);
    expect(await body(response)).toEqual({ error: "refused" });
  });

  it("refuses a cross-site PATCH", async () => {
    const deps = api(json(BLUEPRINT));
    const response = await handleBlueprintUpdate(
      request(BLUEPRINT_PATH, { industry: "x" }, { method: "PATCH", headers: { origin: "https://evil.example.com", "sec-fetch-site": "cross-site" } }),
      CONFIG,
      COMPANY_ID,
      deps,
    );
    expect(response.status).toBe(403);
    expect(deps.fetchMock).not.toHaveBeenCalled();
  });

  it("does not accept a Blueprint for another Company from the API", async () => {
    const response = await handleBlueprintUpdate(
      request(BLUEPRINT_PATH, { industry: "x" }, { method: "PATCH" }),
      CONFIG,
      COMPANY_ID,
      api(json({ ...BLUEPRINT, company_id: "d3e0b000-0000-4000-8000-000000000001" })),
    );
    expect(response.status).toBe(503);
  });
});
