import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  buildRegistrationPayload,
  checkEmployeeCount,
  checkPlainText,
  checkText,
  EMPTY_DRAFT,
  fieldsFromApiDetail,
  MESSAGES,
  normalizeWebsiteUrl,
  type OnboardingDraft,
  parseBlueprintPatch,
  parseRegistrationRequest,
  validateCompanyStep,
  validateContextStep,
  validateLicensingStep,
} from "./model";

// The API's own cases (apps/api/tests/fixtures/website_urls.json): both sides must agree.
const WEBSITE_CASES: { input: string; stored: string | null }[] = JSON.parse(
  readFileSync(resolve(__dirname, "../../../../api/tests/fixtures/website_urls.json"), "utf8"),
).cases;

describe("normalizeWebsiteUrl (mirrors the API exactly)", () => {
  it.each(WEBSITE_CASES)("$input → $stored", ({ input, stored }) => {
    expect(normalizeWebsiteUrl(input).value).toBe(stored);
  });

  it("explains a refusal: an unsupported scheme, or not a website address", () => {
    expect(normalizeWebsiteUrl("javascript:alert(1)")).toEqual({ value: null, error: MESSAGES.websiteScheme });
    expect(normalizeWebsiteUrl("data:text/html,x")).toEqual({ value: null, error: MESSAGES.websiteScheme });
    expect(normalizeWebsiteUrl("https://127.0.0.1")).toEqual({ value: null, error: MESSAGES.websiteFormat });
    expect(normalizeWebsiteUrl("   ")).toEqual({ value: null });
  });

  it("is idempotent: a stored address normalizes to itself", () => {
    for (const { stored } of WEBSITE_CASES) {
      if (stored !== null) expect(normalizeWebsiteUrl(stored).value).toBe(stored);
    }
  });
});

describe("checkPlainText (the summary and notes)", () => {
  it("keeps line breaks, tidies pasted spaces and line endings, trims the ends", () => {
    expect(checkPlainText("  Line one\r\n\r\nLine\u00a0two\u200b  ", 2000)).toEqual({ value: "Line one\n\nLine two" });
    expect(checkPlainText("Tabbed\tcolumns", 2000)).toEqual({ value: "Tabbed\tcolumns" });
    expect(checkPlainText(" \n ", 2000)).toEqual({ value: null });
  });

  it("counts characters as the API does (an emoji is one) and refuses invisible controls", () => {
    expect(checkPlainText("😀".repeat(5), 5)).toEqual({ value: "😀".repeat(5) });
    expect(checkPlainText("x".repeat(6), 5).error).toBe(MESSAGES.tooLong(5));
    expect(checkPlainText("bell\u0007", 100).error).toBe(MESSAGES.unsupportedTextCharacters);
  });
});

const draft = (overrides: Partial<OnboardingDraft> = {}): OnboardingDraft => ({
  ...EMPTY_DRAFT,
  companyName: "Gamma Trading",
  licensingLocation: "not_sure",
  ...overrides,
});

describe("checkText (mirrors the API's tidy-text rule)", () => {
  it("trims surrounding whitespace and treats blank as not given", () => {
    expect(checkText("  Gamma  ", 200)).toEqual({ value: "Gamma" });
    expect(checkText("   ", 200)).toEqual({ value: null });
  });

  it.each([
    ["a line break", "Gamma\nTrading"],
    ["a tab", "Gamma\tTrading"],
    ["a NUL", "Gamma\u0000"],
    ["a no-break space", "Gamma\u00a0Trading"],
    ["a zero-width joiner", "Gam\u200dma"],
    ["a line separator", "Gam\u2028ma"],
  ])("refuses %s like Python's isprintable()", (_, value) => {
    expect(checkText(value, 200).error).toBe(MESSAGES.unsupportedCharacters);
  });

  it("accepts ordinary punctuation, accents and non-Latin scripts", () => {
    for (const value of ["Gamma & Sons (FZ-LLC)", "Société Générale", "شركة جاما", "O'Brien Ltd."]) {
      expect(checkText(value, 200)).toEqual({ value });
    }
  });

  it("enforces the length after trimming", () => {
    expect(checkText(`  ${"x".repeat(200)}  `, 200)).toEqual({ value: "x".repeat(200) });
    expect(checkText("x".repeat(201), 200).error).toBe("Use 200 characters or fewer.");
  });
});

