// @vitest-environment node
import { describe, expect, it } from "vitest";

import { codeChallenge, createCodeVerifier, createState, sameState } from "./pkce";
import { seal, unseal } from "./sealed";

const SECRET = Buffer.alloc(32, 7);
const OTHER_SECRET = Buffer.alloc(32, 8);

describe("sealed cookies", () => {
  it("round-trips a payload for the same purpose and key", () => {
    const sealed = seal({ accessToken: "t", exp: 1 }, SECRET, "session");
    expect(unseal(sealed, SECRET, "session")).toEqual({ accessToken: "t", exp: 1 });
  });

  it("does not contain the plaintext", () => {
    const sealed = seal({ accessToken: "plaintext-marker" }, SECRET, "session");
    expect(sealed).not.toContain("plaintext-marker");
    expect(Buffer.from(sealed.split(".")[2], "base64url").toString()).not.toContain("plaintext-marker");
  });

  it("uses a fresh IV every time", () => {
    expect(seal({ a: 1 }, SECRET, "session")).not.toEqual(seal({ a: 1 }, SECRET, "session"));
  });

  it("rejects another key, another purpose, tampering and junk", () => {
    const sealed = seal({ a: 1 }, SECRET, "login");
    expect(unseal(sealed, OTHER_SECRET, "login")).toBeNull();
    expect(unseal(sealed, SECRET, "session")).toBeNull();

    const parts = sealed.split(".");
    const body = Buffer.from(parts[2], "base64url");
    body[0] ^= 1;
    expect(unseal([parts[0], parts[1], body.toString("base64url"), parts[3]].join("."), SECRET, "login")).toBeNull();

    for (const junk of [undefined, "", "v1", "v2.a.b.c", "v1.a.b.c", sealed + "x"]) {
      expect(unseal(junk, SECRET, "login")).toBeNull();
    }
  });
});

describe("PKCE and state", () => {
  it("matches the RFC 7636 Appendix B S256 test vector", () => {
    expect(codeChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")).toBe(
      "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    );
  });

  it("creates 43-character base64url verifiers and unique states", () => {
    const verifier = createCodeVerifier();
    expect(verifier).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(createCodeVerifier()).not.toBe(verifier);
    expect(createState()).not.toBe(createState());
  });

  it("compares states exactly", () => {
    const state = createState();
    expect(sameState(state, state)).toBe(true);
    expect(sameState(state, state.slice(1))).toBe(false);
    expect(sameState(state, state.slice(0, -1) + (state.endsWith("A") ? "B" : "A"))).toBe(false);
  });
});
