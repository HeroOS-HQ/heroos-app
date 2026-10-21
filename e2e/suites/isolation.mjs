// Phase D (API + database): two independent founders, cross-tenant attempts,
// RLS as the real runtime login, member vs administrator, revocation and
// demotion through the real operator procedure. Browser halves in browser.mjs.
import { randomUUID } from "node:crypto";

import { newFounder, quote } from "./common.mjs";

export async function run(ctx) {
  const { check, fixtures, apiFetch } = ctx;
  const alpha = await newFounder(ctx, "founder-alpha", {
    company_name: "[SYNTHETIC E2E] Alpha Co.",
    blueprint: { legal_name: "Alpha Holdings LLC", industry: "Retail", employee_count: 30, licensing: { location: "difc" } },
  });
  const beta = await newFounder(ctx, "founder-beta", {
    company_name: "[SYNTHETIC E2E] Beta Co.",
    blueprint: { legal_name: "Beta Private Ltd", industry: "Logistics", employee_count: 8, licensing: { location: "other", authority: "Example Free Zone Authority" } },
  });
  ctx.alpha = alpha;
  ctx.beta = beta;
  // Trusted fixture: one synthetic case per Company (cases have no write API yet).
  const alphaCase = randomUUID();
  const betaCase = randomUUID();
  await fixtures.ownerQuery(
    `INSERT INTO cases (id, company_id, case_type, title) VALUES
       (${quote(alphaCase)}, ${quote(alpha.companyId)}, 'probation', '[SYNTHETIC E2E] Alpha case'),
       (${quote(betaCase)}, ${quote(beta.companyId)}, 'probation', '[SYNTHETIC E2E] Beta case')`,
  );
  ctx.cases = { alpha: alphaCase, beta: betaCase };

  // --- discovery and cross-tenant reads/writes ----------------------------------
  const discA = await apiFetch("/me/companies", { token: alpha.token });
  const discB = await apiFetch("/me/companies", { token: beta.token });
  check("D-1", "founder A discovers only Alpha", discA.json?.length === 1 && discA.json[0].company_id === alpha.companyId);
  check("D-2", "founder B discovers only Beta", discB.json?.length === 1 && discB.json[0].company_id === beta.companyId);

  for (const [who, me, other] of [["A", alpha, beta], ["B", beta, alpha]]) {
    for (const path of ["", "/membership", "/blueprint", "/cases"]) {
      const res = await apiFetch(`/companies/${other.companyId}${path}`, { token: me.token });
      check("D-3", `${who} cannot read the other Company's ${path || "/ (company)"}: 403`, res.status === 403 && res.json?.detail === "Forbidden", res.status);
    }
    const otherBefore = await fixtures.ownerQuery(`SELECT legal_name, industry, updated_at FROM company_blueprints WHERE company_id = ${quote(other.companyId)}`);
    const patch = await apiFetch(`/companies/${other.companyId}/blueprint`, { method: "PATCH", token: me.token, body: { industry: "Hijacked" } });
    const otherAfter = await fixtures.ownerQuery(`SELECT legal_name, industry, updated_at FROM company_blueprints WHERE company_id = ${quote(other.companyId)}`);
    check("D-4", `${who} cannot modify the other Company's Blueprint (403, row unchanged)`, patch.status === 403 && JSON.stringify(otherBefore) === JSON.stringify(otherAfter));
    // M2-NEW-03: the primary contact must be a Membership of the caller's own Company.
    const mine = await fixtures.ownerQuery(`SELECT primary_contact_membership_id, website_url FROM company_blueprints WHERE company_id = ${quote(me.companyId)}`);
    const borrowed = await apiFetch(`/companies/${me.companyId}/blueprint`, { method: "PATCH", token: me.token, body: { primary_contact_membership_id: other.membershipId, website_url: "hijack.example" } });
    const nowhere = await apiFetch(`/companies/${me.companyId}/blueprint`, { method: "PATCH", token: me.token, body: { primary_contact_membership_id: randomUUID() } });
    const mineAfter = await fixtures.ownerQuery(`SELECT primary_contact_membership_id, website_url FROM company_blueprints WHERE company_id = ${quote(me.companyId)}`);
    check("D-4b", `${who} cannot make the other Company's member its primary contact (422 exactly like an unknown id; nothing saved)`,
      borrowed.status === 422 && borrowed.text === nowhere.text && JSON.stringify(mine) === JSON.stringify(mineAfter), borrowed.text);
    const own = (await apiFetch(`/companies/${me.companyId}/blueprint`, { token: me.token })).json;
    check("D-4c", `${who}'s Blueprint lists only its own people and contact`,
      own?.people?.length === 1 && own.people[0].membership_id === me.membershipId && own.primary_contact?.membership_id === me.membershipId && own.people[0].is_current_user === true,
      JSON.stringify(own?.people));
  }

  const otherCase = await apiFetch(`/companies/${alpha.companyId}/cases/${betaCase}`, { token: alpha.token });
  const noCase = await apiFetch(`/companies/${alpha.companyId}/cases/${randomUUID()}`, { token: alpha.token });
  check("D-5", "B's case id under A's own Company: 404, identical to an id that exists nowhere", otherCase.status === 404 && otherCase.text === noCase.text && !otherCase.text.includes("Beta"));
  const directCase = await apiFetch(`/companies/${beta.companyId}/cases/${betaCase}`, { token: alpha.token });
  check("D-6", "B's case through B's Company id, as A: 403", directCase.status === 403);
  const ownCases = await apiFetch(`/companies/${alpha.companyId}/cases`, { token: alpha.token });
  check("D-7", "A lists only Alpha's case", ownCases.json?.length === 1 && ownCases.json[0].id === alphaCase);

  const otherCompany = await apiFetch(`/companies/${beta.companyId}`, { token: alpha.token });
  const ghost = await apiFetch(`/companies/${randomUUID()}`, { token: alpha.token });
  check("D-8", "another Company's 403 is identical to a non-existent Company's (no existence oracle)", otherCompany.status === ghost.status && otherCompany.text === ghost.text);
  const nil = await apiFetch("/companies/00000000-0000-0000-0000-000000000000", { token: alpha.token });
  const malformed = await apiFetch("/companies/not-a-uuid'--", { token: alpha.token });
  check("D-9", "nil Company id: the same 403; malformed id: 422 without echoing it", nil.status === 403 && malformed.status === 422 && !malformed.text.includes("not-a-uuid"));

  // --- the database as the API's runtime login ------------------------------------
  const rt = (sql, company) => fixtures.runtimeQuery(sql, company ? { company } : {});
  const countsWithout = await rt("SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM company_blueprints), (SELECT count(*) FROM cases), (SELECT count(*) FROM memberships)");
  check("RLS-1", "runtime login without a tenant context sees no Company, Blueprint, case or Membership", countsWithout.ok && countsWithout.rows[0].every((v) => v === "0"), JSON.stringify(countsWithout));
  const scoped = await rt(`SELECT string_agg(DISTINCT company_id::text, ',') FROM (SELECT company_id FROM cases UNION ALL SELECT company_id FROM company_blueprints UNION ALL SELECT company_id FROM memberships UNION ALL SELECT id FROM companies) t`, beta.companyId);
  check("RLS-2", "with Beta as the transaction's tenant context, only Beta rows are visible (never Alpha's)", scoped.ok && scoped.rows[0][0] === beta.companyId, JSON.stringify(scoped));
  const leak = await fixtures.runtimeQuery(
    `SELECT count(*) FROM companies WHERE id = ${quote(alpha.companyId)}`,
    { company: beta.companyId },
  );
  check("RLS-3", "Alpha stays invisible even when queried by id under Beta's context", leak.ok && leak.rows[0][0] === "0");
  // Same session: set Beta's context, commit, then query in the next transaction.
  const noCarry = await fixtures.runtimeQuery("COMMIT; SELECT count(*) FROM companies", { company: beta.companyId });
  check("RLS-4", "a tenant context never outlives its transaction on the same connection (next transaction sees nothing)", noCarry.ok && noCarry.rows.at(-1)?.[0] === "0", JSON.stringify(noCarry));
  const writes = [
    ["insert a Company", "INSERT INTO companies (id, name) VALUES (gen_random_uuid(), 'x')"],
    ["insert a Membership", `INSERT INTO memberships (id, company_id, user_id, role) VALUES (gen_random_uuid(), ${quote(beta.companyId)}, gen_random_uuid(), 'company_admin')`],
    ["promote a Membership", `UPDATE memberships SET role = 'company_admin' WHERE company_id = ${quote(beta.companyId)}`],
    ["confirm a jurisdiction", `UPDATE company_blueprints SET employment_jurisdiction = 'difc' WHERE company_id = ${quote(beta.companyId)}`],
    ["create a User", "INSERT INTO users (id) VALUES (gen_random_uuid())"],
    ["bind an identity", `INSERT INTO user_identities (id, user_id, issuer, subject) VALUES (gen_random_uuid(), gen_random_uuid(), 'https://x.example/', 'x')`],
    ["delete a Company", `DELETE FROM companies WHERE id = ${quote(beta.companyId)}`],
    ["read registration records", "SELECT count(*) FROM company_registrations"],
    ["read the audit tables", "SELECT count(*) FROM company_events"],
  ];
  for (const [name, sql] of writes) {
    const result = await rt(sql, beta.companyId);
    // A statement that affects no row would also "succeed": only an error counts as refused.
    check("RLS-5", `runtime login cannot ${name}, even inside Beta's context`, !result.ok, result.ok ? `allowed: ${JSON.stringify(result.rows)}` : result.error);
  }
  const candidate = await apiFetch(`/companies/${beta.companyId}/blueprint`, { token: alpha.token });
  check("RLS-6", "the API's candidate context for Beta, set while checking A's Membership, grants A nothing (403)", candidate.status === 403);

  // --- member vs administrator, revocation and demotion (operator procedure) ------
  const memberSubject = ctx.subject("alpha-member");
  const provisioned = await fixtures.operator(["provision", "--company", alpha.companyId, "--issuer", ctx.issuer.issuer], memberSubject);
  check("D-10", "the operator provisions a member into Alpha (trusted procedure)", provisioned.code === 0 && provisioned.outcome === "created", JSON.stringify(provisioned));
  const memberToken = ctx.token(memberSubject);
  const memberDisc = await apiFetch("/me/companies", { token: memberToken });
  check("D-11", "the member discovers Alpha as member", memberDisc.json?.length === 1 && memberDisc.json[0].role === "member");
  const memberRead = await apiFetch(`/companies/${alpha.companyId}/blueprint`, { token: memberToken });
  const memberRole = await apiFetch(`/companies/${alpha.companyId}/membership`, { token: memberToken });
  check("D-12", "the member reads Alpha's information and is told it cannot update", memberRead.status === 200 && memberRole.json?.can_update_blueprint === false);
  const memberPatch = await apiFetch(`/companies/${alpha.companyId}/blueprint`, { method: "PATCH", token: memberToken, body: { industry: "Changed by member" } });
  check("D-13", "the member cannot PATCH the Blueprint (403)", memberPatch.status === 403);
  const adminPatch = await apiFetch(`/companies/${alpha.companyId}/blueprint`, { method: "PATCH", token: alpha.token, body: { industry: "Retail and wholesale" } });
  check("D-14", "the administrator can PATCH permitted fields (200, stored)", adminPatch.status === 200 && adminPatch.json?.industry === "Retail and wholesale");
  for (const [name, body] of [
    ["a role", { role: "company_admin" }],
    ["a Membership", { membership_id: provisioned.membership_id }],
    ["a jurisdiction confirmation", { employment_jurisdiction: "difc" }],
    ["a confirmation date", { jurisdiction_confirmed_at: "2026-01-01T00:00:00Z" }],
    ["the readiness", { jurisdiction: { readiness: "supported_confirmed" } }],
    ["the Company name", { company_name: "Renamed" }],
  ]) {
    const res = await apiFetch(`/companies/${alpha.companyId}/blueprint`, { method: "PATCH", token: alpha.token, body });
    check("D-15", `the administrator cannot set ${name} (422)`, res.status === 422);
  }
  const [jurisdiction] = await fixtures.ownerQuery(`SELECT coalesce(employment_jurisdiction, '-') FROM company_blueprints WHERE company_id = ${quote(alpha.companyId)}`);
  check("D-16", "no jurisdiction confirmation was written by those attempts", jurisdiction[0] === "-");

  // Promotion and demotion of a second member.
  const deputySubject = ctx.subject("alpha-deputy");
  const deputy = await fixtures.operator(["provision", "--company", alpha.companyId, "--issuer", ctx.issuer.issuer], deputySubject);
  const deputyToken = ctx.token(deputySubject);
  const promoted = await fixtures.operator(["set-role", "--company", alpha.companyId, "--membership", deputy.membership_id, "--role", "company_admin"]);
  const promotedPatch = await apiFetch(`/companies/${alpha.companyId}/blueprint`, { method: "PATCH", token: deputyToken, body: { employee_count: 31 } });
  check("D-17", "a member promoted by the operator can PATCH", promoted.code === 0 && promotedPatch.status === 200, JSON.stringify(promoted));
  const demoted = await fixtures.operator(["set-role", "--company", alpha.companyId, "--membership", deputy.membership_id, "--role", "member"]);
  const demotedPatch = await apiFetch(`/companies/${alpha.companyId}/blueprint`, { method: "PATCH", token: deputyToken, body: { employee_count: 32 } });
  const demotedRole = await apiFetch(`/companies/${alpha.companyId}/membership`, { token: deputyToken });
  check("D-18", "a demoted administrator loses write access at once (403), same token, no sign-out", demoted.code === 0 && demotedPatch.status === 403 && demotedRole.json?.role === "member");
  const roleEvents = await fixtures.ownerQuery(`SELECT count(*) FROM membership_events WHERE membership_id = ${quote(deputy.membership_id)} AND event_type = 'membership_role_changed'`);
  check("D-19", "both role changes are audited", roleEvents[0][0] === "2");

  // Revocation of the member: takes effect without sign-out.
  const revoked = await fixtures.operator(["revoke-membership", "--company", alpha.companyId, "--membership", provisioned.membership_id]);
  const afterDisc = await apiFetch("/me/companies", { token: memberToken });
  const afterRead = await apiFetch(`/companies/${alpha.companyId}/blueprint`, { token: memberToken });
  const afterWrite = await apiFetch(`/companies/${alpha.companyId}/blueprint`, { method: "PATCH", token: memberToken, body: { industry: "x" } });
  check("D-20", "after revocation (same, still valid token): discovery empty, reads and writes 403",
    revoked.code === 0 && afterDisc.status === 200 && afterDisc.json?.length === 0 && afterRead.status === 403 && afterWrite.status === 403);
  ctx.alphaMember = { subject: memberSubject, membershipId: provisioned.membership_id };
}
