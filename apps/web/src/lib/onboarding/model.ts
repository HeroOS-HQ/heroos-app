/**
 * Company onboarding and profile data model, shared by the browser forms and
 * the web server's BFF handlers (both validate; the HeroOS API validates again
 * and is authoritative).
 *
 * Limits and text rules mirror the merged M1-10C API schema
 * (apps/api/app/api/companies.py, onboarding.py): text is trimmed here, then
 * must be 1..max characters with no control or separator characters (Python's
 * `str.isprintable()`), and the employee count is a whole number 0..10,000,000.
 * No field carries an identity, Company id, role or jurisdiction confirmation:
 * the API derives or protects those.
 */

export const LIMITS = {
  companyName: 200,
  legalName: 200,
  industry: 120,
  licensingAuthority: 120,
  employeeCountMax: 10_000_000,
} as const;

export const LICENSING_LOCATIONS = ["difc", "other", "not_sure"] as const;
export type LicensingLocation = (typeof LICENSING_LOCATIONS)[number];

export function isLicensingLocation(value: unknown): value is LicensingLocation {
  return typeof value === "string" && (LICENSING_LOCATIONS as readonly string[]).includes(value);
}

export type FieldName =
  | "companyName"
  | "legalName"
  | "industry"
  | "employeeCount"
  | "licensingLocation"
  | "licensingAuthority";

export type FieldErrors = Partial<Record<FieldName, string>>;

/** The in-browser onboarding draft. Ephemeral: never persisted by the browser. */
export type OnboardingDraft = {
  companyName: string;
  legalName: string;
  industry: string;
  employeeCount: string;
  licensingLocation: LicensingLocation | "";
  licensingAuthority: string;
};

export const EMPTY_DRAFT: OnboardingDraft = {
  companyName: "",
  legalName: "",
  industry: "",
  employeeCount: "",
  licensingLocation: "",
  licensingAuthority: "",
};

// Python's str.isprintable(): no "Other" (C*) or "Separator" (Z*) character
// except the ASCII space. Mirrored so the API never refuses what we accept.
const NOT_PRINTABLE = /[\p{C}\p{Zl}\p{Zp}]|[^\P{Zs} ]/u;

export const MESSAGES = {
  companyNameRequired: "Enter your company name.",
  tooLong: (max: number) => `Use ${max.toLocaleString("en-US")} characters or fewer.`,
  unsupportedCharacters: "Remove line breaks, tabs or other special characters.",
  employeeCountFormat: "Enter a whole number, such as 12.",
  employeeCountRange: `Enter a number from 0 to ${LIMITS.employeeCountMax.toLocaleString("en-US")}.`,
  licensingLocationRequired: "Choose where your company is licensed, or choose “I'm not sure”.",
} as const;

type TextCheck = { value: string | null; error?: string };

/** Trim, then check length and characters. Empty after trimming means "not given". */
export function checkText(raw: string, max: number): TextCheck {
  const value = raw.trim();
  if (value === "") return { value: null };
  if (value.length > max) return { value: null, error: MESSAGES.tooLong(max) };
  if (NOT_PRINTABLE.test(value)) return { value: null, error: MESSAGES.unsupportedCharacters };
  return { value };
}

/** A whole number 0..10,000,000, or null when left blank. */
export function checkEmployeeCount(raw: string): { value: number | null; error?: string } {
  const value = raw.trim();
  if (value === "") return { value: null };
  if (!/^\d{1,9}$/.test(value)) return { value: null, error: MESSAGES.employeeCountFormat };
  const count = Number(value);
  if (count > LIMITS.employeeCountMax) return { value: null, error: MESSAGES.employeeCountRange };
  return { value: count };
}

/** Step 1: Company basics. */
export function validateCompanyStep(draft: OnboardingDraft): FieldErrors {
  const errors: FieldErrors = {};
  const name = checkText(draft.companyName, LIMITS.companyName);
  if (name.error) errors.companyName = name.error;
  else if (name.value === null) errors.companyName = MESSAGES.companyNameRequired;
  const legal = checkText(draft.legalName, LIMITS.legalName);
  if (legal.error) errors.legalName = legal.error;
  const industry = checkText(draft.industry, LIMITS.industry);
  if (industry.error) errors.industry = industry.error;
  const count = checkEmployeeCount(draft.employeeCount);
  if (count.error) errors.employeeCount = count.error;
  return errors;
}

