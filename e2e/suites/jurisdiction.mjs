// Phase G (API + operator): jurisdiction readiness is never inferred from the
// licensing answer; only a trusted confirmation that still matches the current
// answer, for a supported jurisdiction, allows jurisdiction-specific guidance.
// The UI half (what the workspace shows) is in browser.mjs.
import { newFounder, quote } from "./common.mjs";

export async function run(ctx) {
  const { check, fixtures, apiFetch } = ctx;
  const readiness = async (founder) => (await apiFetch(`/companies/${founder.companyId}/blueprint`, { token: founder.token })).json?.jurisdiction;
  const describe = (j) => `${j?.readiness}/${j?.reason}/${j?.employment_jurisdiction}/${j?.guidance_allowed}`;

  const inputs = {
    difc: { location: "difc" },
    otherWithAuthority: { location: "other", authority: "Example Free Zone Authority" },
    otherWithoutAuthority: { location: "other" },
    notSure: { location: "not_sure" },
  };
  const founders = {};
  for (const [name, licensing] of Object.entries(inputs)) {
    founders[name] = await newFounder(ctx, `j-${name}`, { company_name: `[SYNTHETIC E2E] J ${name}`, blueprint: { licensing } });
  }
  founders.missing = await newFounder(ctx, "j-missing");
  ctx.jurisdictionFounders = founders;

  const expected = {
    difc: "unconfirmed/awaiting_confirmation/null/false",
    otherWithAuthority: "unconfirmed/awaiting_confirmation/null/false",
    otherWithoutAuthority: "unconfirmed/licensing_authority_missing/null/false",
    notSure: "unconfirmed/licensing_not_sure/null/false",
    missing: "unconfirmed/licensing_not_provided/null/false",
  };
  for (const [name, want] of Object.entries(expected)) {
    const got = describe(await readiness(founders[name]));
    check("J-1", `licensing "${name}" alone confirms nothing (${want})`, got === want, got);
  }

  // Operator confirmations (the only way a jurisdiction becomes confirmed).
  const confirm = (founder, args) => fixtures.operator(["confirm-jurisdiction", "--company", founder.companyId, ...args]);
  const notSure = await confirm(founders.notSure, ["--jurisdiction", "uae_federal", "--licensing-location", "other"]);
  check("J-2", "an unresolved answer (not sure) cannot be confirmed: refused", notSure.outcome === "refused", JSON.stringify(notSure));
  const mismatch = await confirm(founders.difc, ["--jurisdiction", "difc", "--licensing-location", "other", "--licensing-authority", "Something else"]);
  check("J-3", "a confirmation must state the customer's current answer: mismatch refused", mismatch.outcome === "refused" && mismatch.code === "licensing_answer_mismatch", JSON.stringify(mismatch));
  check("J-4", "after the refusals nothing is confirmed", describe(await readiness(founders.notSure)) === expected.notSure && describe(await readiness(founders.difc)) === expected.difc);

  const confirmed = await confirm(founders.difc, ["--jurisdiction", "difc", "--licensing-location", "difc"]);
  const afterConfirm = await readiness(founders.difc);
  check("J-5", "an operator-confirmed supported jurisdiction is supported_confirmed and allows guidance", confirmed.code === 0 && describe(afterConfirm) === "supported_confirmed/confirmed/difc/true", describe(afterConfirm));
  const audited = await fixtures.ownerQuery(`SELECT jurisdiction, actor_kind FROM company_events WHERE company_id = ${quote(founders.difc.companyId)} AND event_type = 'jurisdiction_confirmed'`);
  check("J-6", "the confirmation is audited with the jurisdiction and the operator as actor", audited.length === 1 && audited[0][0] === "difc" && audited[0][1] === "operator");

  // The customer changes the answer: the confirmation is withdrawn at once.
  const changed = await apiFetch(`/companies/${founders.difc.companyId}/blueprint`, {
    method: "PATCH", token: founders.difc.token, body: { licensing: { location: "other", authority: "Example Free Zone Authority" } },
  });
  check("J-7", "changing a confirmed licensing answer withdraws the confirmation (guidance no longer allowed)",
    changed.status === 200 && describe(changed.json?.jurisdiction) === "unconfirmed/licensing_changed_since_confirmation/null/false", describe(changed.json?.jurisdiction));
  const restored = await apiFetch(`/companies/${founders.difc.companyId}/blueprint`, {
    method: "PATCH", token: founders.difc.token, body: { licensing: { location: "difc" } },
  });
  // Observed behaviour, recorded for review: the reviewed basis matches again.
  ctx.report.check("J-8", "reverting to the exact confirmed answer makes the earlier confirmation current again (by design: basis = current answer)",
    describe(restored.json?.jurisdiction) === "supported_confirmed/confirmed/difc/true", describe(restored.json?.jurisdiction));

  // A confirmed but unsupported jurisdiction never allows guidance.
  const adgm = await newFounder(ctx, "j-adgm", {
    company_name: "[SYNTHETIC E2E] J ADGM", blueprint: { licensing: { location: "other", authority: "Abu Dhabi Global Market" } },
  });
  const adgmConfirm = await confirm(adgm, ["--jurisdiction", "adgm", "--licensing-location", "other", "--licensing-authority", "Abu Dhabi Global Market"]);
  check("J-9", "a confirmed ADGM jurisdiction is unsupported and allows no guidance",
    adgmConfirm.code === 0 && describe(await readiness(adgm)) === "unsupported/jurisdiction_not_supported/adgm/false");
  ctx.jurisdictionFounders.adgm = adgm;

  // "Other" is never treated as UAE Federal / MOHRE without a confirmation.
  const [otherRow] = await fixtures.ownerQuery(`SELECT coalesce(employment_jurisdiction, '-') FROM company_blueprints WHERE company_id = ${quote(founders.otherWithAuthority.companyId)}`);
  check("J-10", "\"Other\" with an authority stores no employment jurisdiction (never UAE Federal by default)", otherRow[0] === "-");

  // A member never changes licensing, and the API never accepts readiness from a client.
  const forged = await apiFetch(`/companies/${founders.otherWithAuthority.companyId}/blueprint`, {
    method: "PATCH", token: founders.otherWithAuthority.token, body: { licensing: { location: "difc" }, guidance_allowed: true },
  });
  check("J-11", "a client cannot assert readiness or guidance (422)", forged.status === 422);
  const guidanceStates = await Promise.all(Object.values(ctx.jurisdictionFounders).map(readiness));
  check("J-12", "across all Companies, guidance_allowed is true only for supported_confirmed",
    guidanceStates.every((j) => j.guidance_allowed === (j.readiness === "supported_confirmed")));
}
