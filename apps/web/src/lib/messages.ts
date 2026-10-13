/**
 * Fixed user-facing messages for sign-in outcomes. No identity-provider or API
 * error text is ever rendered: only these strings, selected by a known code.
 */

const AUTH_MESSAGES: Record<string, string> = {
  failed: "Sign-in could not be completed. Please try again.",
  cancelled: "Sign-in was cancelled.",
  expired: "The sign-in attempt expired. Please try again.",
  unavailable: "Sign-in is temporarily unavailable. Please try again later.",
};

/** Fixed message for a known sign-in outcome; unknown values yield null. */
export function authOutcomeMessage(outcome: string | null): string | null {
  return outcome !== null && Object.hasOwn(AUTH_MESSAGES, outcome) ? AUTH_MESSAGES[outcome] : null;
}

export const NOT_CONFIGURED_MESSAGE = "Sign-in is not configured for this deployment.";
