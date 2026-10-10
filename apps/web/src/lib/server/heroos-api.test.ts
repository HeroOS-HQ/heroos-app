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
    const result = await getCompanyOverview(TOKEN, CONFIG, fetchMock as unknown as typeof fetch);

    expect(result).toEqual({
      ok: true,
      data: {
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
    expect(await getCompanyOverview(TOKEN, CONFIG, fetchMock as unknown as typeof fetch)).toEqual({
      ok: false,
      failure,
    });
  });

  it("prefers the authentication failure when both calls fail", async () => {
    const fetchMock = fetcher({ company: json({}, 500), cases: json({}, 401) });
    expect(await getCompanyOverview(TOKEN, CONFIG, fetchMock as unknown as typeof fetch)).toEqual({
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
    expect(await getCompanyOverview(TOKEN, CONFIG, fetchMock as unknown as typeof fetch)).toEqual({
      ok: false,
      failure: "unavailable",
    });
  });
});
