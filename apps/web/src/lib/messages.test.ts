import { describe, expect, it } from "vitest";

import { authOutcomeMessage } from "./messages";

describe("authOutcomeMessage", () => {
  it("tells an unverified user how to get in", () => {
    expect(authOutcomeMessage("verify_email")).toBe(
      "Please verify your email address first. Open the link we emailed you when you signed up, then sign in again.",
    );
  });

  it.each(["", "toString", "__proto__", "<script>", "VERIFY_EMAIL"])("returns null for unknown outcome %j", (value) => {
    expect(authOutcomeMessage(value)).toBeNull();
  });
});
