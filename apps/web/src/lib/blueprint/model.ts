import { jurisdictionName, readinessCopy } from "@/lib/onboarding/copy";
import {
  type BlueprintPatch,
  checkEmployeeCount,
  checkPlainText,
  checkText,
  type FieldErrors,
  type FieldName,
  type HrSupport,
  LIMITS,
  type LicensingLocation,
  licensingPayload,
  normalizeWebsiteUrl,
  type PoliciesExist,
} from "@/lib/onboarding/model";
import type { Blueprint, BlueprintDetail, BlueprintPerson } from "@/lib/server/heroos-api";
import { formatDay } from "@/lib/workflows/copy";

/**
 * The Company Blueprint page (approved Oct 20 design, Page 2) over the
 * Blueprint the API keeps: the canonical company context (M2-NEW-03). The
 * company's display name is the workspace name (read only here); everything
 * else is edited as one form and saved as one patch of the changed fields.
 * Completeness is the API's (`missing`). Validation is the onboarding's
 * (`lib/onboarding/model.ts`), so both write the same values.
 *
 * Against an API from before M2-NEW-03 (`version: "legacy"`) only the profile
 * and jurisdiction exist: the page shows and saves only those.
 */

export type BlueprintForm = {
  legalName: string;
  industry: string;
  employeeCount: string;
  websiteUrl: string;
  companySummary: string;
  licensingLocation: LicensingLocation | "";
  licensingAuthority: string;
  policiesExist: PoliciesExist | "";
  policyContext: string;
  hrSupport: HrSupport | "";
  hrSupportNotes: string;
  /** A Membership id, or "" for none. */
  primaryContact: string;
};

export type EditableField = Exclude<FieldName, "companyName">;

export const FIELD_LABELS: Record<EditableField, string> = {
  legalName: "Legal company name",
  industry: "Industry",
  employeeCount: "Number of employees",
  websiteUrl: "Company website",
  companySummary: "Company summary",
  licensingLocation: "Jurisdiction",
  licensingAuthority: "Licensing authority",
  policiesExist: "HR policies",
  policyContext: "Policy details",
  hrSupport: "HR support",
  hrSupportNotes: "HR support notes",
  primaryContact: "Primary contact",
};

/** Field order, for focusing the first error. */
export const FIELD_ORDER: EditableField[] = [
  "legalName",
  "industry",
  "employeeCount",
  "websiteUrl",
  "companySummary",
  "licensingLocation",
  "licensingAuthority",
  "policiesExist",
  "policyContext",
  "hrSupport",
  "hrSupportNotes",
  "primaryContact",
];

/** Only these exist in a legacy API. */
const LEGACY_FIELDS = new Set<EditableField>(["legalName", "industry", "employeeCount", "licensingLocation", "licensingAuthority"]);

export function fieldsOf(blueprint: Blueprint): EditableField[] {
  return blueprint.version === "context" ? FIELD_ORDER : FIELD_ORDER.filter((field) => LEGACY_FIELDS.has(field));
}

export const FIELD_IDS: Record<EditableField, string> = {
  legalName: "bp-legal",
  industry: "bp-industry",
  employeeCount: "bp-employees",
  websiteUrl: "bp-website",
  companySummary: "bp-summary",
  licensingLocation: "bp-jurisdiction-difc",
  licensingAuthority: "bp-authority",
  policiesExist: "bp-policies-yes",
  policyContext: "bp-policy-context",
  hrSupport: "bp-hr-none",
  hrSupportNotes: "bp-hr-notes",
  primaryContact: "bp-contact",
};

export const SUMMARY_HELP =
  "Briefly describe what your company does and how your team is structured. You can paste or adapt content from your website or About page.";

export const POLICIES_OPTIONS: { value: PoliciesExist; title: string; hint: string }[] = [
  { value: "yes", title: "Yes", hint: "For example, an employee handbook or a disciplinary policy." },
  { value: "no", title: "No, not yet", hint: "HeroOS works without them." },
  { value: "not_sure", title: "Not sure", hint: "You can answer later." },
];

export const HR_SUPPORT_OPTIONS: { value: HrSupport; title: string; hint: string }[] = [
  { value: "none", title: "No dedicated HR", hint: "Founders or managers handle HR matters." },
  { value: "internal", title: "Someone in the company", hint: "An HR person or a manager looks after HR." },
  { value: "external", title: "An outside provider", hint: "A consultant or HR agency supports you." },
  { value: "mixed", title: "Both", hint: "Someone inside, with outside support." },
  { value: "other", title: "Something else", hint: "Tell HeroOS in the notes." },
];

export function policiesLabel(value: PoliciesExist | null): string | null {
  switch (value) {
    case "yes":
      return "Yes, the company has HR policies";
    case "no":
      return "No HR policies yet";
    case "not_sure":
      return "Not sure yet";
    default:
      return null;
  }
}

