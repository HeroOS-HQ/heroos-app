// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { cognitoOriginFrom, contentSecurityPolicy } from "@/lib/csp";
import { COGNITO_ORIGIN } from "@/test/fixtures";

import { proxy } from "./proxy";

const directives = (policy: string) =>
  Object.fromEntries(
    policy.split(";").map((part) => {
      const [name, ...values] = part.trim().split(/\s+/);
      return [name, values];
    }),
  );

describe("contentSecurityPolicy", () => {
  it("allows scripts and styles only with the nonce in production", () => {
    const csp = directives(contentSecurityPolicy({ nonce: "abc", cognitoOrigin: COGNITO_ORIGIN, development: false }));
    expect(csp["script-src"]).toEqual(["'self'", "'nonce-abc'", "'strict-dynamic'"]);
    expect(csp["style-src"]).toEqual(["'self'", "'nonce-abc'"]);
    expect(csp["frame-ancestors"]).toEqual(["'none'"]);
    expect(csp["object-src"]).toEqual(["'none'"]);
    expect(csp["base-uri"]).toEqual(["'none'"]);
    expect(csp["form-action"]).toEqual(["'self'", COGNITO_ORIGIN]);
    expect(csp).toHaveProperty("upgrade-insecure-requests");
    expect(JSON.stringify(csp)).not.toContain("unsafe-inline");
    expect(JSON.stringify(csp)).not.toContain("unsafe-eval");
  });

  it("adds unsafe-eval only in development and omits Cognito when unconfigured", () => {
    const csp = directives(contentSecurityPolicy({ nonce: "abc", cognitoOrigin: null, development: true }));
    expect(csp["script-src"]).toContain("'unsafe-eval'");
    expect(csp["form-action"]).toEqual(["'self'"]);
    expect(csp).not.toHaveProperty("upgrade-insecure-requests");
  });

  it.each([undefined, "", "http://x.example", "https://x.example/path", "https://*.example.com", "not a url"])(
    "ignores an invalid Cognito domain %s",
    (value) => {
      expect(cognitoOriginFrom(value)).toBeNull();
    },
  );
});

describe("proxy", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("sets a fresh nonce CSP on the response and the forwarded request", () => {
    vi.stubEnv("HEROOS_COGNITO_DOMAIN", COGNITO_ORIGIN);
    const first = proxy(new NextRequest("https://heroos-demo.example.com/"));
    const second = proxy(new NextRequest("https://heroos-demo.example.com/"));

    const policy = first.headers.get("content-security-policy")!;
    const nonce = /'nonce-([^']+)'/.exec(policy)![1];
    expect(nonce.length).toBeGreaterThanOrEqual(16);
    expect(policy).toContain(`form-action 'self' ${COGNITO_ORIGIN}`);
    expect(second.headers.get("content-security-policy")).not.toBe(policy);
    expect(first.headers.get("x-middleware-request-content-security-policy")).toBe(policy);
    expect(first.headers.get("x-middleware-request-x-nonce")).toBe(nonce);
  });
});
