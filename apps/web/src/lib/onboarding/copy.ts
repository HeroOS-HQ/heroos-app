import type { LicensingLocation } from "./model";

/**
 * Customer-facing wording for licensing and jurisdiction readiness.
 *
 * - The licensing answer is the customer's statement. Nothing here maps it to a
 *   legal regime: "Other" is never UAE Federal / MOHRE, "DIFC" is never
 *   automatically DIFC employment law (ADR-010 §6).
 * - Readiness copy is chosen only from the state the HeroOS API returns
 *   (`supported_confirmed`, `unconfirmed`, `unsupported`) and its reason code.
 *   Unknown codes fall back to the most cautious wording.
 */

export type LicensingOption = {
  value: LicensingLocation;
  label: string;
  description: string;
};

export const LICENSING_OPTIONS: readonly LicensingOption[] = [
  {
    value: "difc",
    label: "DIFC",
    description: "Your business licence was issued in the Dubai International Financial Centre.",
  },
  {
    value: "other",
    label: "Other",
    description: "Any other licensing authority, such as another free zone or a mainland (onshore) licence.",
  },
  {
    value: "not_sure",
    label: "I'm not sure",
    description: "You can confirm your licensing details later.",
  },
];

/**
 * The approved licensing-authority catalog for the "Other" answer. JJ will
 * provide it; until then it is null and customers type the authority's name.
 * When it arrives, `LicensingAuthorityField` offers it as a list (keeping a
 * typed fallback), without changing the rest of the onboarding flow. A
 * catalog entry is a name only: it never implies a jurisdiction.
 */
export type AuthorityOption = { value: string; label: string };
export const APPROVED_LICENSING_AUTHORITIES: readonly AuthorityOption[] | null = null;

export function licensingLabel(location: LicensingLocation | null): string {
  switch (location) {
    case "difc":
      return "DIFC";
    case "other":
      return "Other licensing authority";
    case "not_sure":
      return "Not sure yet";
    default:
      return "Not provided";
  }
}

/** Neutral note shown under the licensing choice; never a legal conclusion. */
export function licensingChoiceNote(location: LicensingLocation | ""): string | null {
  switch (location) {
    case "difc":
      return "We'll record that your company is licensed in the DIFC. Which employment rules apply is confirmed separately before any jurisdiction-specific guidance is offered.";
    case "other":
      return "We'll record the licensing authority you enter. Which employment rules apply is confirmed separately before any jurisdiction-specific guidance is offered.";
    case "not_sure":
      return "That's okay. Your licensing details can be confirmed later. Until then, some jurisdiction-specific guidance may be unavailable.";
    default:
      return null;
  }
}

export type Readiness = "supported_confirmed" | "unconfirmed" | "unsupported";

const JURISDICTION_NAMES: Record<string, string> = {
  uae_federal: "UAE Federal (MOHRE)",
  difc: "DIFC",
  adgm: "ADGM",
  other: "a jurisdiction outside HeroOS's current coverage",
};

export function jurisdictionName(code: string | null): string | null {
  return code !== null && Object.hasOwn(JURISDICTION_NAMES, code) ? JURISDICTION_NAMES[code] : null;
}

export type ReadinessCopy = {
  /** Short status words (never conveyed by colour alone). */
  status: string;
  tone: "positive" | "neutral" | "caution";
  title: string;
  body: string;
};

const UNCONFIRMED_BODIES: Record<string, string> = {
  licensing_not_provided:
    "We don't have your licensing details yet. Until they're provided and confirmed, jurisdiction-specific guidance isn't available.",
  licensing_not_sure:
    "That's okay. Your licensing details can be confirmed later. Until then, some jurisdiction-specific guidance may be unavailable.",
  licensing_authority_missing:
    "Add the licensing authority shown on your business licence so your details can be confirmed. Until then, jurisdiction-specific guidance isn't available.",
  awaiting_confirmation:
    "Your licensing details are saved and waiting to be confirmed. Until then, jurisdiction-specific guidance isn't available.",
  licensing_changed_since_confirmation:
    "Your licensing details changed after they were confirmed, so they need to be confirmed again. Until then, jurisdiction-specific guidance isn't available.",
};

const DEFAULT_UNCONFIRMED =
  "Your jurisdiction hasn't been confirmed yet. Until it is, jurisdiction-specific guidance isn't available.";

/**
 * Wording for the API's readiness. Only `supported_confirmed` ever says
 * guidance is available, and only when the API also says `guidance_allowed`.
 */
export function readinessCopy(input: {
  readiness: Readiness;
  reason: string;
  employmentJurisdiction: string | null;
  guidanceAllowed: boolean;
}): ReadinessCopy {
  const name = jurisdictionName(input.employmentJurisdiction);
  if (input.readiness === "supported_confirmed" && input.guidanceAllowed && name !== null) {
    return {
      status: "Confirmed",
      tone: "positive",
      title: `Jurisdiction confirmed: ${name}`,
      body: "HeroOS can use this jurisdiction when its guided workflows become available.",
    };
  }
  if (input.readiness === "unsupported") {
    return {
      status: "Not supported",
      tone: "caution",
      title: name ? `${capitalize(name)} isn't supported yet` : "This jurisdiction isn't supported yet",
      body: "HeroOS doesn't currently support guidance for this jurisdiction. Your workspace stays available, but jurisdiction-specific guidance won't be offered.",
    };
  }
  return {
    status: "Not yet confirmed",
    tone: "neutral",
    title: "Jurisdiction not yet confirmed",
    body: Object.hasOwn(UNCONFIRMED_BODIES, input.reason) ? UNCONFIRMED_BODIES[input.reason] : DEFAULT_UNCONFIRMED,
  };
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function roleLabel(role: string | null): string | null {
  if (role === "company_admin") return "Administrator";
  if (role === "member") return "Member";
  return null;
}
