// @vitest-environment node
import { describe, expect, it } from "vitest";

import { ENV } from "@/test/fixtures";

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
        "HEROOS_COGNITO_DOMAIN",
        "HEROOS_COGNITO_CLIENT_ID",
        "HEROOS_API_BASE_URL",
        "HEROOS_DEMO_COMPANY_ID",
        "HEROOS_WEB_SESSION_SECRET",
      ],
    });
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
    ["HEROOS_WEB_SESSION_SECRET", "too-short"],
    ["HEROOS_WEB_SESSION_SECRET", "0F".repeat(32)],
  ])("rejects %s=%s and names only the variable", (name, value) => {
    const result = readAuthConfig({ ...ENV, [name]: value });
    expect(result).toEqual({ ok: false, invalid: [name] });
    expect(JSON.stringify(result)).not.toContain(value);
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
