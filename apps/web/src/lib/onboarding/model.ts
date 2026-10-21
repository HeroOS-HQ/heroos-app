/**
 * Company onboarding and Company Blueprint data model, shared by the browser
 * forms (onboarding and the Blueprint page) and the web server's BFF handlers
 * (both validate; the HeroOS API validates again and is authoritative). One
 * set of rules for both write paths, so both produce the same canonical values.
 *
 * Limits and text rules mirror the API schema (apps/api/app/api/companies.py,
 * app/companies/blueprint.py): one-line text is trimmed here, then must be
 * 1..max characters with no control or separator characters (Python's
 * `str.isprintable()`); multi-line text also keeps line breaks and tabs; the
 * employee count is a whole number 0..10,000,000; the website is normalized
 * exactly as the API does it (shared cases:
 * apps/api/tests/fixtures/website_urls.json). No field carries an identity,
 * Company id, role or jurisdiction confirmation: the API derives or protects
 * those. The primary contact is a Membership id the API checks.
 */

export const LIMITS = {
  companyName: 200,
  legalName: 200,
  industry: 120,
  licensingAuthority: 120,
  employeeCountMax: 10_000_000,
  websiteUrl: 500,
  companySummary: 2000,
  policyContext: 1000,
  hrSupportNotes: 500,
} as const;

/** Does the company already have HR policies? (`null` in the API: not answered.) */
export const POLICIES_EXIST = ["yes", "no", "not_sure"] as const;
export type PoliciesExist = (typeof POLICIES_EXIST)[number];

/** How the company handles HR today. */
export const HR_SUPPORT = ["none", "internal", "external", "mixed", "other"] as const;
export type HrSupport = (typeof HR_SUPPORT)[number];

export function isPoliciesExist(value: unknown): value is PoliciesExist {
  return typeof value === "string" && (POLICIES_EXIST as readonly string[]).includes(value);
}

export function isHrSupport(value: unknown): value is HrSupport {
  return typeof value === "string" && (HR_SUPPORT as readonly string[]).includes(value);
}

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
  | "licensingAuthority"
  | "websiteUrl"
  | "companySummary"
  | "policiesExist"
  | "policyContext"
  | "hrSupport"
  | "hrSupportNotes"
  | "primaryContact";

export type FieldErrors = Partial<Record<FieldName, string>>;

/** The in-browser onboarding draft. Ephemeral: never persisted by the browser. */
export type OnboardingDraft = {
  companyName: string;
  legalName: string;
  industry: string;
  employeeCount: string;
  websiteUrl: string;
  companySummary: string;
  policiesExist: PoliciesExist | "";
  licensingLocation: LicensingLocation | "";
  licensingAuthority: string;
};

