import { describe, expect, it, vi } from "vitest";

import { interpretRegistrationResponse, readyPath, submitRegistration } from "./registration-client";

const COMPANY_ID = "d3e0a000-0000-4000-8000-000000000001";
const PAYLOAD = { company_name: "Gamma", blueprint: { licensing: { location: "not_sure" as const } } };

describe("interpretRegistrationResponse", () => {
  it("accepts 201 created and 200 existing only with a matching, well-formed body", () => {
    expect(interpretRegistrationResponse(201, { outcome: "created", companyId: COMPANY_ID })).toEqual({
      kind: "success",
      outcome: "created",
      companyId: COMPANY_ID,
    });
    expect(interpretRegistrationResponse(200, { outcome: "existing", companyId: COMPANY_ID })).toEqual({
      kind: "success",
      outcome: "existing",
      companyId: COMPANY_ID,
    });
  });

  it.each([
    ["a 200 claiming created", 200, { outcome: "created", companyId: COMPANY_ID }],
    ["a 201 claiming existing", 201, { outcome: "existing", companyId: COMPANY_ID }],
    ["a malformed id", 201, { outcome: "created", companyId: "../../evil" }],
    ["no body", 201, null],
  ])("treats %s as uncertain, never as success", (_, status, body) => {
    expect(interpretRegistrationResponse(status, body)).toMatchObject({ kind: "failure", reason: "uncertain" });
  });

  it.each([
    [401, { error: "session_expired" }, "session_expired"],
    [403, { error: "refused" }, "refused"],
    [403, { error: "forbidden_origin" }, "generic"],
    [404, { error: "registration_unavailable" }, "disabled"],
    [503, { error: "unavailable" }, "uncertain"],
    [500, null, "uncertain"],
    [400, { error: "invalid_request" }, "generic"],
    [415, null, "generic"],
  ])("maps %i %j to %s", (status, body, reason) => {
    expect(interpretRegistrationResponse(status, body)).toMatchObject({ kind: "failure", reason });
  });

  it("keeps only known field names from a 422", () => {
    expect(
      interpretRegistrationResponse(422, { error: "invalid", fields: ["companyName", "role", "<script>"] }),
    ).toEqual({ kind: "failure", reason: "invalid", fields: ["companyName"] });
  });
});

describe("submitRegistration", () => {
  it("posts JSON to this app's BFF only, never with a token", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ outcome: "created", companyId: COMPANY_ID }), { status: 201 }));
    const result = await submitRegistration(PAYLOAD, fetchMock as unknown as typeof fetch);

    expect(result).toMatchObject({ kind: "success" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/bff/registrations");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(init.headers).toEqual({ "Content-Type": "application/json", Accept: "application/json" });
    expect(JSON.parse(String(init.body))).toEqual(PAYLOAD);
  });

  it("a thrown fetch (offline, timeout) is uncertain", async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    expect(await submitRegistration(PAYLOAD, fetchMock as unknown as typeof fetch)).toMatchObject({
      kind: "failure",
      reason: "uncertain",
    });
  });

  it("builds the ready path from the API's id and outcome only", () => {
    expect(readyPath("existing", COMPANY_ID)).toBe(`/workspaces/${COMPANY_ID}/ready?outcome=existing`);
  });
});
