/**
 * Page 3, Company Space: mock content for the design review (20 Oct 2026).
 * The same fictional company as Pages 1 and 2.
 *
 * JJ's reason for this page: people should know what is available to them
 * with the access they bought. Only terms from the transcript are used ("full
 * access", "one case"); package names, limits, prices, Expert Review
 * allowances and billing are NOT confirmed, so none are shown as fact. Where
 * the page needs a value it doesn't have, it says so ("To be confirmed") and
 * the access section carries a "mock data" note.
 */
import { CASES, COMPANY, PERSON } from "./scenario";

export const SPACE_STATES = [
  { key: "full", n: "1", name: "Full access", note: "What you have, at a glance.", anchor: null },
  { key: "limited", n: "2", name: "Case access (limited)", note: "One case included, and which case uses it.", anchor: null },
  { key: "attention", n: "3", name: "Blueprint needs attention", note: "A quiet status and one link to Page 2.", anchor: "blueprint" },
  { key: "expert", n: "4", name: "Expert Review available", note: "Included, and how it works.", anchor: "expert-review" },
  { key: "no-expert", n: "5", name: "Expert Review not included", note: "No pricing, no quotas.", anchor: "expert-review" },
  { key: "account", n: "6", name: "Account context", note: "Who is signed in; who else uses HeroOS.", anchor: "people" },
] as const;

export type SpaceState = (typeof SPACE_STATES)[number]["key"];

export function isSpaceState(value: string): value is SpaceState {
  return SPACE_STATES.some((state) => state.key === value);
}

export type ExpertAccess = "included" | "not_included" | "unconfirmed";

export type Space = {
  industry: string;
  jurisdiction: string | null;
  access: {
    kind: "full" | "case";
    label: string;
    line: string;
  };
  /** Case access only: the case that uses it (a reference, never a case list). */
  includedCase: { title: string; status: string } | null;
  expert: ExpertAccess;
  expertOpen: boolean;
  blueprint: { complete: boolean; attention: string[]; updated: string };
  others: { name: string; initials: string; email: string }[];
};

const MOHAMMED = { name: "Mohammed Khan", initials: "MK", email: "mohammed@bushandbush.example" };
const LAYLA = { name: "Layla Nasser", initials: "LN", email: "layla@bushandbush.example" };
const attendance = CASES.find((c) => c.id === "attendance")!;

const FULL: Space = {
  industry: "Legal and professional services",
  jurisdiction: "DIFC",
  access: {
    kind: "full",
    label: "Full access",
    line: "Use HeroOS for your company's HR situations.",
  },
  includedCase: null,
  expert: "included",
  expertOpen: false,
  blueprint: { complete: true, attention: [], updated: "16 Oct 2026" },
  others: [MOHAMMED],
};

export function spaceFor(state: SpaceState): Space {
  switch (state) {
    case "limited":
      return {
        ...FULL,
        access: { kind: "case", label: "Case access", line: "Includes one case." },
        includedCase: { title: attendance.title, status: "Open" },
        expert: "unconfirmed",
      };
    case "attention":
      // Same company data as Page 2's "missing information" state.
      return {
        ...FULL,
        jurisdiction: null,
        blueprint: { complete: false, attention: ["Company summary", "Jurisdiction", "Policies", "HR support"], updated: "20 Oct 2026" },
        others: [],
      };
    case "expert":
      return { ...FULL, expertOpen: true };
    case "no-expert":
      return { ...FULL, expert: "not_included" };
    case "account":
      return { ...FULL, others: [MOHAMMED, LAYLA] };
    default:
      return FULL;
  }
}

export const SIGNED_IN = { name: PERSON.full, initials: PERSON.initials, email: PERSON.email, company: COMPANY.name };
