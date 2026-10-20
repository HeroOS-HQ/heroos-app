import { jurisdictionName, readinessCopy } from "@/lib/onboarding/copy";
import {
  type BlueprintPatch,
  checkEmployeeCount,
  checkText,
  type FieldErrors,
  type FieldName,
  LIMITS,
  type LicensingLocation,
  licensingPayload,
} from "@/lib/onboarding/model";
import type { Blueprint } from "@/lib/server/heroos-api";

/**
 * The Company Blueprint page (approved Oct 20 design, Page 2) over the
 * Blueprint the API keeps today: legal name, industry, number of employees and
 * the licensing answer, with the jurisdiction HeroOS confirmed from it. The
 * approved design's other sections (website and summary, policies, HR support,
 * people) have no field in the API yet (M2-NEW-03), so nothing here stores or
 * pretends to store them.
 */

export type BlueprintForm = {
  legalName: string;
  industry: string;
  employeeCount: string;
  licensingLocation: LicensingLocation | "";
  licensingAuthority: string;
};

export type EditableField = Exclude<FieldName, "companyName">;

export const FIELD_LABELS: Record<EditableField, string> = {
  legalName: "Legal company name",
  industry: "Industry",
  employeeCount: "Number of employees",
  licensingLocation: "Jurisdiction",
  licensingAuthority: "Licensing authority",
};

/** Field order, for focusing the first error. */
export const FIELD_ORDER: EditableField[] = ["legalName", "industry", "employeeCount", "licensingLocation", "licensingAuthority"];

export const FIELD_IDS: Record<EditableField, string> = {
  legalName: "bp-legal",
  industry: "bp-industry",
  employeeCount: "bp-employees",
  licensingLocation: "bp-jurisdiction-difc",
  licensingAuthority: "bp-authority",
};

export function formFrom(blueprint: Blueprint): BlueprintForm {
  return {
    legalName: blueprint.legalName ?? "",
    industry: blueprint.industry ?? "",
    employeeCount: blueprint.employeeCount === null ? "" : String(blueprint.employeeCount),
    licensingLocation: blueprint.licensing.location ?? "",
    licensingAuthority: blueprint.licensing.authority ?? "",
  };
}

/** Validate the form and build a patch of the changed fields only. */
export function buildPatch(form: BlueprintForm, saved: Blueprint): { patch: BlueprintPatch; errors: FieldErrors } {
  const errors: FieldErrors = {};
  const patch: BlueprintPatch = {};
  const legal = checkText(form.legalName, LIMITS.legalName);
  if (legal.error) errors.legalName = legal.error;
  else if (legal.value !== saved.legalName) patch.legal_name = legal.value;
  const industry = checkText(form.industry, LIMITS.industry);
  if (industry.error) errors.industry = industry.error;
  else if (industry.value !== saved.industry) patch.industry = industry.value;
  const count = checkEmployeeCount(form.employeeCount);
  if (count.error) errors.employeeCount = count.error;
  else if (count.value !== saved.employeeCount) patch.employee_count = count.value;
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
  return { patch, errors };
}

/** The fields a patch changes, in words (the unsaved bar, the confirmation). */
export function changedLabels(patch: BlueprintPatch): string[] {
  const labels: string[] = [];
  if ("legal_name" in patch) labels.push(FIELD_LABELS.legalName);
  if ("industry" in patch) labels.push(FIELD_LABELS.industry);
  if ("employee_count" in patch) labels.push(FIELD_LABELS.employeeCount);
  if ("licensing" in patch) labels.push(FIELD_LABELS.licensingLocation);
  return labels;
}

/** Which form fields differ from what is saved (the "Edited" markers), whether or not they are valid yet. */
export function editedFields(form: BlueprintForm, saved: Blueprint): Set<EditableField> {
  const initial = formFrom(saved);
  const edited = new Set<EditableField>();
  if (form.legalName.trim() !== initial.legalName) edited.add("legalName");
  if (form.industry.trim() !== initial.industry) edited.add("industry");
  if (form.employeeCount.trim() !== initial.employeeCount) edited.add("employeeCount");
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

export function attentionOf(blueprint: Blueprint): Attention[] {
  const items: Attention[] = [];
  if (!blueprint.legalName) items.push({ field: "legalName", label: FIELD_LABELS.legalName });
  if (!blueprint.industry) items.push({ field: "industry", label: FIELD_LABELS.industry });
  if (blueprint.employeeCount === null) items.push({ field: "employeeCount", label: FIELD_LABELS.employeeCount });
  const { location, authority } = blueprint.licensing;
  if (location === null || location === "not_sure") items.push({ field: "licensingLocation", label: FIELD_LABELS.licensingLocation });
  else if (location === "other" && !authority) items.push({ field: "licensingAuthority", label: FIELD_LABELS.licensingAuthority });
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
