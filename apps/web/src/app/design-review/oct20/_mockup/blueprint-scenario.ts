/**
 * Page 2, Company Blueprint: mock content for the design review (20 Oct
 * 2026). Bush & Bush is the same fictional company as on Page 1.
 *
 * What is grounded in the current product:
 * - legal name, industry, employee count and the licensing answer (DIFC /
 *   another authority / not sure) are the API's Blueprint fields;
 * - jurisdiction confirmation is a separate backend state; Page 2 shows the
 *   company's current setting only, never a "confirmed" badge.
 *
 * What is new and only illustrative: the company summary, policies, HR
 * support, primary contact and the people list (names and emails only: no
 * roles or permissions on Page 2). Nothing here is a supported jurisdiction
 * list, a policy rule, a permission rule or a legal claim.
 */
import { COMPANY, PERSON } from "./scenario";

export const BLUEPRINT_STATES = [
  { key: "review", n: "1", name: "Review", note: "Scan what HeroOS knows; one Edit for everything.", anchor: null },
  { key: "edit", n: "2", name: "Edit mode", note: "Every field editable at once; nothing to save yet.", anchor: null },
  { key: "unsaved", n: "3", name: "Unsaved changes", note: "Edited fields are marked; the save bar appears.", anchor: null },
  { key: "saved", n: "4", name: "Saved", note: "A calm confirmation of what changed.", anchor: null },
  { key: "incomplete", n: "5", name: "Missing information", note: "What needs attention, and what it affects.", anchor: null },
  { key: "policies", n: "6", name: "Policies added", note: "Does HeroOS know our policies? Yes.", anchor: "policies" },
  { key: "no-policies", n: "7", name: "No policies yet", note: "Add them, or say there are none.", anchor: "policies" },
  { key: "users", n: "8", name: "Company users", note: "Primary contact once; other people by name and email.", anchor: "people" },
] as const;

export type BlueprintState = (typeof BLUEPRINT_STATES)[number]["key"];

export function isBlueprintState(value: string): value is BlueprintState {
  return BLUEPRINT_STATES.some((state) => state.key === value);
}

export type Policy = { name: string; meta: string };
export type CompanyUser = { name: string; initials: string; email: string; you?: boolean; primary?: boolean };
export type HrSupport = "none" | "internal" | "external";

export const HR_OPTIONS: { value: HrSupport; label: string; hint: string }[] = [
  { value: "none", label: "No dedicated HR team", hint: "HR matters are handled by the founders or managers." },
  { value: "internal", label: "Internal HR contact", hint: "Someone in the company looks after HR." },
  { value: "external", label: "External HR support", hint: "An outside consultant or provider supports you." },
];

export type Blueprint = {
  name: string;
  legalName: string;
  industry: string;
  employees: string | null;
  summary: string | null;
  jurisdiction: {
    choice: "difc" | "other" | "not_sure";
    label: string;
    detail: string | null;
    /** As the backend reports it today; never a legal verification. */
    confirmed: boolean;
  };
  policies: Policy[];
  hr: HrSupport | null;
  hrNote: string | null;
  contactTitle: string;
  users: CompanyUser[];
  updated: string;
};

const DANIEL: CompanyUser = {
  name: PERSON.full,
  initials: PERSON.initials,
  email: PERSON.email,
  you: true,
  primary: true,
};
const MOHAMMED: CompanyUser = { name: "Mohammed Khan", initials: "MK", email: "mohammed@bushandbush.example" };
const LAYLA: CompanyUser = { name: "Layla Nasser", initials: "LN", email: "layla@bushandbush.example" };

const POLICIES: Policy[] = [
  { name: "Employee handbook", meta: "PDF · added 2 Oct 2026" },
  { name: "Leave and attendance policy", meta: "PDF · added 2 Oct 2026" },
  { name: "Disciplinary policy", meta: "Word document · added 9 Oct 2026" },
];

const COMPLETE: Blueprint = {
  name: COMPANY.name,
  legalName: COMPANY.legalName,
  industry: "Legal and professional services",
  employees: "24",
  summary:
    "Corporate and employment law firm in the DIFC. Two partners lead small teams of associates and paralegals, supported by front-desk and finance staff. About 24 people, all in one Dubai office.",
  jurisdiction: { choice: "difc", label: "DIFC", detail: "Dubai International Financial Centre", confirmed: true },
  policies: POLICIES,
  hr: "none",
  hrNote: "The managing partner handles HR matters.",
  contactTitle: "Managing Partner",
  users: [DANIEL, MOHAMMED],
  updated: "16 Oct 2026 by Daniel Haddad",
};

/** The edits made in states 3–4: the summary and the HR support. */
export const EDITED_SUMMARY =
  "Corporate and employment law firm in the DIFC. Two partners lead small teams of associates and paralegals, supported by front-desk and finance staff. About 26 people, all in one Dubai office; two new associates join in November.";

const SAVED: Blueprint = {
  ...COMPLETE,
  summary: EDITED_SUMMARY,
  hr: "external",
  hrNote: "An outside HR consultant supports us on contracts and policies.",
  updated: "just now by Daniel Haddad",
};

const INCOMPLETE: Blueprint = {
  ...COMPLETE,
  employees: null,
  summary: null,
  jurisdiction: { choice: "not_sure", label: "Not sure yet", detail: null, confirmed: false },
  policies: [],
  hr: null,
  hrNote: null,
  users: [DANIEL],
  updated: "20 Oct 2026 by Daniel Haddad",
};

export function blueprintFor(state: BlueprintState): Blueprint {
  switch (state) {
    case "saved":
      return SAVED;
    case "unsaved":
      return SAVED;
    case "incomplete":
      return INCOMPLETE;
    case "no-policies":
      return { ...COMPLETE, policies: [] };
    case "users":
      return { ...COMPLETE, users: [DANIEL, MOHAMMED, LAYLA] };
    default:
      return COMPLETE;
  }
}

/** Details that need attention (missing context HeroOS relies on). */
export function attentionOf(blueprint: Blueprint): { id: string; label: string }[] {
  const items: { id: string; label: string }[] = [];
  if (!blueprint.summary) items.push({ id: "basics", label: "Company summary" });
  if (blueprint.jurisdiction.choice === "not_sure") items.push({ id: "jurisdiction", label: "Jurisdiction" });
  if (blueprint.policies.length === 0) items.push({ id: "policies", label: "Policies" });
  if (!blueprint.hr) items.push({ id: "hr", label: "HR support" });
  return items;
}
