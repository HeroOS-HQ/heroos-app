// Phase C (API + database): founder self-registration scenarios R1-R8 through
// the real API process, verified in the database as its owner. The browser
// halves of R1, R4 and R7 are in browser.mjs.
import { counts, identityFacts, quote, register, sameCounts, UUID } from "./common.mjs";

export async function run(ctx) {
  const { check, fixtures, apiFetch } = ctx;

  // --- R1: a new founder ------------------------------------------------------
  const subject = ctx.subject("r1-founder");
  const token = ctx.token(subject);
  const before = await counts(ctx);
  const created = await register(ctx, token, {
    company_name: "[SYNTHETIC E2E] R1 Founder Co.",
    blueprint: { legal_name: "R1 Founder Trading LLC", industry: "Hospitality", employee_count: 12, licensing: { location: "difc" } },
  });
  check("R1-1", "a new founder registers: 201 created, company_admin", created.status === 201 && created.json?.outcome === "created" && created.json?.role === "company_admin" && UUID.test(created.json?.company_id ?? ""), created.text);
  const companyId = created.json?.company_id;
  const facts = await identityFacts(ctx, subject);
  check("R1-2", "exactly one identity binding, active, on a new active User", facts.length === 1 && facts[0].identityStatus === "active" && facts[0].userStatus === "active");
  const [company] = await fixtures.ownerQuery(`SELECT name FROM companies WHERE id = ${quote(companyId)}`);
  check("R1-3", "the Company exists with the submitted name", company?.[0] === "[SYNTHETIC E2E] R1 Founder Co.");
  const [blueprint] = await fixtures.ownerQuery(
    `SELECT legal_name, industry, employee_count, licensing_location, coalesce(employment_jurisdiction, '-') FROM company_blueprints WHERE company_id = ${quote(companyId)}`,
  );
  check("R1-4", "its Blueprint holds the onboarding answers, with no jurisdiction confirmed", JSON.stringify(blueprint) === JSON.stringify(["R1 Founder Trading LLC", "Hospitality", "12", "difc", "-"]), JSON.stringify(blueprint));
  const memberships = await fixtures.ownerQuery(`SELECT user_id, role, status FROM memberships WHERE company_id = ${quote(companyId)}`);
  check("R1-5", "exactly one Membership: the founder, company_admin, active", memberships.length === 1 && memberships[0][0] === facts[0]?.userId && memberships[0][1] === "company_admin" && memberships[0][2] === "active", JSON.stringify(memberships));
  const registrations = await fixtures.ownerQuery(`SELECT identity_id, user_id, membership_id FROM company_registrations WHERE company_id = ${quote(companyId)}`);
  check("R1-6", "one self-registration record links identity, User, Company and Membership", registrations.length === 1 && registrations[0][0] === facts[0]?.identityId && registrations[0][2] === created.json?.membership_id);
  const [contact] = await fixtures.ownerQuery(`SELECT primary_contact_membership_id FROM company_blueprints WHERE company_id = ${quote(companyId)}`);
  check("R1-6b", "the founder's own Membership is the Blueprint's first primary contact (set by the server, never by the request)", contact?.[0] === created.json?.membership_id, JSON.stringify(contact));
  const events = await fixtures.ownerQuery(`SELECT event_type, actor_kind, actor_reference FROM company_events WHERE company_id = ${quote(companyId)}`);
  check("R1-7", "the registration is audited (company_registered, actor api, registration reference)", events.length === 1 && events[0][0] === "company_registered" && events[0][1] === "api" && /^registration:[0-9a-f-]{36}$/.test(events[0][2]), JSON.stringify(events));
  const after = await counts(ctx);
  check("R1-8", "nothing else was created (one Company, Blueprint, User, binding, Membership, registration)",
    after.companies - before.companies === 1 && after.blueprints - before.blueprints === 1 && after.users - before.users === 1 &&
    after.identities - before.identities === 1 && after.memberships - before.memberships === 1 && after.registrations - before.registrations === 1);
  const discovery = await apiFetch("/me/companies", { token });
  check("R1-9", "workspace discovery lists exactly the new Company, as company_admin", discovery.status === 200 && discovery.json?.length === 1 && discovery.json[0].company_id === companyId && discovery.json[0].role === "company_admin");
  const membership = await apiFetch(`/companies/${companyId}/membership`, { token });
  const workspace = await apiFetch(`/companies/${companyId}`, { token });
  check("R1-10", "the workspace is accessible and the founder may update the Blueprint", workspace.status === 200 && membership.json?.can_update_blueprint === true);

  // --- R2: double submission ---------------------------------------------------
  const again = await register(ctx, token, { company_name: "[SYNTHETIC E2E] R1 Founder Co." });
  check("R2-1", "a second submission returns 200 existing with the same Company", again.status === 200 && again.json?.outcome === "existing" && again.json?.company_id === companyId);
  check("R2-2", "still exactly one registration for the founder", sameCounts(await counts(ctx), after));

  // --- R3: concurrent submissions for one identity ------------------------------
  const r3Subject = ctx.subject("r3-concurrent");
  const r3Token = ctx.token(r3Subject);
  const r3Before = await counts(ctx);
  const burst = await Promise.all(
    Array.from({ length: 8 }, (_, i) => register(ctx, r3Token, { company_name: `[SYNTHETIC E2E] R3 Burst ${i}` })),
  );
  const statuses = burst.map((r) => r.status).sort();
  const ids = new Set(burst.map((r) => r.json?.company_id));
  check("R3-1", "8 concurrent submissions: exactly one 201, seven 200 existing, one Company id", statuses.filter((s) => s === 201).length === 1 && statuses.filter((s) => s === 200).length === 7 && ids.size === 1, statuses.join(","));
  const r3After = await counts(ctx);
  check("R3-2", "one Company, one registration, one Membership, one User and binding were created", r3After.companies - r3Before.companies === 1 && r3After.registrations - r3Before.registrations === 1 && r3After.memberships - r3Before.memberships === 1 && r3After.users - r3Before.users === 1 && r3After.identities - r3Before.identities === 1);
  const r3Admins = await fixtures.ownerQuery(`SELECT count(*) FROM memberships WHERE company_id = ${quote([...ids][0])} AND role = 'company_admin'`);
  check("R3-3", "no duplicate administrator grant", r3Admins[0][0] === "1");
  const winner = burst.find((r) => r.status === 201)?.json;
  const [storedName] = await fixtures.ownerQuery(`SELECT name FROM companies WHERE id = ${quote(winner?.company_id)}`);
  check("R3-4", "the stored name is the winning submission's", burst.some((r) => r.status === 201 && storedName?.[0]?.startsWith("[SYNTHETIC E2E] R3 Burst")));

  // --- R4 (API half): a retry after a lost response --------------------------------
  // The first request completed on the server; the client never saw the answer
  // and retries, possibly with edited details. The retry must change nothing.
  const r4Subject = ctx.subject("r4-retry");
  const r4Token = ctx.token(r4Subject);
  const r4First = await register(ctx, r4Token, { company_name: "[SYNTHETIC E2E] R4 Original", blueprint: { legal_name: "R4 Original LLC" } });
  const r4Retry = await register(ctx, r4Token, { company_name: "[SYNTHETIC E2E] R4 Edited", blueprint: { legal_name: "R4 Edited LLC", licensing: { location: "not_sure" } } });
  const [r4Row] = await fixtures.ownerQuery(
    `SELECT c.name, b.legal_name, coalesce(b.licensing_location, '-') FROM companies c JOIN company_blueprints b ON b.company_id = c.id WHERE c.id = ${quote(r4First.json?.company_id)}`,
  );
  check("R4-1", "the retry returns the existing Company (200 existing)", r4Retry.status === 200 && r4Retry.json?.outcome === "existing" && r4Retry.json?.company_id === r4First.json?.company_id);
  check("R4-2", "the retried (edited) details were not applied: the first submission's data stands", JSON.stringify(r4Row) === JSON.stringify(["[SYNTHETIC E2E] R4 Original", "R4 Original LLC", "-"]), JSON.stringify(r4Row));

  // --- R5: another login binding of the same person --------------------------------
  // A User has at most one active binding per issuer, so a second login means
  // a second provider (e.g. Auth0 now, Cognito at M5). Simulated with a second
  // local provider and an API switched over to it, as an M5 cut-over would.
  const r5Primary = ctx.subject("r5-primary");
  const r5Token = ctx.token(r5Primary);
  const r5 = await register(ctx, r5Token, { company_name: "[SYNTHETIC E2E] R5 Co." });
  const [r5Facts] = await identityFacts(ctx, r5Primary);
  const sameIssuer = await fixtures.operator(["bind-identity", "--user", r5Facts.userId, "--issuer", ctx.issuer.issuer], ctx.subject("r5-same-issuer"));
  check("R5-0", "a second active binding under the same issuer is refused by the operator procedure", sameIssuer.outcome === "refused" && sameIssuer.code === "active_identity_exists_for_issuer", JSON.stringify(sameIssuer));
  const second = ctx.secondIssuer;
  const r5Second = ctx.subject("r5-second-provider");
  const bound = await fixtures.operator(["bind-identity", "--user", r5Facts.userId, "--issuer", second.issuer], r5Second);
  check("R5-1", "the operator binds an identity from a second provider to the same User (trusted procedure)", bound.code === 0 && bound.outcome === "created", JSON.stringify(bound));
  await ctx.api.stop();
  await ctx.api.start({ extraEnv: { HEROOS_OIDC_ISSUER: second.issuer } });
  const r5SecondToken = second.accessToken(r5Second);
  ctx.issuedTokens.push(r5SecondToken);
  const r5Again = await register(ctx, r5SecondToken, { company_name: "[SYNTHETIC E2E] R5 Second Co." });
  const r5Discovery = await apiFetch("/me/companies", { token: r5SecondToken });
  const r5OldIssuer = await apiFetch("/me/companies", { token: r5Token });
  await ctx.api.stop();
  await ctx.api.start();
  check("R5-2", "registering through the second provider returns the same Company (no second self-registration)", r5Again.status === 200 && r5Again.json?.outcome === "existing" && r5Again.json?.company_id === r5.json?.company_id, r5Again.text);
  check("R5-3", "the second login discovers the same workspace", r5Discovery.json?.length === 1 && r5Discovery.json[0].company_id === r5.json?.company_id);
  check("R5-4", "the API trusts only its configured issuer (the first provider's token is refused while switched)", r5OldIssuer.status === 401);
  const r5Registrations = await fixtures.ownerQuery(`SELECT count(*) FROM company_registrations WHERE user_id = ${quote(r5Facts.userId)}`);
  check("R5-5", "one registration for that User", r5Registrations[0][0] === "1");
  // Same e-mail claim, different subjects: never linked.
  const mailA = ctx.subject("r5-mail-a");
  const mailB = ctx.subject("r5-mail-b");
  const email = { email: "same.person@example.test", email_verified: true };
  const regA = await register(ctx, ctx.token(mailA, { overrides: email }), { company_name: "[SYNTHETIC E2E] R5 Mail A" });
  const regB = await register(ctx, ctx.token(mailB, { overrides: email }), { company_name: "[SYNTHETIC E2E] R5 Mail B" });
  const [factsA] = await identityFacts(ctx, mailA);
  const [factsB] = await identityFacts(ctx, mailB);
  check("R5-6", "identities with the same e-mail claim are separate Users with separate Companies (no e-mail linking)",
    regA.status === 201 && regB.status === 201 && regA.json.company_id !== regB.json.company_id && factsA.userId !== factsB.userId);

  // --- R6: invalid or privileged payloads ----------------------------------------
  const r6Token = ctx.token(ctx.subject("r6-attacker"));
  const victim = r1Context();
  function r1Context() {
    return { companyId, userId: facts[0]?.userId, membershipId: created.json?.membership_id };
  }
  const r6Before = await counts(ctx);
  const bodies = [
    ["another user id", { company_name: "X", user_id: victim.userId }],
    ["an existing Company id", { company_name: "X", company_id: victim.companyId }],
    ["an explicit administrator", { company_name: "X", administrator_id: victim.userId }],
    ["a role", { company_name: "X", role: "company_admin" }],
    ["an issuer override", { company_name: "X", issuer: "https://evil.example/" }],
    ["a subject override", { company_name: "X", subject: ctx.subject("r1-founder") }],
    ["a membership id", { company_name: "X", membership_id: victim.membershipId }],
    ["a jurisdiction confirmation in the Blueprint", { company_name: "X", blueprint: { employment_jurisdiction: "difc" } }],
    ["a confirmation timestamp", { company_name: "X", blueprint: { jurisdiction_confirmed_at: "2026-01-01T00:00:00Z" } }],
    ["readiness fields", { company_name: "X", blueprint: { jurisdiction: { readiness: "supported_confirmed", guidance_allowed: true } } }],
    ["confirmed licensing basis", { company_name: "X", blueprint: { licensing: { location: "difc", confirmed: true } } }],
    ["an authority without Other", { company_name: "X", blueprint: { licensing: { location: "difc", authority: "DIFC Authority" } } }],
    ["an unknown top-level field", { company_name: "X", plan: "enterprise" }],
    ["a name with surrounding spaces", { company_name: " X " }],
    ["a name with a control character", { company_name: "X\u0007Y" }],
    ["a name over 200 characters", { company_name: "X".repeat(201) }],
    ["a string employee count (strict types)", { company_name: "X", blueprint: { employee_count: "12" } }],
    ["a negative employee count", { company_name: "X", blueprint: { employee_count: -1 } }],
  ];
  for (const [name, body] of bodies) {
    const res = await register(ctx, r6Token, body);
    const echoed = [victim.userId, victim.companyId, victim.membershipId].some((id) => id && res.text.includes(id));
    check("R6-1", `rejected: ${name} (422, nothing echoed)`, res.status === 422 && !echoed, `status ${res.status}`);
  }
  check("R6-2", "rejected payloads created and changed nothing", sameCounts(await counts(ctx), r6Before));
  const victimMembership = await fixtures.ownerQuery(`SELECT role, status FROM memberships WHERE company_id = ${quote(victim.companyId)}`);
  check("R6-3", "the victim Company still has only its founder as administrator", victimMembership.length === 1 && victimMembership[0][0] === "company_admin");
  const malformed = await apiFetch("/company-registrations", { method: "POST", token: r6Token, body: "{not json" });
  check("R6-4", "malformed JSON: 422", malformed.status === 422);

  // --- R7: registration disabled ---------------------------------------------------
  await ctx.api.stop();
  await ctx.api.start({ selfRegistration: false });
  const r7Before = await counts(ctx);
  const disabled = await register(ctx, ctx.token(ctx.subject("r7-new")), { company_name: "[SYNTHETIC E2E] R7 Co." });
  check("R7-1", "with HEROOS_SELF_REGISTRATION_ENABLED=false registration answers 404", disabled.status === 404 && disabled.json?.detail === "Not found");
  check("R7-2", "nothing was created while disabled", sameCounts(await counts(ctx), r7Before));
  const stillWorks = await apiFetch("/me/companies", { token });
  check("R7-3", "existing founders still reach their workspace while registration is disabled", stillWorks.status === 200 && stillWorks.json?.length === 1);
  await ctx.api.stop();
  await ctx.api.start({ selfRegistration: true });

  // --- R8: account lifecycle ---------------------------------------------------------
  const lifecycle = async (label, change) => {
    const s = ctx.subject(`r8-${label}`);
    const t = ctx.token(s);
    const reg = await register(ctx, t, { company_name: `[SYNTHETIC E2E] R8 ${label}` });
    const [f] = await identityFacts(ctx, s);
    const result = await change({ ...f, companyId: reg.json.company_id, membershipId: reg.json.membership_id });
    const beforeRetry = await counts(ctx);
    const retry = await register(ctx, t, { company_name: `[SYNTHETIC E2E] R8 ${label} again` });
    const disc = await apiFetch("/me/companies", { token: t });
    const read = await apiFetch(`/companies/${reg.json.company_id}`, { token: t });
    const write = await apiFetch(`/companies/${reg.json.company_id}/blueprint`, { method: "PATCH", token: t, body: { industry: "Retail" } });
    return { result, retry, disc, read, write, unchanged: sameCounts(await counts(ctx), beforeRetry) };
  };
  const revokedIdentity = await lifecycle("revoked-identity", (f) => fixtures.operator(["revoke-identity", "--identity", f.identityId]));
  check("R8-1", "revoked identity: the operator revocation succeeds", revokedIdentity.result.code === 0, JSON.stringify(revokedIdentity.result));
  check("R8-2", "revoked identity: re-registration refused (403), nothing created", revokedIdentity.retry.status === 403 && revokedIdentity.unchanged);
  check("R8-3", "revoked identity: discovery, reads and writes denied (403)", [revokedIdentity.disc, revokedIdentity.read, revokedIdentity.write].every((r) => r.status === 403));

  const suspended = await lifecycle("suspended-user", (f) => fixtures.operator(["suspend-user", "--user", f.userId]));
  check("R8-4", "suspended User: the operator suspension succeeds", suspended.result.code === 0, JSON.stringify(suspended.result));
  check("R8-5", "suspended User: re-registration refused (403), nothing created", suspended.retry.status === 403 && suspended.unchanged);
  check("R8-6", "suspended User: discovery, reads and writes denied (403)", [suspended.disc, suspended.read, suspended.write].every((r) => r.status === 403));

  const revokedMembership = await lifecycle("revoked-membership", (f) =>
    fixtures.operator(["revoke-membership", "--company", f.companyId, "--membership", f.membershipId]),
  );
  check("R8-7", "revoked registered Membership: the operator revocation succeeds", revokedMembership.result.code === 0, JSON.stringify(revokedMembership.result));
  check("R8-8", "revoked registered Membership: re-registration refused (403), no new Company", revokedMembership.retry.status === 403 && revokedMembership.unchanged);
  check("R8-9", "revoked registered Membership: no workspace listed (200 []), reads and writes 403",
    revokedMembership.disc.status === 200 && revokedMembership.disc.json?.length === 0 && revokedMembership.read.status === 403 && revokedMembership.write.status === 403);

  // A founder later demoted by the operator, who submits onboarding again: the
  // answer must state the role actually held, never re-assert administration.
  const demotedSubject = ctx.subject("r8-demoted-founder");
  const demotedToken = ctx.token(demotedSubject);
  const demotedReg = await register(ctx, demotedToken, { company_name: "[SYNTHETIC E2E] R8 demoted" });
  const demotedSet = await fixtures.operator(["set-role", "--company", demotedReg.json.company_id, "--membership", demotedReg.json.membership_id, "--role", "member"]);
  const demotedRetry = await register(ctx, demotedToken, { company_name: "[SYNTHETIC E2E] R8 demoted again" });
  const demotedRole = await apiFetch(`/companies/${demotedReg.json.company_id}/membership`, { token: demotedToken });
  check("R8-10", "a demoted founder re-submitting onboarding gets 200 existing with the role actually held (member), not company_admin",
    demotedSet.code === 0 && demotedRetry.status === 200 && demotedRetry.json?.outcome === "existing" &&
    demotedRetry.json?.role === demotedRole.json?.role && demotedRole.json?.role === "member", `answer role ${demotedRetry.json?.role}, actual ${demotedRole.json?.role}`);

  ctx.r1 = { subject, token, companyId, userId: facts[0]?.userId, membershipId: created.json?.membership_id };
}