export const EMPTY_DRAFT: OnboardingDraft = {
  companyName: "",
  legalName: "",
  industry: "",
  employeeCount: "",
  websiteUrl: "",
  companySummary: "",
  policiesExist: "",
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
  unsupportedTextCharacters: "Remove special or invisible characters.",
  employeeCountFormat: "Enter a whole number, such as 12.",
  employeeCountRange: `Enter a number from 0 to ${LIMITS.employeeCountMax.toLocaleString("en-US")}.`,
  licensingLocationRequired: "Choose where your company is licensed, or choose “I'm not sure”.",
  websiteFormat: "Enter your website's address, such as www.example.com.",
  websiteScheme: "Use a web address that starts with https:// or http://.",
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

// Pasted text (a website's About page, a document) often carries Windows line
// endings, non-breaking or other typographic spaces and zero-width marks. They
// are tidied before validation, so the API (which stores text exactly as sent)
// receives plain text.
export function tidyPastedText(raw: string): string {
  return raw
    .replace(/\r\n?|[\u2028\u2029]/g, "\n")
    .replace(/[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]/g, " ")
    .replace(/[\u200b\ufeff]/g, "");
}

/**
 * Multi-line plain text (the company summary, policy and HR notes): tidied and
 * trimmed, then 1..max characters (counted as the API counts them: code
 * points) where only line breaks and tabs may be invisible. Empty means "not given".
 */
export function checkPlainText(raw: string, max: number): TextCheck {
  const value = tidyPastedText(raw).trim();
  if (value === "") return { value: null };
  if (Array.from(value).length > max) return { value: null, error: MESSAGES.tooLong(max) };
  if (NOT_PRINTABLE.test(value.replace(/[\n\t]/g, ""))) return { value: null, error: MESSAGES.unsupportedTextCharacters };
  return { value };
}

const URL_SCHEME = /^([A-Za-z][A-Za-z0-9+.-]*):/;
// A DNS label, and an alphabetic or IDNA A-label top-level domain: never an IP
// address or a single-label host such as "localhost".
const URL_LABEL = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/;
const URL_TOP_LABEL = /^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$/;
// Path, query and fragment: visible ASCII except the backslash.
const URL_REST = /^[!-[\]-~]*$/;

/**
 * The company website exactly as the API stores it (mirrors
 * `normalize_website_url` in apps/api/app/companies/blueprint.py): http or
 * https only, https assumed when no scheme is given, scheme and host
 * lowercased, a lone trailing "/" dropped. Any other scheme (javascript:,
 * data:, file:, mailto:...), credentials, a port, an IP address, spaces and
 * non-ASCII characters are refused. Empty means "not given". HeroOS only
 * stores the address: nothing fetches it.
 */
export function normalizeWebsiteUrl(raw: string): TextCheck {
  const text = raw.trim();
  if (text === "") return { value: null };
  if (/[^\x21-\x7e]/.test(text)) return { value: null, error: MESSAGES.websiteFormat };
  let scheme = "https";
  let rest = text;
  const match = URL_SCHEME.exec(text);
  if (match) {
    const after = text.slice(match[0].length);
    scheme = match[1].toLowerCase();
    if ((scheme !== "https" && scheme !== "http") || !after.startsWith("//")) {
      return { value: null, error: MESSAGES.websiteScheme };
    }
    rest = after.slice(2);
  }
  const cut = rest.search(/[/?#]/);
  const end = cut === -1 ? rest.length : cut;
  const host = rest.slice(0, end).toLowerCase();
  const remainder = rest.slice(end);
  const labels = host.split(".");
  if (
    host.length > 253 ||
    labels.length < 2 ||
    !labels.every((label) => URL_LABEL.test(label)) ||
    !URL_TOP_LABEL.test(labels[labels.length - 1])
  ) {
    return { value: null, error: MESSAGES.websiteFormat };
  }
  if (!URL_REST.test(remainder)) return { value: null, error: MESSAGES.websiteFormat };
  const url = `${scheme}://${host}${remainder === "/" ? "" : remainder}`;
  if (url.length > LIMITS.websiteUrl) return { value: null, error: MESSAGES.tooLong(LIMITS.websiteUrl) };
  return { value: url };
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

/** About your company: all optional (website, summary, whether HR policies exist). */
export function validateContextStep(draft: OnboardingDraft): FieldErrors {
  const errors: FieldErrors = {};
  const website = normalizeWebsiteUrl(draft.websiteUrl);
  if (website.error) errors.websiteUrl = website.error;
  const summary = checkPlainText(draft.companySummary, LIMITS.companySummary);
  if (summary.error) errors.companySummary = summary.error;
  return errors;
}

/** Jurisdiction: a choice is required; "I'm not sure" is a valid choice. */
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

/** `POST /company-registrations` body (M1-10C contract; company context since M2-NEW-03). */
export type RegistrationPayload = {
  company_name: string;
  blueprint: {
    legal_name?: string;
    industry?: string;
    employee_count?: number;
    website_url?: string;
    company_summary?: string;
    policies_exist?: PoliciesExist;
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
  const errors = { ...validateCompanyStep(draft), ...validateContextStep(draft), ...validateLicensingStep(draft) };
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
  const website = normalizeWebsiteUrl(draft.websiteUrl).value;
  if (website !== null) blueprint.website_url = website;
  const summary = checkPlainText(draft.companySummary, LIMITS.companySummary).value;
  if (summary !== null) blueprint.company_summary = summary;
  if (isPoliciesExist(draft.policiesExist)) blueprint.policies_exist = draft.policiesExist;
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
  website_url?: string | null;
  company_summary?: string | null;
  policies_exist?: PoliciesExist | null;
  policy_context?: string | null;
  hr_support?: HrSupport | null;
  hr_support_notes?: string | null;
  primary_contact_membership_id?: string | null;
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
  website_url: "websiteUrl",
  company_summary: "companySummary",
  policies_exist: "policiesExist",
  policy_context: "policyContext",
  hr_support: "hrSupport",
  hr_support_notes: "hrSupportNotes",
  primary_contact_membership_id: "primaryContact",
};

const UUID_FORMAT = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

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

type ContextKey = "website_url" | "company_summary" | "policy_context" | "hr_support_notes";

/** A context value exactly as it would be stored (already normalized by the form). */
function parseContextText(
  source: Record<string, unknown>,
  key: ContextKey,
  fields: FieldName[],
  allowNull: boolean,
): string | null | undefined {
  if (!own(source, key)) return undefined;
  const value = source[key];
  if (value === null && allowNull) return null;
  if (typeof value === "string") {
    const checked =
      key === "website_url"
        ? normalizeWebsiteUrl(value)
        : checkPlainText(value, key === "company_summary" ? LIMITS.companySummary : key === "policy_context" ? LIMITS.policyContext : LIMITS.hrSupportNotes);
    if (checked.value !== null && checked.value === value) return value;
  }
  fields.push(API_FIELDS[key]);
  return undefined;
}

function parseChoice<T extends string>(
  source: Record<string, unknown>,
  key: "policies_exist" | "hr_support",
  accept: (value: unknown) => value is T,
  fields: FieldName[],
  allowNull: boolean,
): T | null | undefined {
  if (!own(source, key)) return undefined;
  const value = source[key];
  if (value === null && allowNull) return null;
  if (accept(value)) return value;
  fields.push(API_FIELDS[key]);
  return undefined;
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
  const allowed = new Set(["legal_name", "industry", "employee_count", "licensing", "website_url", "company_summary", "policies_exist"]);
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
  const website = parseContextText(source, "website_url", fields, false);
  if (typeof website === "string") blueprint.website_url = website;
  const summary = parseContextText(source, "company_summary", fields, false);
  if (typeof summary === "string") blueprint.company_summary = summary;
  const policies = parseChoice(source, "policies_exist", isPoliciesExist, fields, false);
  if (typeof policies === "string") blueprint.policies_exist = policies;
  const licensing = parseLicensing(source.licensing, fields);
  if (licensing !== null) blueprint.licensing = licensing;
  if (fields.length > 0 || name === null) return { ok: false, fields: [...new Set(fields)] };
  return { ok: true, value: { company_name: name, blueprint } };
}

/** Server-side parse of a Blueprint update from the settings form. Strict, like registration. */
export function parseBlueprintPatch(body: unknown): ParseResult<BlueprintPatch> {
  const fields: FieldName[] = [];
  const allowed = new Set([
    "legal_name",
    "industry",
    "employee_count",
    "licensing",
    "website_url",
    "company_summary",
    "policies_exist",
    "policy_context",
    "hr_support",
    "hr_support_notes",
    "primary_contact_membership_id",
  ]);
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
  for (const key of ["website_url", "company_summary", "policy_context", "hr_support_notes"] as const) {
    const text = parseContextText(body, key, fields, true);
    if (text !== undefined) patch[key] = text;
  }
  const policies = parseChoice(body, "policies_exist", isPoliciesExist, fields, true);
  if (policies !== undefined) patch.policies_exist = policies;
  const support = parseChoice(body, "hr_support", isHrSupport, fields, true);
  if (support !== undefined) patch.hr_support = support;
  if (own(body, "primary_contact_membership_id")) {
    const contact = body.primary_contact_membership_id;
    if (contact === null || (typeof contact === "string" && UUID_FORMAT.test(contact))) {
      patch.primary_contact_membership_id = contact;
    } else {
      fields.push("primaryContact");
    }
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