export function hrSupportLabel(value: HrSupport | null): string | null {
  return HR_SUPPORT_OPTIONS.find((option) => option.value === value)?.title ?? null;
}

/**
 * A person in words. HeroOS keeps no names or email addresses, so people are
 * told apart by "You" and when they joined. The page carries no roles (the
 * approved design), though the API and the HeroOS context keep them.
 */
export function personLabel(person: BlueprintPerson): { name: string; detail: string | null } {
  if (person.isCurrentUser) return { name: "You", detail: null };
  return { name: "Another person", detail: `joined ${formatDay(person.memberSince)}` };
}

/** The primary contact's choices: everyone with access, you first. */
export function contactChoices(blueprint: Blueprint): BlueprintPerson[] {
  return [...blueprint.people].sort((a, b) => Number(b.isCurrentUser) - Number(a.isCurrentUser));
}

export function formFrom(blueprint: Blueprint): BlueprintForm {
  return {
    legalName: blueprint.legalName ?? "",
    industry: blueprint.industry ?? "",
    employeeCount: blueprint.employeeCount === null ? "" : String(blueprint.employeeCount),
    websiteUrl: blueprint.websiteUrl ?? "",
    companySummary: blueprint.companySummary ?? "",
    licensingLocation: blueprint.licensing.location ?? "",
    licensingAuthority: blueprint.licensing.authority ?? "",
    policiesExist: blueprint.policiesExist ?? "",
    policyContext: blueprint.policyContext ?? "",
    hrSupport: blueprint.hrSupport ?? "",
    hrSupportNotes: blueprint.hrSupportNotes ?? "",
    primaryContact: blueprint.primaryContact?.membershipId ?? "",
  };
}

type Checked<T> = { value: T | null; error?: string };

/** Validate the form and build a patch of the changed fields only. */
export function buildPatch(form: BlueprintForm, saved: Blueprint): { patch: BlueprintPatch; errors: FieldErrors } {
  const errors: FieldErrors = {};
  const patch: BlueprintPatch = {};
  function compare<T>(field: EditableField, checked: Checked<T>, current: T | null, apply: (value: T | null) => void) {
    if (checked.error) errors[field] = checked.error;
    else if (checked.value !== current) apply(checked.value);
  }
  compare("legalName", checkText(form.legalName, LIMITS.legalName), saved.legalName, (value) => (patch.legal_name = value));
  compare("industry", checkText(form.industry, LIMITS.industry), saved.industry, (value) => (patch.industry = value));
  compare("employeeCount", checkEmployeeCount(form.employeeCount), saved.employeeCount, (value) => (patch.employee_count = value));
  if (form.licensingLocation !== "") {
    const authority = checkText(form.licensingAuthority, LIMITS.licensingAuthority);
    if (form.licensingLocation === "other" && authority.error) {
      errors.licensingAuthority = authority.error;
    } else {
      const next = licensingPayload(form.licensingLocation, form.licensingAuthority);
      if (next.location !== saved.licensing.location || (next.authority ?? null) !== saved.licensing.authority) {
        patch.licensing = next;
      }
    }
  }
  if (saved.version === "legacy") return { patch, errors };

  compare("websiteUrl", normalizeWebsiteUrl(form.websiteUrl), saved.websiteUrl, (value) => (patch.website_url = value));
  compare("companySummary", checkPlainText(form.companySummary, LIMITS.companySummary), saved.companySummary, (value) => (patch.company_summary = value));
  compare("policyContext", checkPlainText(form.policyContext, LIMITS.policyContext), saved.policyContext, (value) => (patch.policy_context = value));
  compare("hrSupportNotes", checkPlainText(form.hrSupportNotes, LIMITS.hrSupportNotes), saved.hrSupportNotes, (value) => (patch.hr_support_notes = value));
  // Choices are only ever set from the page's options; clearing one isn't offered.
  if (form.policiesExist !== "" && form.policiesExist !== saved.policiesExist) patch.policies_exist = form.policiesExist;
  if (form.hrSupport !== "" && form.hrSupport !== saved.hrSupport) patch.hr_support = form.hrSupport;
  if (form.primaryContact !== "" && form.primaryContact !== (saved.primaryContact?.membershipId ?? "")) {
    patch.primary_contact_membership_id = form.primaryContact;
  }
  return { patch, errors };
}

const PATCH_LABELS: [keyof BlueprintPatch, EditableField][] = [
  ["legal_name", "legalName"],
  ["industry", "industry"],
  ["employee_count", "employeeCount"],
  ["website_url", "websiteUrl"],
  ["company_summary", "companySummary"],
  ["licensing", "licensingLocation"],
  ["policies_exist", "policiesExist"],
  ["policy_context", "policyContext"],
  ["hr_support", "hrSupport"],
  ["hr_support_notes", "hrSupportNotes"],
  ["primary_contact_membership_id", "primaryContact"],
];

