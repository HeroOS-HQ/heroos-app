// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { maxDuration } from "@/app/bff/registrations/route";
import { REGISTRATION_TIMEOUT_MS } from "@/lib/onboarding/registration-client";
import { API_BASE_URL, COMPANY_ID, CONFIG } from "@/test/fixtures";

import {
  discoverWorkspaces,
  getWorkspaceDetails,
  parseBlueprint,
  REGISTRATION_WRITE_TIMEOUT_MS,
  registerCompany,
  updateBlueprint,
} from "./heroos-api";

const TOKEN = "header.payload.signature";
const COMPANY_B_ID = "d3e0b000-0000-4000-8000-000000000001";
const MEMBERSHIP_ID = "d3e0a000-0000-4000-8000-0000000000a1";
const NAMES: Record<string, string> = {
  [COMPANY_ID]: "[SYNTHETIC DEMO] Alpha Example Co.",
  [COMPANY_B_ID]: "[SYNTHETIC DEMO] Beta Example Co.",
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

type Route = Response | Error | (() => Response);
/** A fake API: exact path → response; anything else 404. */
function api(routes: Record<string, Route>) {
  return vi.fn(async (input: string, init?: RequestInit) => {
    void init;
    const path = input.slice(API_BASE_URL.length);
    const route = routes[path];
    if (route === undefined) return json({ detail: "Not Found" }, 404);
    if (route instanceof Error) throw route;
    return typeof route === "function" ? route() : route.clone();
  });
}
const asFetch = (mock: ReturnType<typeof api>) => mock as unknown as typeof fetch;

const BLUEPRINT = {
  company_id: COMPANY_ID,
  legal_name: "Alpha Holdings LLC",
  industry: "Retail",
  employee_count: 12,
  licensing: { location: "other", authority: "Example Free Zone Authority" },
  jurisdiction: {
    readiness: "unconfirmed",
    reason: "awaiting_confirmation",
    employment_jurisdiction: null,
    confirmed_at: null,
    guidance_allowed: false,
  },
  updated_at: "2026-10-14T08:00:00Z",
};

describe("discoverWorkspaces", () => {
  it("asks GET /me/companies server-side with the bearer token and no caching", async () => {
    const fetchMock = api({
      "/me/companies": json([
        { company_id: COMPANY_ID, name: NAMES[COMPANY_ID], membership_id: MEMBERSHIP_ID, role: "company_admin" },
      ]),
    });
    const result = await discoverWorkspaces(TOKEN, CONFIG, asFetch(fetchMock));

    expect(result).toEqual({
      ok: true,
      data: [{ companyId: COMPANY_ID, name: NAMES[COMPANY_ID], membershipId: MEMBERSHIP_ID, role: "company_admin" }],
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/me/companies`);
    expect(init.headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` });
    expect(init.cache).toBe("no-store");
    expect(init.redirect).toBe("error");
    expect(init.method).toBe("GET");
  });

  it("returns an empty list as-is (a known account without active access)", async () => {
    expect(await discoverWorkspaces(TOKEN, CONFIG, asFetch(api({ "/me/companies": json([]) })))).toEqual({
      ok: true,
      data: [],
    });
  });

  it.each([
    [401, "unauthenticated"],
    [403, "forbidden"],
    [500, "unavailable"],
    [503, "unavailable"],
  ])("maps HTTP %i to %s without passing the body on", async (status, failure) => {
    const result = await discoverWorkspaces(
      TOKEN,
      CONFIG,
      asFetch(api({ "/me/companies": json({ detail: "internal detail" }, status) })),
    );
    expect(result).toEqual({ ok: false, failure });
  });

  it.each([
    ["network error", new Error("ECONNRESET")],
    ["not a list", json({ items: [] })],
    ["unknown role", json([{ company_id: COMPANY_ID, name: "x", membership_id: MEMBERSHIP_ID, role: "owner" }])],
    ["malformed id", json([{ company_id: "../cases", name: "x", membership_id: MEMBERSHIP_ID, role: "member" }])],
    ["non-JSON body", new Response("<html>")],
  ])("reports %s as unavailable", async (_, response) => {
    const result = await discoverWorkspaces(TOKEN, CONFIG, asFetch(api({ "/me/companies": response })));
    expect(result).toEqual({ ok: false, failure: "unavailable" });
  });

  it("an API without /me/companies and no demo candidates is unavailable", async () => {
    const result = await discoverWorkspaces(TOKEN, { ...CONFIG, demoCompanyIds: [] }, asFetch(api({})));
    expect(result).toEqual({ ok: false, failure: "unavailable" });
  });
});

// Legacy demo path: an API from before M1-10C (no /me/companies) with candidates.
const TWO_CANDIDATES = { ...CONFIG, demoCompanyIds: [COMPANY_ID, COMPANY_B_ID] };

/** Old API: a member of `memberOf` only; unknown identities get 403 everywhere. */
function legacyApi(memberOf: string[], overrides: Record<string, number> = {}) {
  return vi.fn(async (input: string) => {
    const match = /\/companies\/([^/]+)$/.exec(input);
    if (!match) return json({ detail: "Not Found" }, 404);
    const id = match[1];
    const status = overrides[id] ?? (memberOf.includes(id) ? 200 : 403);
    if (status !== 200) return json({ detail: "Forbidden", secret: NAMES[id] }, status);
    return json({ id, name: NAMES[id] });
  });
}

describe("discoverWorkspaces against a pre-M1-10C API (demo candidates)", () => {
  it("lists only the candidates the API authorizes, without roles", async () => {
    const result = await discoverWorkspaces(TOKEN, TWO_CANDIDATES, legacyApi([COMPANY_ID]) as unknown as typeof fetch);
    expect(result).toEqual({
      ok: true,
      data: [{ companyId: COMPANY_ID, name: NAMES[COMPANY_ID], membershipId: null, role: null }],
    });
    expect(JSON.stringify(result)).not.toContain("Beta");
  });

  it("an identity without any membership is forbidden, with no company data", async () => {
    const result = await discoverWorkspaces(TOKEN, TWO_CANDIDATES, legacyApi([]) as unknown as typeof fetch);
    expect(result).toEqual({ ok: false, failure: "forbidden" });
  });

  it("fails closed rather than showing a partial list", async () => {
    const unavailable = legacyApi([COMPANY_ID], { [COMPANY_B_ID]: 503 }) as unknown as typeof fetch;
    expect(await discoverWorkspaces(TOKEN, TWO_CANDIDATES, unavailable)).toEqual({ ok: false, failure: "unavailable" });
    const expired = legacyApi([COMPANY_ID], { [COMPANY_ID]: 401, [COMPANY_B_ID]: 401 }) as unknown as typeof fetch;
    expect(await discoverWorkspaces(TOKEN, TWO_CANDIDATES, expired)).toEqual({ ok: false, failure: "unauthenticated" });
  });

  it("does not trust a response naming a different company", async () => {
    const lying = vi.fn(async (input: string) =>
      input.endsWith("/me/companies") ? json({}, 404) : json({ id: COMPANY_B_ID, name: "x" }),
    );
    const result = await discoverWorkspaces(TOKEN, CONFIG, lying as unknown as typeof fetch);
    expect(result).toEqual({ ok: false, failure: "forbidden" });
  });
});

const COMPANY_PATH = `/companies/${COMPANY_ID}`;
const DETAIL_ROUTES = {
  [COMPANY_PATH]: json({ id: COMPANY_ID, name: NAMES[COMPANY_ID] }),
  [`${COMPANY_PATH}/membership`]: json({
    company_id: COMPANY_ID,
    membership_id: MEMBERSHIP_ID,
    role: "member",
    can_update_blueprint: false,
  }),
  [`${COMPANY_PATH}/blueprint`]: json(BLUEPRINT),
  [`${COMPANY_PATH}/cases`]: json([]),
};

describe("getWorkspaceDetails", () => {
  it("reads the company, the caller's membership and the Blueprint", async () => {
    const fetchMock = api(DETAIL_ROUTES);
    const result = await getWorkspaceDetails(TOKEN, CONFIG, COMPANY_ID, asFetch(fetchMock));

    expect(result).toMatchObject({
      ok: true,
      data: {
        company: { id: COMPANY_ID },
        membership: { role: "member", canUpdateBlueprint: false },
        blueprint: {
          legalName: "Alpha Holdings LLC",
          licensing: { location: "other", authority: "Example Free Zone Authority" },
          jurisdiction: { readiness: "unconfirmed", reason: "awaiting_confirmation", guidanceAllowed: false },
        },
        cases: [],
      },
    });
    for (const [, init] of fetchMock.mock.calls as [string, RequestInit][]) {
      expect(init.headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` });
      expect(init.cache).toBe("no-store");
    }
  });

  it.each([
    [403, "forbidden"],
    [401, "unauthenticated"],
    [503, "unavailable"],
  ])("a %i for the company is the whole answer", async (status, failure) => {
    const result = await getWorkspaceDetails(
      TOKEN,
      CONFIG,
      COMPANY_ID,
      asFetch(api({ ...DETAIL_ROUTES, [COMPANY_PATH]: json({ detail: "x" }, status) })),
    );
    expect(result).toEqual({ ok: false, failure });
  });

  it("an API without membership and Blueprint routes still opens the workspace (legacy demo)", async () => {
    const routes = { [COMPANY_PATH]: DETAIL_ROUTES[COMPANY_PATH], [`${COMPANY_PATH}/cases`]: json([]) };
    const result = await getWorkspaceDetails(TOKEN, CONFIG, COMPANY_ID, asFetch(api(routes)));
    expect(result).toMatchObject({ ok: true, data: { membership: null, blueprint: null } });
  });

  it("a malformed or foreign company id never reaches the API", async () => {
    const fetchMock = api(DETAIL_ROUTES);
    for (const id of ["../me/companies", "not-a-uuid", COMPANY_ID.toUpperCase(), ""]) {
      expect(await getWorkspaceDetails(TOKEN, CONFIG, id, asFetch(fetchMock))).toEqual({ ok: false, failure: "forbidden" });
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not trust a response naming another company", async () => {
    const routes = { ...DETAIL_ROUTES, [COMPANY_PATH]: json({ id: COMPANY_B_ID, name: "Beta" }) };
    expect(await getWorkspaceDetails(TOKEN, CONFIG, COMPANY_ID, asFetch(api(routes)))).toEqual({
      ok: false,
      failure: "forbidden",
    });
  });

  it("a membership answer never grants editing to a member", async () => {
    const routes = {
      ...DETAIL_ROUTES,
      [`${COMPANY_PATH}/membership`]: json({
        company_id: COMPANY_ID,
        membership_id: MEMBERSHIP_ID,
        role: "member",
        can_update_blueprint: true,
      }),
    };
    const result = await getWorkspaceDetails(TOKEN, CONFIG, COMPANY_ID, asFetch(api(routes)));
    expect(result.ok && result.data.membership?.canUpdateBlueprint).toBe(false);
  });
});

describe("parseBlueprint", () => {
  it("allows guidance only for a supported, confirmed jurisdiction", () => {
    const unsupported = parseBlueprint({
      ...BLUEPRINT,
      jurisdiction: { ...BLUEPRINT.jurisdiction, readiness: "unsupported", employment_jurisdiction: "adgm", guidance_allowed: true },
    });
    expect(unsupported?.jurisdiction.guidanceAllowed).toBe(false);
    const confirmed = parseBlueprint({
      ...BLUEPRINT,
      licensing: { location: "difc", authority: null },
      jurisdiction: {
        readiness: "supported_confirmed",
        reason: "confirmed",
        employment_jurisdiction: "difc",
        confirmed_at: "2026-10-14T09:00:00Z",
        guidance_allowed: true,
      },
    });
    expect(confirmed?.jurisdiction).toMatchObject({ readiness: "supported_confirmed", guidanceAllowed: true });
  });

  it.each([
    ["unknown readiness", { jurisdiction: { ...BLUEPRINT.jurisdiction, readiness: "approved" } }],
    ["unknown jurisdiction", { jurisdiction: { ...BLUEPRINT.jurisdiction, employment_jurisdiction: "mohre" } }],
    ["unknown licensing location", { licensing: { location: "adgm", authority: null } }],
    ["negative employee count", { employee_count: -1 }],
    ["missing company id", { company_id: undefined }],
  ])("refuses %s", (_, override) => {
    expect(parseBlueprint({ ...BLUEPRINT, ...override })).toBeNull();
  });

  it("reads an API without the company context as legacy, so the page edits only what it keeps", () => {
    expect(parseBlueprint(BLUEPRINT)).toMatchObject({
      version: "legacy",
      websiteUrl: null,
      companySummary: null,
      primaryContact: null,
      people: [],
      missing: null,
    });
  });

  const PERSON = {
    membership_id: MEMBERSHIP_ID,
    role: "company_admin",
    member_since: "2026-10-13T08:00:00Z",
    is_current_user: true,
    is_primary_contact: true,
  };
  const CONTEXT = {
    ...BLUEPRINT,
    company_name: "Alpha",
    website_url: "https://alpha.example",
    company_summary: "Two shops.\n\nEight staff.",
    policies_exist: "yes",
    policy_context: "Employee handbook",
    hr_support: "external",
    hr_support_notes: null,
    primary_contact: PERSON,
    people: [PERSON],
    completeness: { complete: false, missing: ["jurisdiction"] },
  };

  it("reads the company context (M2-NEW-03): people without names, the API's completeness", () => {
    expect(parseBlueprint(CONTEXT)).toMatchObject({
      version: "context",
      websiteUrl: "https://alpha.example",
      companySummary: "Two shops.\n\nEight staff.",
      policiesExist: "yes",
      policyContext: "Employee handbook",
      hrSupport: "external",
      hrSupportNotes: null,
      primaryContact: { membershipId: MEMBERSHIP_ID, role: "company_admin", isCurrentUser: true, isPrimaryContact: true },
      people: [{ membershipId: MEMBERSHIP_ID, memberSince: "2026-10-13T08:00:00Z" }],
      missing: ["jurisdiction"],
    });
  });

  it.each([
    ["an unknown policies answer", { policies_exist: "maybe" }],
    ["an unknown HR support", { hr_support: "outsourced" }],
    ["a person without a membership id", { people: [{ ...PERSON, membership_id: "x" }] }],
    ["a primary contact with an unknown role", { primary_contact: { ...PERSON, role: "owner" } }],
    ["an unknown completeness detail", { completeness: { complete: false, missing: ["website_url"] } }],
    ["no completeness", { completeness: undefined }],
    ["a summary that isn't text", { company_summary: 7 }],
  ])("refuses a context with %s", (_, override) => {
    expect(parseBlueprint({ ...CONTEXT, ...override })).toBeNull();
  });
});

const PAYLOAD = {
  company_name: "Gamma Trading",
  blueprint: { legal_name: "Gamma Trading FZ-LLC", licensing: { location: "not_sure" as const } },
};
const REGISTERED = { outcome: "created", company_id: COMPANY_ID, membership_id: MEMBERSHIP_ID, role: "company_admin" };

describe("registerCompany", () => {
  it("POSTs the validated payload as JSON with the bearer token", async () => {
    const fetchMock = api({ "/company-registrations": json(REGISTERED, 201) });
    const result = await registerCompany(TOKEN, CONFIG, PAYLOAD, asFetch(fetchMock));

    expect(result).toEqual({ ok: true, data: { outcome: "created", companyId: COMPANY_ID, membershipId: MEMBERSHIP_ID } });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE_URL}/company-registrations`);
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" });
    expect(JSON.parse(String(init.body))).toEqual(PAYLOAD);
    expect(init.cache).toBe("no-store");
  });

  it("reports an existing registration", async () => {
    const result = await registerCompany(
      TOKEN,
      CONFIG,
      PAYLOAD,
      asFetch(api({ "/company-registrations": json({ ...REGISTERED, outcome: "existing" }) })),
    );
    expect(result).toMatchObject({ ok: true, data: { outcome: "existing", companyId: COMPANY_ID } });
  });

  it("accepts an existing registration whose founder has since been demoted to member", async () => {
    const result = await registerCompany(
      TOKEN,
      CONFIG,
      PAYLOAD,
      asFetch(api({ "/company-registrations": json({ ...REGISTERED, outcome: "existing", role: "member" }) })),
    );
    expect(result).toMatchObject({ ok: true, data: { outcome: "existing", companyId: COMPANY_ID } });
  });

  it.each([
    [401, "unauthenticated"],
    [403, "forbidden"],
    [404, "not_found"],
    [500, "unavailable"],
  ])("maps HTTP %i to %s", async (status, failure) => {
    const result = await registerCompany(
      TOKEN,
      CONFIG,
      PAYLOAD,
      asFetch(api({ "/company-registrations": json({ detail: "secret internals" }, status) })),
    );
    expect(result).toEqual({ ok: false, failure });
  });

  it("keeps only the field names of a 422, never the messages", async () => {
    const detail = [
      { type: "string_too_long", loc: ["body", "company_name"], msg: "String should have at most 200 characters" },
      { type: "value_error", loc: ["body", "blueprint", "licensing", "authority"], msg: "Value error" },
      { type: "extra_forbidden", loc: ["body", "role"], msg: "Extra inputs are not permitted" },
    ];
    const result = await registerCompany(
      TOKEN,
      CONFIG,
      PAYLOAD,
      asFetch(api({ "/company-registrations": json({ detail }, 422) })),
    );
    expect(result).toEqual({ ok: false, failure: "invalid", fields: ["companyName", "licensingAuthority"] });
    expect(JSON.stringify(result)).not.toContain("String should");
  });

  it.each([
    ["no outcome", { ...REGISTERED, outcome: undefined }],
    ["not an administrator", { ...REGISTERED, role: "member" }],
    ["malformed company id", { ...REGISTERED, company_id: "x" }],
  ])("treats a success body with %s as unavailable", async (_, body) => {
    const result = await registerCompany(TOKEN, CONFIG, PAYLOAD, asFetch(api({ "/company-registrations": json(body, 201) })));
    expect(result).toEqual({ ok: false, failure: "unavailable" });
  });

  it("a network failure is unavailable (the outcome is unknown)", async () => {
    const result = await registerCompany(
      TOKEN,
      CONFIG,
      PAYLOAD,
      asFetch(api({ "/company-registrations": new Error("timeout") })),
    );
    expect(result).toEqual({ ok: false, failure: "unavailable" });
  });

  it("waits out a waking API (32 s observed), then answers before the browser and the route give up", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    try {
      await registerCompany(TOKEN, CONFIG, PAYLOAD, asFetch(api({ "/company-registrations": json(REGISTERED, 201) })));
      expect(timeout).toHaveBeenCalledWith(REGISTRATION_WRITE_TIMEOUT_MS);
    } finally {
      timeout.mockRestore();
    }
    expect(REGISTRATION_WRITE_TIMEOUT_MS).toBeGreaterThanOrEqual(32_000 + 10_000);
    expect(REGISTRATION_WRITE_TIMEOUT_MS).toBeLessThan(REGISTRATION_TIMEOUT_MS);
    expect(REGISTRATION_WRITE_TIMEOUT_MS).toBeLessThan(maxDuration * 1000);
  });
});

describe("updateBlueprint", () => {
  it("PATCHes only the given fields and returns the saved Blueprint", async () => {
    const fetchMock = api({ [`${COMPANY_PATH}/blueprint`]: json(BLUEPRINT) });
    const result = await updateBlueprint(TOKEN, CONFIG, COMPANY_ID, { industry: "Retail" }, asFetch(fetchMock));

    expect(result).toMatchObject({ ok: true, data: { industry: "Retail" } });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ industry: "Retail" });
  });

  it("refuses a malformed company id before any request", async () => {
    const fetchMock = api({});
    expect(await updateBlueprint(TOKEN, CONFIG, "x/../y", { industry: "x" }, asFetch(fetchMock))).toEqual({
      ok: false,
      failure: "forbidden",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("a member's update is forbidden by the API", async () => {
    const result = await updateBlueprint(
      TOKEN,
      CONFIG,
      COMPANY_ID,
      { industry: "x" },
      asFetch(api({ [`${COMPANY_PATH}/blueprint`]: json({ detail: "Forbidden" }, 403) })),
    );
    expect(result).toEqual({ ok: false, failure: "forbidden" });
  });
});