describe("checkEmployeeCount", () => {
  it.each([
    ["", null],
    ["0", 0],
    ["12", 12],
    [" 12 ", 12],
    ["10000000", 10_000_000],
  ])("accepts %j", (input, value) => {
    expect(checkEmployeeCount(input)).toEqual({ value });
  });

  it.each(["-1", "1.5", "12 people", "1e3", "0x10", "١٢"])("refuses %j as not a whole number", (input) => {
    expect(checkEmployeeCount(input).error).toBe(MESSAGES.employeeCountFormat);
  });

  it("refuses more than 10,000,000", () => {
    expect(checkEmployeeCount("10000001").error).toBe(MESSAGES.employeeCountRange);
  });
});

describe("step validation", () => {
  it("requires only the company name on step 1", () => {
    expect(validateCompanyStep(draft({ companyName: "" }))).toEqual({ companyName: MESSAGES.companyNameRequired });
    expect(validateCompanyStep(draft())).toEqual({});
  });

  it("validates optional fields when given", () => {
    const errors = validateCompanyStep(draft({ legalName: "x".repeat(201), industry: "a\tb", employeeCount: "many" }));
    expect(Object.keys(errors).sort()).toEqual(["employeeCount", "industry", "legalName"]);
  });

  it("requires a licensing choice, where 'not sure' is a valid choice", () => {
    expect(validateLicensingStep(draft({ licensingLocation: "" }))).toEqual({
      licensingLocation: MESSAGES.licensingLocationRequired,
    });
    for (const location of ["difc", "other", "not_sure"] as const) {
      expect(validateLicensingStep(draft({ licensingLocation: location }))).toEqual({});
    }
  });
});

describe("the About Your Company step", () => {
  it("is all optional, and checks what is given with the Blueprint's rules", () => {
    expect(validateContextStep(draft())).toEqual({});
    expect(validateContextStep(draft({ websiteUrl: "file:///etc/passwd", companySummary: "x".repeat(2001) }))).toEqual({
      websiteUrl: MESSAGES.websiteScheme,
      companySummary: MESSAGES.tooLong(2000),
    });
  });

  it("sends the context only when given, exactly as the API stores it", () => {
    const built = buildRegistrationPayload(
      draft({ websiteUrl: "Gamma.example/", companySummary: " Two shops.\r\nEight staff. ", policiesExist: "not_sure" }),
    );
    expect(built.ok && built.value.blueprint).toEqual({
      website_url: "https://gamma.example",
      company_summary: "Two shops.\nEight staff.",
      policies_exist: "not_sure",
      licensing: { location: "not_sure" },
    });
  });
});

describe("buildRegistrationPayload (the M1-10C contract)", () => {
  it("sends only given optional fields and the licensing answer", () => {
    const result = buildRegistrationPayload(
      draft({ companyName: "  Gamma  ", legalName: "Gamma FZ-LLC", employeeCount: "8", licensingLocation: "difc" }),
    );
    expect(result).toEqual({
      ok: true,
      value: {
        company_name: "Gamma",
        blueprint: { legal_name: "Gamma FZ-LLC", employee_count: 8, licensing: { location: "difc" } },
      },
    });
  });

  it("sends the authority only with 'other', and omits a blank one", () => {
    expect(buildRegistrationPayload(draft({ licensingLocation: "other", licensingAuthority: " Example Authority " })))
      .toMatchObject({ ok: true, value: { blueprint: { licensing: { location: "other", authority: "Example Authority" } } } });
    expect(buildRegistrationPayload(draft({ licensingLocation: "other", licensingAuthority: "" })))
      .toMatchObject({ ok: true, value: { blueprint: { licensing: { location: "other" } } } });
    // A stale authority typed before switching away from "Other" is never sent.
    const result = buildRegistrationPayload(draft({ licensingLocation: "not_sure", licensingAuthority: "Stale" }));
    expect(result).toMatchObject({ ok: true, value: { blueprint: { licensing: { location: "not_sure" } } } });
    expect(JSON.stringify(result)).not.toContain("Stale");
  });

  it("never carries an identity, Company id, role or jurisdiction", () => {
    const result = buildRegistrationPayload(draft({ licensingLocation: "difc" }));
    expect(result.ok && Object.keys(result.value)).toEqual(["company_name", "blueprint"]);
    expect(result.ok && Object.keys(result.value.blueprint)).toEqual(["licensing"]);
  });

  it("returns every error of an incomplete draft", () => {
    expect(buildRegistrationPayload({ ...EMPTY_DRAFT })).toEqual({
      ok: false,
      errors: { companyName: MESSAGES.companyNameRequired, licensingLocation: MESSAGES.licensingLocationRequired },
    });
  });
});