/** The fields a patch changes, in words (the unsaved bar, the confirmation). */
export function changedLabels(patch: BlueprintPatch): string[] {
  return PATCH_LABELS.filter(([key]) => key in patch).map(([, field]) => FIELD_LABELS[field]);
}

/** Which form fields differ from what is saved (the "Edited" markers), whether or not they are valid yet. */
export function editedFields(form: BlueprintForm, saved: Blueprint): Set<EditableField> {
  const initial = formFrom(saved);
  const edited = new Set<EditableField>();
  const texts: (keyof BlueprintForm & EditableField)[] = [
    "legalName",
    "industry",
    "employeeCount",
    "websiteUrl",
    "companySummary",
    "policyContext",
    "hrSupportNotes",
  ];
  for (const field of texts) {
    if (form[field].trim() !== initial[field]) edited.add(field);
  }
  for (const field of ["policiesExist", "hrSupport", "primaryContact"] as const) {
    if (form[field] !== initial[field]) edited.add(field);
  }
  if (
    form.licensingLocation !== initial.licensingLocation ||
    (form.licensingLocation === "other" && form.licensingAuthority.trim() !== initial.licensingAuthority)
  ) {
    edited.add("licensingLocation");
  }
  return edited;
}

/** A detail HeroOS relies on that isn't there yet (approved design: "needs attention"). */
export type Attention = { field: EditableField; label: string };

const DETAIL_FIELDS: Record<Exclude<BlueprintDetail, "jurisdiction">, EditableField> = {
  legal_name: "legalName",
  industry: "industry",
  employee_count: "employeeCount",
  company_summary: "companySummary",
  policies: "policiesExist",
  hr_support: "hrSupport",
  primary_contact: "primaryContact",
};

/** The API's completeness in words (a legacy API's Blueprint: the four details it keeps). */
export function attentionOf(blueprint: Blueprint): Attention[] {
  const { location, authority } = blueprint.licensing;
  const jurisdiction: Attention =
    location === "other" && !authority
      ? { field: "licensingAuthority", label: FIELD_LABELS.licensingAuthority }
      : { field: "licensingLocation", label: FIELD_LABELS.licensingLocation };
  if (blueprint.missing !== null) {
    return blueprint.missing.map((detail) =>
      detail === "jurisdiction" ? jurisdiction : { field: DETAIL_FIELDS[detail], label: FIELD_LABELS[DETAIL_FIELDS[detail]] },
    );
  }
  const items: Attention[] = [];
  if (!blueprint.legalName) items.push({ field: "legalName", label: FIELD_LABELS.legalName });
  if (!blueprint.industry) items.push({ field: "industry", label: FIELD_LABELS.industry });
  if (blueprint.employeeCount === null) items.push({ field: "employeeCount", label: FIELD_LABELS.employeeCount });
  if (location === null || location === "not_sure" || (location === "other" && !authority)) items.push(jurisdiction);
  return items;
}

/**
 * The company's jurisdiction as the page shows it: plainly, never as a legal
 * verification (no "confirmed" badge). The name HeroOS works with when it has
 * confirmed one, otherwise the founder's licensing answer; `note` is the API's
 * readiness in words while jurisdiction-specific guidance isn't available.
 */
export type JurisdictionDisplay =
  | { kind: "missing"; note: string }
  | { kind: "set"; label: string; detail: string | null; note: string | null };

export function jurisdictionDisplay(blueprint: Blueprint): JurisdictionDisplay {
  const { location, authority } = blueprint.licensing;
  const { jurisdiction } = blueprint;
  const confirmed =
    jurisdiction.readiness === "supported_confirmed" && jurisdiction.guidanceAllowed
      ? jurisdictionName(jurisdiction.employmentJurisdiction)
      : null;
  // The API's readiness, in its own words (an unsupported jurisdiction is named first).
  const copy = readinessCopy(jurisdiction);
  const note = confirmed === null ? (jurisdiction.readiness === "unsupported" ? `${copy.title}. ${copy.body}` : copy.body) : null;
  if (location === null || location === "not_sure") {
    return { kind: "missing", note: note ?? "Until a jurisdiction is set, HeroOS can't give jurisdiction-specific guidance." };
  }
  if (location === "difc") {
    return { kind: "set", label: confirmed ?? "DIFC", detail: "Dubai International Financial Centre", note };
  }
  return {
    kind: "set",
    label: confirmed ?? authority ?? "Another jurisdiction",
    detail: authority ? `Licensed by ${authority}` : "Licensing authority not added yet",
    note,
  };
}
