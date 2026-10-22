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
 * Opens the case status (M2-NEW-02: the slide-over from the case's name in the
 * header) as a person would; does nothing if it is already open.
 */
export async function openCaseStatus(page) {
  await page.waitForHydrated('button[aria-haspopup="dialog"][aria-label$="Case status"]');
  await page.eval(`(() => { if (!document.getElementById("case-status")) document.querySelector('button[aria-haspopup="dialog"][aria-label$="Case status"]').click(); return true; })()`);
  await page.waitFor(`Boolean(document.getElementById("case-status"))`, { message: "case status open" });
}

/** Closes the case status (Escape, as a person would). */
export async function closeCaseStatus(page) {
  await page.press("Escape");
  await page.waitFor(`!document.getElementById("case-status")`, { message: "case status closed" });
}

/**
 * Opens the case's folded "Full case details" (progress, the jurisdiction's
 * basis, facts, missing information), inside the case status, as a person
 * would, by its summary; does nothing if it is already open.
 */
export async function openFullCaseDetails(page) {
  await openCaseStatus(page);
  await page.eval(`(() => { const d = document.getElementById("case-full-details"); if (d && !d.open) d.querySelector("summary").click(); return true; })()`);
  await page.waitFor(`document.getElementById("case-full-details")?.open === true`, { message: "full case details open" });
}

/**
 * Unfolds the case's "Case details" (M2-NEW-08: the Case is chat-first, so its
 * structured answers are secondary, folded until asked for) as a person would,
 * by its button; does nothing if they are already open.
 */
export async function openCaseDetails(page) {
  await page.waitForHydrated('button[aria-controls="case-details-body"]');
  await page.eval(`(() => { const b = document.querySelector('button[aria-controls="case-details-body"]'); if (b.getAttribute("aria-expanded") !== "true") b.click(); return true; })()`);
  await page.waitFor(`Boolean(document.getElementById("case-details-body"))`, { message: "case details open" });
}

/** Opens the account menu (M2-NEW-02: the way to the Blueprint, Company Space, another workspace and sign out). */
export async function openAccountMenu(page) {
  await page.waitForHydrated('button[aria-label^="Account menu"]');
  await page.eval(`(() => { const b = document.querySelector('button[aria-label^="Account menu"]'); if (b.getAttribute("aria-expanded") !== "true") b.click(); return true; })()`);
  await page.waitFor(`[...document.querySelectorAll("button")].some((b) => b.offsetParent !== null && b.textContent.trim() === "Sign out")`, { message: "account menu open" });
}

/** Signs out from the account menu (M2-NEW-02: the header's only way to the account). */
export async function signOutFromMenu(page) {
  await openAccountMenu(page);
  await page.clickText("button", "Sign out");
}