describe("server-side parsing", () => {
  it("accepts exactly what the browser form builds", () => {
    const built = buildRegistrationPayload(
      draft({ legalName: "Gamma FZ-LLC", industry: "Retail", employeeCount: "8", licensingLocation: "other", licensingAuthority: "X" }),
    );
    expect(built.ok && parseRegistrationRequest(built.value)).toEqual({ ok: true, value: built.ok ? built.value : null });
  });

  it.each([null, [], "text", 42])("refuses a non-object body %j", (value) => {
    expect(parseRegistrationRequest(value).ok).toBe(false);
  });

  it("refuses unknown keys at any level of a Blueprint patch", () => {
    expect(parseBlueprintPatch({ industry: "x", role: "company_admin" }).ok).toBe(false);
    expect(parseBlueprintPatch({ licensing: { location: "difc", jurisdiction: "difc" } }).ok).toBe(false);
    expect(parseBlueprintPatch({}).ok).toBe(false);
    expect(parseBlueprintPatch({ industry: null, employee_count: null })).toEqual({
      ok: true,
      value: { industry: null, employee_count: null },
    });
  });
});

describe("server-side parsing of the company context", () => {
  it("accepts the context exactly as the forms build it, and a primary contact id in a patch", () => {
    const contact = "d3e0a000-0000-4000-8000-00000000a001";
    const patch = {
      website_url: "https://gamma.example",
      company_summary: "Two shops.\n\nEight staff.",
      policies_exist: "yes",
      policy_context: null,
      hr_support: "mixed",
      hr_support_notes: "A consultant helps.",
      primary_contact_membership_id: contact,
    };
    expect(parseBlueprintPatch(patch)).toEqual({ ok: true, value: patch });
    const registration = {
      company_name: "Gamma",
      blueprint: { website_url: "https://gamma.example", company_summary: "Two shops.", policies_exist: "no", licensing: { location: "difc" } },
    };
    expect(parseRegistrationRequest(registration)).toEqual({ ok: true, value: registration });
  });

  it.each([
    ["an un-normalized website", { website_url: "Gamma.example" }, "websiteUrl"],
    ["an unsafe website", { website_url: "javascript:alert(1)" }, "websiteUrl"],
    ["untidy summary", { company_summary: " padded " }, "companySummary"],
    ["an overlong policy context", { policy_context: "x".repeat(1001) }, "policyContext"],
    ["an unknown policies answer", { policies_exist: "maybe" }, "policiesExist"],
    ["an unknown HR support", { hr_support: "outsourced" }, "hrSupport"],
    ["a malformed contact", { primary_contact_membership_id: "someone" }, "primaryContact"],
  ])("refuses %s in a patch, naming the field", (_, body, field) => {
    expect(parseBlueprintPatch(body)).toEqual({ ok: false, fields: [field] });
  });

  it("never lets registration choose a primary contact or the later Blueprint details", () => {
    const blueprint = { licensing: { location: "difc" } };
    for (const extra of [
      { primary_contact_membership_id: "d3e0a000-0000-4000-8000-00000000a001" },
      { hr_support: "none" },
      { policy_context: "Handbook" },
    ]) {
      expect(parseRegistrationRequest({ company_name: "Gamma", blueprint: { ...blueprint, ...extra } }).ok).toBe(false);
    }
  });
});

describe("fieldsFromApiDetail", () => {
  it("maps known API field paths and ignores everything else", () => {
    expect(
      fieldsFromApiDetail([
        { loc: ["body", "company_name"] },
        { loc: ["body", "blueprint", "licensing", "location"] },
        { loc: ["body", "blueprint", "employee_count"] },
        { loc: ["body", "role"] },
        { loc: "body" },
        "junk",
      ]),
    ).toEqual(["companyName", "licensingLocation", "employeeCount"]);
    expect(fieldsFromApiDetail(undefined)).toEqual([]);
  });
});
