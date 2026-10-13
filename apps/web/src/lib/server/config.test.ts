// @vitest-environment node
import { describe, expect, it } from "vitest";

import { ENV, OIDC_AUDIENCE, OIDC_CLIENT_ID, OIDC_ENV, OIDC_ISSUER } from "@/test/fixtures";

import { callbackUrl, readAuthConfig, signedOutUrl } from "./config";

describe("readAuthConfig", () => {
  it("accepts a complete production configuration", () => {
    const result = readAuthConfig(ENV);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(callbackUrl(result.config)).toBe("https://heroos-demo.example.com/auth/callback");
    expect(signedOutUrl(result.config)).toBe("https://heroos-demo.example.com/");
    expect(result.config.sessionSecret).toHaveLength(32);
  });

  it("fails closed when nothing is configured", () => {
    const result = readAuthConfig({ NODE_ENV: "production" });
    expect(result).toEqual({
      ok: false,
      invalid: [
        "HEROOS_WEB_ORIGIN",
        "HEROOS_WEB_AUTH_PROVIDER",
        "HEROOS_API_BASE_URL",
        "HEROOS_WEB_SESSION_SECRET",
      ],
    });
  });

  it.each([undefined, "", "COGNITO", "development", "auth0"])(
    "refuses an unknown provider %s",
    (provider) => {
      expect(readAuthConfig({ ...ENV, HEROOS_WEB_AUTH_PROVIDER: provider })).toEqual({
        ok: false,
        invalid: ["HEROOS_WEB_AUTH_PROVIDER"],
      });
    },
  );

  it("reports the Cognito variables when cognito is selected but unset", () => {
    const result = readAuthConfig({ ...ENV, HEROOS_COGNITO_DOMAIN: undefined, HEROOS_COGNITO_CLIENT_ID: undefined });
    expect(result).toEqual({ ok: false, invalid: ["HEROOS_COGNITO_DOMAIN", "HEROOS_COGNITO_CLIENT_ID"] });
  });

  it.each([
    ["HEROOS_WEB_ORIGIN", "http://heroos-demo.example.com"],
    ["HEROOS_WEB_ORIGIN", "https://heroos-demo.example.com/"],
    ["HEROOS_WEB_ORIGIN", "https://*.vercel.app"],
    ["HEROOS_WEB_ORIGIN", "http://localhost:3000"],
    ["HEROOS_COGNITO_DOMAIN", "http://heroos-demo.auth.eu-west-1.amazoncognito.com"],
    ["HEROOS_COGNITO_DOMAIN", "https://heroos-demo.auth.eu-west-1.amazoncognito.com/oauth2"],
    ["HEROOS_COGNITO_CLIENT_ID", "client id with spaces"],
    ["HEROOS_API_BASE_URL", "http://heroos-api.example.com"],
    ["HEROOS_API_BASE_URL", "https://heroos-api.example.com/"],
    ["HEROOS_API_BASE_URL", "https://heroos-api.example.com?x=1"],
    ["HEROOS_DEMO_COMPANY_ID", "not-a-uuid"],
    ["HEROOS_DEMO_COMPANY_ID", "D3E0A000-0000-4000-8000-000000000001"],
    ["HEROOS_DEMO_COMPANY_IDS", "d3e0a000-0000-4000-8000-000000000001,not-a-uuid"],
    ["HEROOS_DEMO_COMPANY_IDS", "d3e0a000-0000-4000-8000-000000000001,d3e0a000-0000-4000-8000-000000000001"],
    ["HEROOS_DEMO_COMPANY_IDS", "d3e0a000-0000-4000-8000-000000000001, d3e0b000-0000-4000-8000-000000000001"],
    ["HEROOS_WEB_SESSION_SECRET", "too-short"],
    ["HEROOS_WEB_SESSION_SECRET", "0F".repeat(32)],
  ])("rejects %s=%s and names only the variable", (name, value) => {
    const result = readAuthConfig({ ...ENV, [name]: value });
    expect(result).toEqual({ ok: false, invalid: [name] });
    expect(JSON.stringify(result)).not.toContain(value);
  });

  it("reads a candidate list from HEROOS_DEMO_COMPANY_IDS, which wins over the single id", () => {
    const ids = "d3e0a000-0000-4000-8000-000000000001,d3e0b000-0000-4000-8000-000000000001";
    const result = readAuthConfig({ ...ENV, HEROOS_DEMO_COMPANY_IDS: ids });
    expect(result.ok && result.config.demoCompanyIds).toEqual(ids.split(","));
  });

  it("falls back to the single HEROOS_DEMO_COMPANY_ID", () => {
    const result = readAuthConfig(ENV);
    expect(result.ok && result.config.demoCompanyIds).toEqual([ENV.HEROOS_DEMO_COMPANY_ID]);
  });

  it("needs no demo Company at all: workspaces come from the API (M1-10D)", () => {
    const result = readAuthConfig({ ...ENV, HEROOS_DEMO_COMPANY_ID: undefined, HEROOS_DEMO_COMPANY_IDS: "" });
    expect(result.ok && result.config.demoCompanyIds).toEqual([]);
  });

  it("allows plain-http localhost only outside production", () => {
    const local = { HEROOS_WEB_ORIGIN: "http://localhost:3000", HEROOS_API_BASE_URL: "http://localhost:8000" };
    expect(readAuthConfig({ ...ENV, ...local, NODE_ENV: "development" }).ok).toBe(true);
    expect(readAuthConfig({ ...ENV, ...local, NODE_ENV: "production" }).ok).toBe(false);
    // The identity provider is always https.
    expect(
      readAuthConfig({ ...ENV, NODE_ENV: "development", HEROOS_COGNITO_DOMAIN: "http://localhost:9000" }).ok,
    ).toBe(false);
  });
});

