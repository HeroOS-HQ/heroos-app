// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { API_BASE_URL, COMPANY_ID, CONFIG } from "@/test/fixtures";

import { getCompanyOverview } from "./heroos-api";

const TOKEN = "header.payload.signature";
const COMPANY = { id: COMPANY_ID, name: "[SYNTHETIC DEMO] Alpha Example Co." };
const CASES = [
  {
    id: "d3e0a000-0000-4000-8000-000000000501",
    company_id: COMPANY_ID,
    subject_id: null,
    case_type: "general",
    title: "[SYNTHETIC DEMO] Case A-1",
    created_at: "2026-10-09T18:30:00Z",
    updated_at: "2026-10-09T18:30:00Z",
  },
];

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function fetcher(routes: { company?: Response | Error; cases?: Response | Error }) {
  return vi.fn(async (input: string) => {
    const result = input.endsWith("/cases") ? (routes.cases ?? json(CASES)) : (routes.company ?? json(COMPANY));
    if (result instanceof Error) throw result;
    return result;
  });
}

describe("getCompanyOverview", () => {
  it("calls the API server-side with the bearer token and no caching", async () => {
    const fetchMock = fetcher({});
    const result = await getCompanyOverview(TOKEN, CONFIG, null, fetchMock as unknown as typeof fetch);

    expect(result).toEqual({
      ok: true,
      data: {
        companies: [COMPANY],
        selected: {
          company: COMPANY,
          cases: [
            {
              id: CASES[0].id,
              title: CASES[0].title,
              caseType: "general",
              createdAt: CASES[0].created_at,
            },
          ],
        },
      },
    });
    const urls = fetchMock.mock.calls.map(([url]) => url).sort();
    expect(urls).toEqual([`${API_BASE_URL}/companies/${COMPANY_ID}`, `${API_BASE_URL}/companies/${COMPANY_ID}/cases`]);
    for (const call of fetchMock.mock.calls) {
      const init = (call as unknown as [string, RequestInit])[1];
      expect(init.headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` });
      expect(init.cache).toBe("no-store");
      expect(init.redirect).toBe("error");
    }
  });

  it.each([
    [401, "unauthenticated"],
    [403, "forbidden"],
    [404, "not_found"],
    [500, "unavailable"],
    [502, "unavailable"],
  ])("maps HTTP %i to %s", async (status, failure) => {
    const fetchMock = fetcher({ company: json({ detail: "internal detail" }, status) });
    expect(await getCompanyOverview(TOKEN, CONFIG, null, fetchMock as unknown as typeof fetch)).toEqual({
      ok: false,
      failure,
    });
  });

  it("reports a failing cases request for the authorized company", async () => {
    const fetchMock = fetcher({ cases: json({}, 401) });
    expect(await getCompanyOverview(TOKEN, CONFIG, null, fetchMock as unknown as typeof fetch)).toEqual({
      ok: false,
      failure: "unauthenticated",
    });
  });

  it.each([
    ["network error", { company: new Error("ECONNRESET") }],
    ["unexpected company shape", { company: json({ id: 1 }) }],
    ["unexpected cases shape", { cases: json({ items: [] }) }],
    ["non-JSON body", { cases: new Response("<html>") }],
  ])("reports %s as unavailable", async (_, routes) => {
    const fetchMock = fetcher(routes);
    expect(await getCompanyOverview(TOKEN, CONFIG, null, fetchMock as unknown as typeof fetch)).toEqual({
      ok: false,
      failure: "unavailable",
    });
  });
});

// Demo-only Company discovery against a fake API that applies the Membership rule.
const COMPANY_B_ID = "d3e0b000-0000-4000-8000-000000000001";
const NAMES = {
  [COMPANY_ID]: "[SYNTHETIC DEMO] Alpha Example Co.",
  [COMPANY_B_ID]: "[SYNTHETIC DEMO] Beta Example Co.",
};
const TWO_COMPANIES = { ...CONFIG, demoCompanyIds: [COMPANY_ID, COMPANY_B_ID] };

/** A user who is a member of `memberOf` only; unknown identities get 403 everywhere. */
function apiFor(memberOf: string[], overrides: Record<string, number> = {}) {
  return vi.fn(async (input: string) => {
    const match = /\/companies\/([^/]+)(\/cases)?$/.exec(input)!;
    const [, id, cases] = match;
    const status = overrides[id] ?? (memberOf.includes(id) ? 200 : 403);
    if (status !== 200) return json({ detail: "Forbidden", secret: NAMES[id as keyof typeof NAMES] }, status);
    return cases
      ? json([{ ...CASES[0], id: `${id}-case`, title: `Case of ${id}`, company_id: id }])
      : json({ id, name: NAMES[id as keyof typeof NAMES] });
  });
}

const overview = (memberOf: string[], requested: string | null = null, overrides = {}) => {
  const api = apiFor(memberOf, overrides);
  return getCompanyOverview(TOKEN, TWO_COMPANIES, requested, api as unknown as typeof fetch).then((result) => ({
    result,
    api,
  }));
};

describe("getCompanyOverview: demo company discovery", () => {
  it("Alpha: shows Company A automatically and never fetches Company B's cases", async () => {
    const { result, api } = await overview([COMPANY_ID]);
    expect(result).toMatchObject({
      ok: true,
      data: {
        companies: [{ id: COMPANY_ID }],
        selected: { company: { id: COMPANY_ID }, cases: [{ id: `${COMPANY_ID}-case` }] },
      },
    });
    expect(JSON.stringify(result)).not.toContain("Beta");
    expect(api.mock.calls.map(([url]) => url)).not.toContain(`${API_BASE_URL}/companies/${COMPANY_B_ID}/cases`);
  });

  it("Beta: shows Company B automatically, Company A denied", async () => {
    const { result } = await overview([COMPANY_B_ID]);
    expect(result).toMatchObject({
      ok: true,
      data: { companies: [{ id: COMPANY_B_ID }], selected: { company: { id: COMPANY_B_ID } } },
    });
    expect(JSON.stringify(result)).not.toContain("Alpha");
  });

  it("Beta cannot reach Company A by asking for it", async () => {
    const { result } = await overview([COMPANY_B_ID], COMPANY_ID);
    expect(result).toMatchObject({ ok: true, data: { selected: { company: { id: COMPANY_B_ID } } } });
    expect(JSON.stringify(result)).not.toContain("Alpha");
  });

  it("unknown identity: access denied with no company data", async () => {
    const { result } = await overview([]);
    expect(result).toEqual({ ok: false, failure: "forbidden" });
  });

  it("multiple memberships: offers only authorized choices until one is chosen", async () => {
    const { result } = await overview([COMPANY_ID, COMPANY_B_ID]);
    expect(result).toMatchObject({ ok: true, data: { selected: null } });
    if (result.ok) expect(result.data.companies.map((c) => c.id)).toEqual([COMPANY_ID, COMPANY_B_ID]);

    const chosen = await overview([COMPANY_ID, COMPANY_B_ID], COMPANY_B_ID);
    expect(chosen.result).toMatchObject({ ok: true, data: { selected: { company: { id: COMPANY_B_ID } } } });
  });

  it("an unauthorized or unknown requested company is ignored", async () => {
    const { result } = await overview([COMPANY_ID, COMPANY_B_ID], "d3e0c000-0000-4000-8000-000000000001");
    expect(result).toMatchObject({ ok: true, data: { selected: null } });
  });

  it("unauthenticated: no data, and the expired token fails the whole lookup", async () => {
    const { result } = await overview([COMPANY_ID], null, { [COMPANY_ID]: 401, [COMPANY_B_ID]: 401 });
    expect(result).toEqual({ ok: false, failure: "unauthenticated" });
  });

  it("fails closed rather than showing a partial list when one lookup is unavailable", async () => {
    const { result } = await overview([COMPANY_ID], null, { [COMPANY_B_ID]: 503 });
    expect(result).toEqual({ ok: false, failure: "unavailable" });
  });

  it("does not trust a response naming a different company", async () => {
    const api = vi.fn(async () => json({ id: COMPANY_B_ID, name: "x" }));
    const result = await getCompanyOverview(TOKEN, CONFIG, null, api as unknown as typeof fetch);
    expect(result).toEqual({ ok: false, failure: "forbidden" });
  });
});
