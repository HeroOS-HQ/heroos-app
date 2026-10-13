import { describe, expect, it } from "vitest";

import { APPROVED_LICENSING_AUTHORITIES, LICENSING_OPTIONS, licensingChoiceNote, readinessCopy } from "./copy";

const unconfirmed = (reason: string) =>
  readinessCopy({ readiness: "unconfirmed", reason, employmentJurisdiction: null, guidanceAllowed: false });

describe("licensing choices (JJ, 13 October)", () => {
  it("offers DIFC, Other and I'm not sure, and nothing else", () => {
    expect(LICENSING_OPTIONS.map((option) => [option.value, option.label])).toEqual([
      ["difc", "DIFC"],
      ["other", "Other"],
      ["not_sure", "I'm not sure"],
    ]);
  });

  it("keeps 'not sure' distinct from an onshore (mainland) licence", () => {
    const other = LICENSING_OPTIONS.find((option) => option.value === "other")!;
    const notSure = LICENSING_OPTIONS.find((option) => option.value === "not_sure")!;
    expect(other.description).toMatch(/onshore/);
    expect(notSure.description).not.toMatch(/onshore|mainland/i);
  });

  it("has no invented licensing-authority catalog (JJ's list is pending)", () => {
    expect(APPROVED_LICENSING_AUTHORITIES).toBeNull();
  });

  it("never names a legal regime for a licensing answer", () => {
    for (const location of ["difc", "other", "not_sure"] as const) {
      const note = licensingChoiceNote(location)!;
      expect(note).not.toMatch(/MOHRE|federal|DIFC (law|rules) appl/i);
      expect(note).not.toMatch(/confirmed as|eligible|compliant|verified/i);
    }
    expect(licensingChoiceNote("not_sure")).toBe(
      "That's okay. Your licensing details can be confirmed later. Until then, some jurisdiction-specific guidance may be unavailable.",
    );
  });
});

describe("readinessCopy (only the API's state decides)", () => {
  it("says 'confirmed' only for supported_confirmed with guidance allowed", () => {
    const copy = readinessCopy({
      readiness: "supported_confirmed",
      reason: "confirmed",
      employmentJurisdiction: "difc",
      guidanceAllowed: true,
    });
    expect(copy).toMatchObject({ status: "Confirmed", tone: "positive", title: "Jurisdiction confirmed: DIFC" });
  });

  it("falls back to 'not yet confirmed' if guidance is not allowed or the jurisdiction is unknown", () => {
    for (const input of [
      { readiness: "supported_confirmed" as const, reason: "confirmed", employmentJurisdiction: "difc", guidanceAllowed: false },
      { readiness: "supported_confirmed" as const, reason: "confirmed", employmentJurisdiction: "mohre", guidanceAllowed: true },
    ]) {
      expect(readinessCopy(input).status).toBe("Not yet confirmed");
    }
  });

  it("explains an unsupported jurisdiction without offering anything", () => {
    const copy = readinessCopy({
      readiness: "unsupported",
      reason: "jurisdiction_not_supported",
      employmentJurisdiction: "adgm",
      guidanceAllowed: false,
    });
    expect(copy.status).toBe("Not supported");
    expect(copy.title).toBe("ADGM isn't supported yet");
    expect(copy.body).toContain("HeroOS doesn't currently support guidance for this jurisdiction");
    expect(`${copy.title} ${copy.body}`).not.toMatch(/subscri|upgrade|pay/i);
  });

  it.each([
    ["licensing_not_provided", "don't have your licensing details"],
    ["licensing_not_sure", "can be confirmed later"],
    ["licensing_authority_missing", "Add the licensing authority"],
    ["awaiting_confirmation", "waiting to be confirmed"],
    ["licensing_changed_since_confirmation", "need to be confirmed again"],
    ["a_future_reason", "hasn't been confirmed yet"],
  ])("explains %s", (reason, text) => {
    const copy = unconfirmed(reason);
    expect(copy.status).toBe("Not yet confirmed");
    expect(copy.body).toContain(text);
  });

  it("never claims compliance, verification or eligibility", () => {
    const all = [
      ...["licensing_not_provided", "licensing_not_sure", "awaiting_confirmation"].map(unconfirmed),
      readinessCopy({ readiness: "unsupported", reason: "x", employmentJurisdiction: "other", guidanceAllowed: false }),
      readinessCopy({ readiness: "supported_confirmed", reason: "confirmed", employmentJurisdiction: "uae_federal", guidanceAllowed: true }),
    ];
    for (const copy of all) expect(`${copy.title} ${copy.body}`).not.toMatch(/compliant|verified|eligible|approved/i);
  });
});
