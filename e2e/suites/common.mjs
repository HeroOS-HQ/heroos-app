// Helpers shared by the end-to-end suites.

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** POST /company-registrations straight to the API (as the web server's BFF does). */
export function register(ctx, token, body) {
  return ctx.apiFetch("/company-registrations", { method: "POST", token, body });
}

/** A founder: a fresh identity, its token and a registered Company. */
export async function newFounder(ctx, name, body = { company_name: `[SYNTHETIC E2E] ${name} Co.` }) {
  const subject = ctx.subject(name);
  const token = ctx.token(subject);
  const response = await register(ctx, token, body);
  if (response.status !== 201) throw new Error(`registration of ${name} answered ${response.status}`);
  return { name, subject, token, companyId: response.json.company_id, membershipId: response.json.membership_id };
}

const quote = (value) => `'${String(value).replace(/'/g, "''")}'`;

/** The binding, User and statuses for (issuer, subject), read as the owner. */
export async function identityFacts(ctx, subject) {
  const rows = await ctx.fixtures.ownerQuery(
    `SELECT i.id, i.status, u.id, u.status FROM user_identities i JOIN users u ON u.id = i.user_id
      WHERE i.issuer = ${quote(ctx.issuer.issuer)} AND i.subject = ${quote(subject)}`,
  );
  return rows.map(([identityId, identityStatus, userId, userStatus]) => ({ identityId, identityStatus, userId, userStatus }));
}

/** Row counts of the identity and tenancy tables (owner view). */
export async function counts(ctx) {
  const [row] = await ctx.fixtures.ownerQuery(
    `SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM users), (SELECT count(*) FROM user_identities),
            (SELECT count(*) FROM memberships), (SELECT count(*) FROM company_registrations),
            (SELECT count(*) FROM company_blueprints)`,
  );
  const [companies, users, identities, memberships, registrations, blueprints] = row.map(Number);
  return { companies, users, identities, memberships, registrations, blueprints };
}

export const sameCounts = (a, b) => JSON.stringify(a) === JSON.stringify(b);

export { quote };

/**
 * Opens the case page's folded "Full case details" (progress, the jurisdiction's
 * basis, facts, missing information) as a person would, by its summary; does
 * nothing if it is already open.
 */
export async function openFullCaseDetails(page) {
  await page.eval(`(() => { const d = document.getElementById("case-full-details"); if (d && !d.open) d.querySelector("summary").click(); return true; })()`);
  await page.waitFor(`document.getElementById("case-full-details")?.open === true`, { message: "full case details open" });
}
