import { describe, expect, it } from "vitest";

import {
  buildRegistrationPayload,
  checkEmployeeCount,
  checkText,
  EMPTY_DRAFT,
  fieldsFromApiDetail,
  MESSAGES,
  type OnboardingDraft,
  parseBlueprintPatch,
  parseRegistrationRequest,
  validateCompanyStep,
  validateLicensingStep,
} from "./model";

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