describe("readAuthConfig (oidc)", () => {
  it("accepts a complete OIDC configuration and keeps the issuer verbatim", () => {
    const result = readAuthConfig(OIDC_ENV);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.config.provider).toEqual({
      kind: "oidc",
      issuer: OIDC_ISSUER,
      origin: "https://heroos-demo.idp.example.com",
      audience: OIDC_AUDIENCE,
    });
    expect(result.config.clientId).toBe(OIDC_CLIENT_ID);
  });

  it("ignores Cognito variables when oidc is selected", () => {
    const result = readAuthConfig({ ...OIDC_ENV, HEROOS_COGNITO_DOMAIN: "garbage" });
    expect(result.ok).toBe(true);
  });

  it("reports only the OIDC variables when oidc is selected but unset", () => {
    expect(readAuthConfig({ ...ENV, HEROOS_WEB_AUTH_PROVIDER: "oidc" })).toEqual({
      ok: false,
      invalid: ["HEROOS_OIDC_ISSUER", "HEROOS_OIDC_CLIENT_ID", "HEROOS_OIDC_AUDIENCE"],
    });
  });

  it.each([
    ["HEROOS_OIDC_ISSUER", "http://heroos-demo.idp.example.com/"],
    ["HEROOS_OIDC_ISSUER", "https://*.idp.example.com/"],
    ["HEROOS_OIDC_ISSUER", "https://heroos-demo.idp.example.com/?tenant=x"],
    ["HEROOS_OIDC_ISSUER", "https://user:pw@heroos-demo.idp.example.com/"],
    ["HEROOS_OIDC_ISSUER", "not a url"],
    ["HEROOS_OIDC_CLIENT_ID", "client id with spaces"],
    ["HEROOS_OIDC_AUDIENCE", "has space"],
    ["HEROOS_OIDC_AUDIENCE", OIDC_CLIENT_ID],
  ])("rejects %s=%s and names only the variable", (name, value) => {
    const result = readAuthConfig({ ...OIDC_ENV, [name]: value });
    expect(result).toEqual({ ok: false, invalid: [name] });
    expect(JSON.stringify(result)).not.toContain(value);
  });
});