/** Step 2: Licensing. A choice is required; "I'm not sure" is a valid choice. */
export function validateLicensingStep(draft: OnboardingDraft): FieldErrors {
  const errors: FieldErrors = {};
  if (!isLicensingLocation(draft.licensingLocation)) {
    errors.licensingLocation = MESSAGES.licensingLocationRequired;
  }
  if (draft.licensingLocation === "other") {
    const authority = checkText(draft.licensingAuthority, LIMITS.licensingAuthority);
    if (authority.error) errors.licensingAuthority = authority.error;
  }
  return errors;
}

/** The licensing answer exactly as the API takes it. */
export type LicensingPayload = { location: LicensingLocation; authority?: string };

/** `POST /company-registrations` body (M1-10C contract). */
export type RegistrationPayload = {
  company_name: string;
  blueprint: {
    legal_name?: string;
    industry?: string;
    employee_count?: number;
    licensing: LicensingPayload;
  };
};

export type BuildResult<T> = { ok: true; value: T } | { ok: false; errors: FieldErrors };

/**
 * The registration request for a complete draft. Optional fields are sent only
 * when given; the authority only with "Other" (a changed choice never carries a
 * stale authority).
 */
export function buildRegistrationPayload(draft: OnboardingDraft): BuildResult<RegistrationPayload> {
  const errors = { ...validateCompanyStep(draft), ...validateLicensingStep(draft) };
  if (Object.keys(errors).length > 0 || !isLicensingLocation(draft.licensingLocation)) {
    return { ok: false, errors };
  }
  const blueprint: RegistrationPayload["blueprint"] = {
    licensing: licensingPayload(draft.licensingLocation, draft.licensingAuthority),
  };
  const legal = checkText(draft.legalName, LIMITS.legalName).value;
  if (legal !== null) blueprint.legal_name = legal;
  const industry = checkText(draft.industry, LIMITS.industry).value;
  if (industry !== null) blueprint.industry = industry;
  const count = checkEmployeeCount(draft.employeeCount).value;
  if (count !== null) blueprint.employee_count = count;
  return {
    ok: true,
    value: { company_name: checkText(draft.companyName, LIMITS.companyName).value!, blueprint },
  };
}

export function licensingPayload(location: LicensingLocation, rawAuthority: string): LicensingPayload {
  if (location !== "other") return { location };
  const authority = checkText(rawAuthority, LIMITS.licensingAuthority).value;
  return authority === null ? { location } : { location, authority };
}

/** `PATCH /companies/{id}/blueprint` body: only the fields being changed. */
export type BlueprintPatch = {
  legal_name?: string | null;
  industry?: string | null;
  employee_count?: number | null;
  licensing?: LicensingPayload;
};

const own = (value: object, key: string) => Object.prototype.hasOwnProperty.call(value, key);
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** Field names (in the API's JSON) mapped to the form fields that show their errors. */
export const API_FIELDS: Record<string, FieldName> = {
  company_name: "companyName",
  legal_name: "legalName",
  industry: "industry",
  employee_count: "employeeCount",
  location: "licensingLocation",
  authority: "licensingAuthority",
  licensing: "licensingLocation",
};

type ParseResult<T> = { ok: true; value: T } | { ok: false; fields: FieldName[] };

/** A text value that is exactly what would be stored (already trimmed by the form). */
function tidyText(value: unknown, max: number): string | null {
  if (typeof value !== "string") return null;
  const checked = checkText(value, max);
  return checked.value !== null && checked.value === value ? value : null;
}

function parseLicensing(value: unknown, fields: FieldName[]): LicensingPayload | null {
  if (!isRecord(value) || Object.keys(value).some((key) => key !== "location" && key !== "authority")) {
    fields.push("licensingLocation");
    return null;
  }
  if (!isLicensingLocation(value.location)) {
    fields.push("licensingLocation");
    return null;
  }
  if (value.authority === undefined || value.authority === null) return { location: value.location };
  const authority = tidyText(value.authority, LIMITS.licensingAuthority);
  if (authority === null || value.location !== "other") {
    fields.push("licensingAuthority");
    return null;
  }
  return { location: value.location, authority };
}

function parseOptional(
  source: Record<string, unknown>,
  key: "legal_name" | "industry",
  max: number,
  fields: FieldName[],
  allowNull: boolean,
): string | null | undefined {
  if (!own(source, key)) return undefined;
  const value = source[key];
  if (value === null && allowNull) return null;
  const text = tidyText(value, max);
  if (text === null) fields.push(API_FIELDS[key]);
  return text ?? undefined;
}

function parseCount(source: Record<string, unknown>, fields: FieldName[], allowNull: boolean): number | null | undefined {
  if (!own(source, "employee_count")) return undefined;
  const value = source.employee_count;
  if (value === null && allowNull) return null;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0 || value > LIMITS.employeeCountMax) {
    fields.push("employeeCount");
    return undefined;
  }
  return value;
}

