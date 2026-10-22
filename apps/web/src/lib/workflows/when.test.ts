import { describe, expect, it } from "vitest";

import { caseWhen } from "./when";

describe("caseWhen", () => {
  const now = new Date(2026, 9, 21, 15, 30);

  it("says the time today, the day this year and the year before that", () => {
    expect(caseWhen(new Date(2026, 9, 21, 9, 12).toISOString(), now)).toBe("09:12");
    expect(caseWhen(new Date(2026, 9, 16, 9, 0).toISOString(), now)).toBe("16 Oct");
    expect(caseWhen(new Date(2025, 11, 2, 9, 0).toISOString(), now)).toBe("2 Dec 2025");
  });

  it("says nothing for a time it can't read", () => {
    expect(caseWhen("not a date", now)).toBe("");
  });
});