/**
 * Server-side parse of a registration request from the browser. Strict: any
 * other key (an identity, a Company id, a role, a confirmation) is refused, and
 * the API body is rebuilt from the validated values only.
 */
export function parseRegistrationRequest(body: unknown): ParseResult<RegistrationPayload> {
  const fields: FieldName[] = [];
  if (!isRecord(body) || Object.keys(body).some((key) => key !== "company_name" && key !== "blueprint")) {
    return { ok: false, fields: [] };
  }
  const name = tidyText(body.company_name, LIMITS.companyName);
  if (name === null) fields.push("companyName");
  const source = body.blueprint;
  const allowed = new Set(["legal_name", "industry", "employee_count", "licensing"]);
  if (!isRecord(source) || Object.keys(source).some((key) => !allowed.has(key))) {
    return { ok: false, fields: [...fields, "licensingLocation"] };
  }
  const blueprint: RegistrationPayload["blueprint"] = {
    licensing: { location: "not_sure" },
  };
  const legal = parseOptional(source, "legal_name", LIMITS.legalName, fields, false);
  if (typeof legal === "string") blueprint.legal_name = legal;
  const industry = parseOptional(source, "industry", LIMITS.industry, fields, false);
  if (typeof industry === "string") blueprint.industry = industry;
  const count = parseCount(source, fields, false);
  if (typeof count === "number") blueprint.employee_count = count;
  const licensing = parseLicensing(source.licensing, fields);
  if (licensing !== null) blueprint.licensing = licensing;
  if (fields.length > 0 || name === null) return { ok: false, fields: [...new Set(fields)] };
  return { ok: true, value: { company_name: name, blueprint } };
}

/** Server-side parse of a Blueprint update from the settings form. Strict, like registration. */
export function parseBlueprintPatch(body: unknown): ParseResult<BlueprintPatch> {
  const fields: FieldName[] = [];
  const allowed = new Set(["legal_name", "industry", "employee_count", "licensing"]);
  if (!isRecord(body) || Object.keys(body).length === 0 || Object.keys(body).some((key) => !allowed.has(key))) {
    return { ok: false, fields: [] };
  }
  const patch: BlueprintPatch = {};
  const legal = parseOptional(body, "legal_name", LIMITS.legalName, fields, true);
  if (legal !== undefined) patch.legal_name = legal;
  const industry = parseOptional(body, "industry", LIMITS.industry, fields, true);
  if (industry !== undefined) patch.industry = industry;
  const count = parseCount(body, fields, true);
  if (count !== undefined) patch.employee_count = count;
  if (own(body, "licensing")) {
    const licensing = parseLicensing(body.licensing, fields);
    if (licensing !== null) patch.licensing = licensing;
  }
  if (fields.length > 0) return { ok: false, fields: [...new Set(fields)] };
  return { ok: true, value: patch };
}

/** Map the API's sanitized 422 `loc` paths to form fields; unknown paths are dropped. */
export function fieldsFromApiDetail(detail: unknown): FieldName[] {
  if (!Array.isArray(detail)) return [];
  const fields = new Set<FieldName>();
  for (const error of detail) {
    if (!isRecord(error) || !Array.isArray(error.loc)) continue;
    for (let index = error.loc.length - 1; index >= 0; index -= 1) {
      const part = error.loc[index];
      if (typeof part === "string" && own(API_FIELDS, part)) {
        fields.add(API_FIELDS[part]);
        break;
      }
    }
  }
  return [...fields];
}
