// Phases C/D/E/G/I/J in a real browser against the real stack: the founder
// journey through the hosted sign-up, retries and lost responses, disabled
// registration, lifecycle denials, tenant isolation by URL, stale UI after
// revocation, switching, logout, jurisdiction display, responsive layout,
// accessibility checks and the CSP investigation.
import { counts, identityFacts, newFounder, openAccountMenu, quote, sameCounts, signOutFromMenu } from "./common.mjs";

const WIDTHS = [320, 375, 390, 768, 1024, 1440];

/** Records CSP violations and the life of React's hidden streaming containers. */
const CSP_PROBE = `(() => {
  window.__csp = [];
  window.__containers = [];
  let frames = 0;
  const tick = () => { frames += 1; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  document.addEventListener("securitypolicyviolation", (e) => {
    window.__csp.push({ directive: e.violatedDirective, sample: e.sample, blocked: e.blockedURI, line: e.lineNumber });
  });
  new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (node.nodeType === 1 && /^S:/.test(node.id || "")) {
          const box = node.getBoundingClientRect();
          window.__containers.push({ id: node.id, tag: node.tagName, framesAtInsert: frames, width: box.width, height: box.height, hiddenAttr: node.hasAttribute("hidden"), content: node.tagName.toLowerCase() === "svg" ? node.innerHTML.slice(0, 160) : undefined });
        }
      }
      for (const node of record.removedNodes) {
        if (node.nodeType === 1 && /^S:/.test(node.id || "")) {
          const entry = window.__containers.find((c) => c.id === node.id && c.framesAtRemove === undefined);
          if (entry) entry.framesAtRemove = frames;
        }
      }
    }
  }).observe(document, { childList: true, subtree: true });
})();`;

export async function run(ctx) {
  const { check, fixtures, webOrigin } = ctx;
  const shot = (page, name) => ctx.screenshot(page, name);
  const pages = [];
  const open = async () => {
    const page = await ctx.newPage();
    await page.addInitScript(CSP_PROBE);
    pages.push(page);
    return page;
  };
  const withSession = async (page, token) => {
    const value = ctx.session(token);
    await page.setCookie({ name: "__Host-heroos-session", value, url: webOrigin, path: "/", secure: true, httpOnly: true, sameSite: "Lax" });
  };
  const visible = (page, text) => page.eval(`document.body.innerText.includes(${JSON.stringify(text)})`);

  // Onboarding opens on Welcome (a presentation that sends nothing); "Get Started" opens Company Basics.
  // A page already past Welcome (e.g. after a validation check) carries on where it is.
  async function startOnboarding(page) {
    await page.waitFor(`document.getElementById("onboarding-start") || document.getElementById("company-name")`, { message: "onboarding" });
    if (await page.eval(`Boolean(document.getElementById("onboarding-start"))`)) {
      await page.waitForHydrated("#onboarding-start");
      await page.click("#onboarding-start");
    }
    await page.waitForHydrated("#company-name");
  }

  // Company Basics, then About Your Company (M2-NEW-03, all optional), then Jurisdiction.
  async function passAboutStep(page, { website, summary, policies } = {}) {
    await page.waitFor(`document.getElementById("website-url")`, { message: "about-your-company step" });
    if (website) await page.type("#website-url", website);
    if (summary) await page.type("#company-summary", summary);
    if (policies) await page.click(`#onboarding-policies-${policies}`);
    await page.clickText("button", "Continue");
    await page.waitFor(`document.getElementById("onboarding-location-difc")`, { message: "jurisdiction step" });
  }

  async function fillWizard(page, { name, legal, industry, employees, website, summary, policies, location, authority }) {
    await startOnboarding(page);
    await page.type("#company-name", name);
    if (legal) await page.type("#legal-name", legal);
    if (industry) await page.type("#industry", industry);
    if (employees) await page.type("#employee-count", employees);
    await page.clickText("button", "Continue");
    await passAboutStep(page, { website, summary, policies });
    await page.click(`#onboarding-location-${location}`);
    if (authority) {
      await page.waitFor(`document.getElementById("onboarding-authority")`);
      await page.type("#onboarding-authority", authority);
    }
    await page.clickText("button", "Continue");
    await page.waitForText("Review your company information");
  }

  // ===== R1 in the browser: hosted sign-up -> onboarding -> workspace -> settings =====
  const founderSubject = ctx.subject("ui-founder");
  const page = await open();
  await page.viewport(390, 844);
  await page.goto(`${webOrigin}/`);
  await page.waitForText("Get started");
  const getStarted = await page.eval(`[...document.querySelectorAll("a")].filter((a) => a.innerText.trim().startsWith("Get started")).map((a) => a.getAttribute("href"))`);
  check("UI-1", "homepage \"Get started\" leads to the hosted sign-up", getStarted.length > 0 && getStarted.every((h) => h === "/auth/signup"), JSON.stringify(getStarted));
  await page.clickText("a", "Get started");
  await page.waitFor(`location.origin === ${JSON.stringify(ctx.issuer.origin)} && document.getElementById("heading")`, { message: "hosted page" });
  check("UI-2", "the provider shows its sign-up screen (screen_hint=signup reached it)", (await page.eval(`document.getElementById("heading").innerText`)) === "Create your account");
  await page.type("#subject", founderSubject);
  await page.click("#continue");
  await page.waitFor(`location.pathname === "/onboarding"`, { message: "landing on /onboarding" });
  check("UI-3", "after sign-up the founder lands on /onboarding (no workspace was created by signing in)", (await identityFacts(ctx, founderSubject)).length === 0);
  await page.waitForText("Welcome to HeroOS");
  await shot(page, "r1-onboarding-welcome-390");
  await startOnboarding(page);
  check("UI-3b", "onboarding opens on Welcome, and Get Started opens Company Basics without sending anything",
    page.network.filter((r) => r.url.includes("/bff/") && r.method !== "GET").length === 0 &&
      (await page.eval(`document.querySelector('[aria-current="step"]')?.textContent ?? ""`)) === "2Company Basics");
  await shot(page, "r1-onboarding-step1-390");
  await page.clickText("button", "Continue");
  await page.waitForText("Enter your company name");
  // The wizard shows the error at once and moves focus on the next animation
  // frame (requestAnimationFrame): wait for focus instead of sampling it, which
  // raced on slower CI runners.
  const focusedName = await page
    .waitFor(`document.activeElement?.id === "company-name"`, { timeout: 2_000, message: "focus on the company name" })
    .then(() => true, () => false);
  check("UI-4", "validation: an empty company name is refused next to the field, focus on it", focusedName,
    await page.eval("document.activeElement?.id ?? 'none'"));
  await shot(page, "validation-error-390");
  await fillWizard(page, {
    name: "[SYNTHETIC E2E] UI Founder Co.",
    legal: "UI Founder Trading LLC",
    industry: "Hospitality",
    employees: "14",
    website: "WWW.UI-Founder.example/",
    summary: "Two fictional cafés. A manager leads twelve staff.",
    policies: "yes",
    location: "other",
    authority: "Example Free Zone Authority",
  });
  const reviewText = await page.text();
  check("UI-4b", "the review shows exactly what will be stored: the normalized website, the summary, the policies answer and the founder as primary contact",
    reviewText.includes("https://www.ui-founder.example") && reviewText.includes("Two fictional cafés. A manager leads twelve staff.") &&
      reviewText.includes("Yes, the company has HR policies") && reviewText.includes("as the person creating this workspace"));
  await shot(page, "r1-review-390");
  await page.viewport(1440, 900);
  await shot(page, "r1-review-1440");
  await page.viewport(390, 844);
  const beforeCreate = await counts(ctx);
  // Click as the founder: after real typing the browser shows a "Leave site?"
  // prompt if the page still guards its draft when it leaves; answered with
  // Cancel, that prompt left the page locked on "Opening your workspace…".
  const dialogsBefore = page.dialogs.length;
  await page.clickText("button", "Create my workspace", { asUser: true });
  await page.waitForText("Your workspace is ready");
  const prompts = page.dialogs.slice(dialogsBefore);
  check("UI-5a", "\"Create my workspace\" opens the workspace with no \"Leave site?\" prompt", prompts.length === 0,
    JSON.stringify(prompts));
  const readyUrl = new URL(page.url);
  const [facts] = await identityFacts(ctx, founderSubject);
  const companyId = readyUrl.pathname.split("/")[2];
  const [stored] = await fixtures.ownerQuery(
    `SELECT c.name, b.legal_name, b.industry, b.employee_count, b.licensing_location, b.licensing_authority, m.role,
            b.website_url, b.company_summary, b.policies_exist, (b.primary_contact_membership_id = m.id)::text
       FROM companies c JOIN company_blueprints b ON b.company_id = c.id JOIN memberships m ON m.company_id = c.id
      WHERE c.id = ${quote(companyId)} AND m.user_id = ${quote(facts?.userId)}`,
  );
  check("UI-5", "\"Create my workspace\" created exactly what the founder entered (the canonical Blueprint values), with the founder as company_admin and primary contact",
    JSON.stringify(stored) === JSON.stringify([
      "[SYNTHETIC E2E] UI Founder Co.", "UI Founder Trading LLC", "Hospitality", "14", "other", "Example Free Zone Authority", "company_admin",
      "https://www.ui-founder.example", "Two fictional cafés. A manager leads twelve staff.", "yes", "true",
    ]), JSON.stringify(stored));
  check("UI-6", "exactly one Company and Membership were created by the journey", (await counts(ctx)).companies - beforeCreate.companies === 1);
  await shot(page, "r1-ready-390");
  await page.clickText("a", "Open my workspace");
  await page.waitForText("What can HR do for you today?");
  await shot(page, "r1-workspace-390");
  await openAccountMenu(page);
  const company = (await visible(page, "[SYNTHETIC E2E] UI Founder Co.")) && (await visible(page, "Administrator"));
  await page.clickText("a", "Company Blueprint");
  await page.waitForHydrated("#edit-blueprint");
  check("UI-7", "the workspace names the Company and the administrator role, and the Blueprint says the jurisdiction is waiting to be confirmed",
    company && (await visible(page, "waiting to be confirmed")));
  await page.click("#edit-blueprint");
  await page.waitForHydrated("#bp-industry");
  await page.type("#bp-industry", "Hospitality and events");
  await shot(page, "r1-blueprint-unsaved-390");
  await page.clickText("button", "Save changes");
  await page.waitForText("Company Blueprint updated");
  const industry = await fixtures.ownerValue(`SELECT industry FROM company_blueprints WHERE company_id = ${quote(companyId)}`);
  check("UI-8", "settings: the administrator's change is saved through the BFF and the API", industry === "Hospitality and events");
  await shot(page, "r1-settings-saved-390");

  // ===== M2-NEW-03: onboarding -> Company Blueprint -> edit an optional detail -> reload =====
  const blueprintUrl = `${webOrigin}/workspaces/${companyId}/settings`;
  const blueprintText = await page.text();
  check("BP-1", "the Blueprint shows the onboarding values: the website, the summary, the policies answer and the founder as primary contact (\"You\")",
    blueprintText.includes("https://www.ui-founder.example") && blueprintText.includes("Two fictional cafés. A manager leads twelve staff.") &&
      blueprintText.includes("Yes, the company has HR policies") && /Primary contact\s*You/.test(blueprintText));
  const jurisdictionBefore = await fixtures.ownerQuery(
    `SELECT licensing_location, licensing_authority, coalesce(employment_jurisdiction, '-') FROM company_blueprints WHERE company_id = ${quote(companyId)}`,
  );
  await page.click("#edit-blueprint");
  await page.waitForHydrated("#bp-hr-external");
  await page.click("#bp-hr-external");
  await page.type("#bp-hr-notes", "A fictional HR consultant helps with contracts.");
  await shot(page, "bp-edit-hr-390");
  await page.clickText("button", "Save changes");
  await page.waitForText("Company Blueprint updated");
  const savedNotice = await page.text();
  await shot(page, "bp-saved-390");
  // Away to Ask HeroOS, then back with a full reload.
  await page.goto(`${webOrigin}/workspaces/${companyId}`);
  await page.waitForText("What can HR do for you today?");
  await page.goto(blueprintUrl);
  await page.waitForHydrated("#edit-blueprint");
  const reloaded = await page.text();
  const [afterEdit] = await fixtures.ownerQuery(
    `SELECT b.hr_support, b.hr_support_notes, b.licensing_location, b.licensing_authority, coalesce(b.employment_jurisdiction, '-'),
            (b.primary_contact_membership_id = m.id)::text
       FROM company_blueprints b JOIN memberships m ON m.company_id = b.company_id
      WHERE b.company_id = ${quote(companyId)} AND m.user_id = ${quote(facts?.userId)}`,
  );
  check("BP-2", "saving an optional detail confirms it (\"HR support, HR support notes saved\") and it persists across navigation and reload",
    savedNotice.includes("HR support, HR support notes saved") && reloaded.includes("An outside provider") &&
      reloaded.includes("A fictional HR consultant helps with contracts.") && afterEdit?.[0] === "external",
    JSON.stringify(afterEdit));
  check("BP-3", "the jurisdiction stays canonical and unchanged (the founder's answer, nothing confirmed), and the primary contact is still the founder's Membership",
    JSON.stringify(afterEdit?.slice(2, 5)) === JSON.stringify(jurisdictionBefore[0]) && afterEdit?.[4] === "-" && afterEdit?.[5] === "true",
    JSON.stringify({ before: jurisdictionBefore[0], after: afterEdit }));
  const otherNames = await fixtures.ownerQuery(`SELECT name FROM companies WHERE id <> ${quote(companyId)}`);
  check("BP-4", "no other Company's data is visible on the Blueprint (names, people)",
    otherNames.every(([name]) => !reloaded.includes(name)) && /Others with access\s*No one else yet/.test(reloaded), `${otherNames.length} other companies`);
  await shot(page, "bp-reloaded-390");

  // Tokens stay on the server.
  const storage = await page.eval(`JSON.stringify({ local: Object.entries(localStorage), session: Object.entries(sessionStorage), cookie: document.cookie })`);
  const html = await page.html();
  const urls = page.network.map((r) => r.url).join("\n");
  const leaked = ctx.issuedTokens.filter((t) => storage.includes(t) || html.includes(t) || urls.includes(t));
  check("UI-9", "no access token in page HTML, localStorage, sessionStorage, readable cookies or any requested URL", leaked.length === 0 && !/eyJ[A-Za-z0-9_-]{20,}/.test(storage), storage.slice(0, 200));
  const apiCalls = page.network.filter((r) => r.url.startsWith(ctx.api.url));
  check("UI-10", "the browser never called the API directly (only the web origin)", apiCalls.length === 0, apiCalls.map((r) => r.url).join(", "));
  const direct = await page.eval(`fetch(${JSON.stringify(`${ctx.api.url}/me/companies`)}, { credentials: "include" }).then((r) => "status " + r.status, (e) => "blocked: " + e.name)`);
  const connectBlocked = await page.eval(`(window.__csp ?? []).some((v) => v.directive === "connect-src" && v.blocked.startsWith(${JSON.stringify(ctx.api.url)}))`);
  check("UI-11", "a script in the page cannot reach the API at all: CSP connect-src blocks it (and it has no token; the API sends no CORS grant)", direct.startsWith("blocked") && connectBlocked, direct);
  ctx.uiFounder = { subject: founderSubject, companyId };

  // ===== R2 in the browser: double-click on "Create my workspace" =====
  const dbl = await open();
  await withSession(dbl, ctx.token(ctx.subject("ui-double")));
  await dbl.viewport(1024, 900);
  await dbl.goto(`${webOrigin}/onboarding`);
  await fillWizard(dbl, { name: "[SYNTHETIC E2E] Double Click Co.", location: "difc" });
  const dblBefore = await counts(ctx);
  await dbl.eval(`(() => { const b = [...document.querySelectorAll("button")].find((x) => x.innerText.includes("Create my workspace")); b.click(); b.click(); b.click(); return true; })()`);
  await dbl.waitForText("Your workspace is ready");
  const posts = dbl.network.filter((r) => r.url.endsWith("/bff/registrations") && r.method === "POST");
  check("UI-12", "a triple click sends one registration request and creates one Company", posts.length === 1 && (await counts(ctx)).companies - dblBefore.companies === 1, `${posts.length} requests`);

  // ===== R4 in the browser: the response is lost after the server completed =====
  const lost = await open();
  await withSession(lost, ctx.token(ctx.subject("ui-lost")));
  await lost.viewport(390, 844);
  await lost.goto(`${webOrigin}/onboarding`);
  await fillWizard(lost, { name: "[SYNTHETIC E2E] Lost Response Co.", legal: "Lost Response LLC", location: "not_sure" });
  let dropped = 0;
  await lost.interceptResponses("*/bff/registrations", async (params) => {
    dropped += 1;
    // The server has answered; the browser never gets it (connection reset).
    await lost.call("Fetch.failRequest", { requestId: params.requestId, errorReason: "ConnectionReset" });
  });
  await lost.clickText("button", "Create my workspace");
  await lost.waitForText("We couldn't confirm that your workspace was created");
  await lost.interceptResponses(null);
  const [lostFacts] = await identityFacts(ctx, ctx.subject("ui-lost"));
  const lostCompanies = await fixtures.ownerQuery(`SELECT c.id, c.name FROM company_registrations r JOIN companies c ON c.id = r.company_id WHERE r.user_id = ${quote(lostFacts?.userId)}`);
  check("UI-13", "lost response: the server did create the Company, and the UI says the outcome is unknown (no false success)",
    dropped === 1 && lostCompanies.length === 1 && !(await visible(lost, "Your workspace is ready")));
  await shot(lost, "r4-uncertain-390");
  // The founder edits the name before retrying: the retry must not claim it was saved.
  await lost.clickText("button", "Edit");
  await lost.waitForHydrated("#company-name");
  await lost.type("#company-name", "[SYNTHETIC E2E] Lost Response EDITED");
  await lost.clickText("button", "Continue");
  await passAboutStep(lost);
  await lost.clickText("button", "Continue");
  await lost.waitForText("Review your company information");
  await lost.clickText("button", "Create my workspace");
  await lost.waitForText("You already have a workspace");
  const lostText = await lost.text();
  const storedName = await fixtures.ownerValue(`SELECT name FROM companies WHERE id = ${quote(lostCompanies[0]?.[0])}`);
  check("UI-14", "the retry finds the existing workspace, shows the stored name and says nothing was changed (never that the edits were saved)",
    lostText.includes("Your existing workspace wasn't changed") && lostText.includes("[SYNTHETIC E2E] Lost Response Co.") &&
    !lostText.includes("EDITED") && storedName === "[SYNTHETIC E2E] Lost Response Co." && !/weren't saved|were saved/.test(lostText));
  await shot(lost, "r4-existing-390");

  // ===== A demoted founder submits onboarding again =====
  const demoted = await newFounder(ctx, "ui-demoted");
  await fixtures.operator(["set-role", "--company", demoted.companyId, "--membership", demoted.membershipId, "--role", "member"]);
  const dem = await open();
  await withSession(dem, demoted.token);
  await dem.viewport(390, 844);
  await dem.goto(`${webOrigin}/onboarding`);
  await fillWizard(dem, { name: "[SYNTHETIC E2E] Demoted Again Co.", location: "difc" });
  await dem.clickText("button", "Create my workspace");
  await dem.waitFor(`document.body.innerText.includes("You already have a workspace") || document.body.innerText.includes("couldn't confirm")`);
  check("UI-14b", "a demoted founder submitting again sees their existing workspace (not a false \"couldn't confirm\"), with no administrator wording",
    (await visible(dem, "You already have a workspace")) && !(await visible(dem, "Check them from your workspace")));

  // ===== R7 in the browser: registration disabled =====
  await ctx.api.stop();
  await ctx.api.start({ selfRegistration: false });
  const off = await open();
  await withSession(off, ctx.token(ctx.subject("ui-disabled")));
  await off.viewport(390, 844);
  await off.goto(`${webOrigin}/onboarding`);
  await fillWizard(off, { name: "[SYNTHETIC E2E] Disabled Co.", location: "difc" });
  const offBefore = await counts(ctx);
  await off.clickText("button", "Create my workspace");
  await off.waitForText("Workspace setup isn't available yet");
  check("UI-15", "registration disabled: the honest unavailable state, nothing created", (await counts(ctx)).companies === offBefore.companies && !(await visible(off, "Your workspace is ready")));
  await shot(off, "r7-disabled-390");
  await ctx.api.stop();
  await ctx.api.start({ selfRegistration: true });

  // ===== R8 in the browser: a suspended founder =====
  const suspended = await newFounder(ctx, "ui-suspended");
  const [suspendedFacts] = await identityFacts(ctx, suspended.subject);
  await fixtures.operator(["suspend-user", "--user", suspendedFacts.userId]);
  const sus = await open();
  await withSession(sus, suspended.token);
  await sus.viewport(390, 844);
  await sus.goto(`${webOrigin}/workspaces`);
  await sus.waitForText("Let's set up your company workspace");
  check("UI-16", "a suspended founder sees the neutral welcome, never their former workspace", !(await visible(sus, "ui-suspended")) && !(await visible(sus, "SYNTHETIC E2E] ui-suspended")));
  await sus.goto(`${webOrigin}/workspaces/${suspended.companyId}`);
  await sus.waitForText("You don't have access to this workspace");
  await sus.goto(`${webOrigin}/onboarding`);
  await fillWizard(sus, { name: "[SYNTHETIC E2E] Comeback Co.", location: "difc" });
  await sus.clickText("button", "Create my workspace");
  await sus.waitForText("We couldn't create a workspace for this account");
  check("UI-17", "a suspended founder cannot re-register (refused, honest message)", true);
  await shot(sus, "r8-refused-390");

  // ===== Tenant isolation by URL =====
  const alpha = ctx.alpha ?? (await newFounder(ctx, "ui-alpha"));
  const beta = ctx.beta ?? (await newFounder(ctx, "ui-beta"));
  const a = await open();
  await withSession(a, alpha.token);
  await a.viewport(1440, 900);
  await a.goto(`${webOrigin}/workspaces`);
  await a.waitFor(`location.pathname === "/workspaces/${alpha.companyId}"`, { message: "single workspace redirect" });
  await a.waitForText("What can HR do for you today?");
  for (const path of [``, `/settings`, `/ready?outcome=created`]) {
    await a.goto(`${webOrigin}/workspaces/${beta.companyId}${path}`);
    await a.waitForText("You don't have access to this workspace");
    const pageHtml = await a.html();
    check("UI-18", `A opening Beta's ${path || "workspace"} by URL: access denied, no Beta data in the page`, !pageHtml.includes("Beta") && !pageHtml.includes("Logistics"));
  }
  await shot(a, "isolation-access-denied-1440");

  // ===== Switching between two Companies keeps no state from the other =====
  const granted = await fixtures.operator(["grant", "--company", beta.companyId, "--issuer", ctx.issuer.issuer], alpha.subject);
  check("UI-19", "the operator grants founder A a member Membership in Beta (trusted procedure)", granted.code === 0, JSON.stringify(granted));
  await a.goto(`${webOrigin}/workspaces`);
  await a.waitForText("Choose a workspace");
  await shot(a, "chooser-1440");
  await a.goto(`${webOrigin}/workspaces/${alpha.companyId}`);
  await a.waitForText("What can HR do for you today?");
  await openAccountMenu(a);
  await shot(a, "switcher-open-1440");
  await a.clickText("a", "Switch workspace");
  await a.waitForText("Choose a workspace");
  await a.click(`a[href="/workspaces/${beta.companyId}"]`);
  await a.waitFor(`location.pathname === "/workspaces/${beta.companyId}"`);
  await a.waitForText("What can HR do for you today?");
  const betaHtml = await a.html();
  check("UI-20", "after switching to Beta the page holds none of Alpha's private details", !betaHtml.includes("Alpha Holdings LLC") && !betaHtml.includes("Retail and wholesale"));
  const memberAsk = await a.eval(`document.getElementById("ask-heroos")?.disabled === true && !document.querySelector('button[aria-label="Cases"]')`);
  await a.goto(`${webOrigin}/workspaces/${beta.companyId}/settings`);
  await a.waitForText("HeroOS uses this information");
  check("UI-21", "in Beta, founder A is a member: Ask HeroOS can't open cases and the Blueprint has no Edit", memberAsk && !(await a.eval(`Boolean(document.getElementById("edit-blueprint"))`)));
  const memberPatch = await a.eval(`fetch("/bff/companies/${beta.companyId}/blueprint", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ industry: "x" }) }).then((r) => r.status)`);
  check("UI-22", "a member's hand-crafted PATCH from the page is refused (403): hiding the link is not the control", memberPatch === 403);

  // ===== Stale UI after demotion and revocation =====
  const deputySubject = ctx.subject("ui-deputy");
  const deputy = await fixtures.operator(["provision", "--company", alpha.companyId, "--issuer", ctx.issuer.issuer], deputySubject);
  await fixtures.operator(["set-role", "--company", alpha.companyId, "--membership", deputy.membership_id, "--role", "company_admin"]);
  const dep = await open();
  await withSession(dep, ctx.token(deputySubject));
  await dep.viewport(390, 844);
  await dep.goto(`${webOrigin}/workspaces/${alpha.companyId}/settings`);
  await dep.waitForHydrated("#edit-blueprint");
  await dep.click("#edit-blueprint");
  await dep.waitForHydrated("#bp-industry");
  await fixtures.operator(["set-role", "--company", alpha.companyId, "--membership", deputy.membership_id, "--role", "member"]);
  const industryBefore = await fixtures.ownerValue(`SELECT industry FROM company_blueprints WHERE company_id = ${quote(alpha.companyId)}`);
  await dep.type("#bp-industry", "Changed after demotion");
  await dep.clickText("button", "Save changes");
  await dep.waitForText("Only company administrators can edit the Blueprint");
  const industryAfter = await fixtures.ownerValue(`SELECT industry FROM company_blueprints WHERE company_id = ${quote(alpha.companyId)}`);
  check("UI-23", "a form left open by a demoted administrator cannot save: refused, nothing written", industryBefore === industryAfter);
  await shot(dep, "stale-demoted-refused-390");
  await dep.goto(`${webOrigin}/workspaces/${alpha.companyId}/settings`);
  await dep.waitForText("HeroOS uses this information");
  check("UI-24", "reloading shows the read-only Blueprint (no Edit)", !(await dep.eval(`Boolean(document.getElementById("edit-blueprint") || document.getElementById("bp-industry"))`)));
  await fixtures.operator(["revoke-membership", "--company", alpha.companyId, "--membership", deputy.membership_id]);
  await dep.goto(`${webOrigin}/workspaces/${alpha.companyId}`);
  await dep.waitFor(`document.body.innerText.includes("You don't have access to this workspace") || document.body.innerText.includes("No active workspace")`);
  check("UI-25", "after revocation the same session gets no workspace data", !(await dep.html()).includes("Alpha Holdings LLC"));

  // ===== Logout and the Back button =====
  const out = await open();
  await out.viewport(390, 844);
  const outSubject = ctx.subject("ui-logout");
  await newFounderWithName(ctx, outSubject, "[SYNTHETIC E2E] Logout Co.");
  await ctx.signIn(out, outSubject);
  await out.goto(`${webOrigin}/workspaces`);
  await out.waitForText("What can HR do for you today?");
  await signOutFromMenu(out);
  await out.waitFor(`location.origin === ${JSON.stringify(webOrigin)} && location.pathname === "/" && document.body.innerText.includes("Get started")`, { message: "signed-out homepage" });
  check("UI-26", "sign out returns to the signed-out homepage through the provider's logout", ctx.issuer.events.some((e) => e.type === "logout"));
  await out.eval("history.back()");
  await ctx.sleep(1500);
  await out.waitFor("document.readyState === 'complete'");
  const backText = await out.text();
  check("UI-27", "Back after logout shows no workspace data (pages are no-store)", !backText.includes("Logout Co.") && !backText.includes("What can HR do for you today?"), backText.slice(0, 120));
  await out.goto(`${webOrigin}/workspaces`);
  await out.waitForText("Please sign in");
  const cookies = await out.cookies([webOrigin]);
  check("UI-28", "after logout no session cookie remains and protected pages ask to sign in", !cookies.some((c) => c.name === "__Host-heroos-session"));

  // ===== The same, with the Cache-Control the live Vercel deployment sends =====
  // Observed read-only on the live demo (2026-10-14): Vercel serves these
  // pages with "public, max-age=0, must-revalidate" instead of Next.js'
  // "private, no-cache, no-store, ...". Without no-store the browser may keep
  // a signed-in page in its back/forward cache.
  ctx.web.htmlCacheControl = "public, max-age=0, must-revalidate";
  try {
    const vercel = await open();
    await vercel.viewport(390, 844);
    const vercelSubject = ctx.subject("ui-logout-vercel");
    await newFounderWithName(ctx, vercelSubject, "[SYNTHETIC E2E] Shared Device Co.");
    await ctx.signIn(vercel, vercelSubject);
    await vercel.goto(`${webOrigin}/workspaces`);
    await vercel.waitForText("What can HR do for you today?");
    const pageCacheControl = vercel.responses.filter((r) => r.url.startsWith(`${webOrigin}/workspaces/`)).at(-1)?.headers["cache-control"];
    await signOutFromMenu(vercel);
    await vercel.waitFor(`location.origin === ${JSON.stringify(webOrigin)} && location.pathname === "/" && document.body.innerText.includes("Get started")`, { message: "signed-out homepage" });
    await vercel.eval("history.back()");
    await ctx.sleep(1500);
    await vercel.waitFor("document.readyState === 'complete'");
    const restored = await vercel.text();
    check("UI-27v", "with Vercel's observed Cache-Control, Back after logout still shows no workspace data", !restored.includes("Shared Device Co.") && !restored.includes("What can HR do for you today?"),
      `page Cache-Control: ${pageCacheControl}; after Back: ${restored.slice(0, 100).replace(/\n/g, " ")}`);
  } finally {
    ctx.web.htmlCacheControl = null;
  }

  // ===== Unverified e-mail: the staging Auth0 Post Login Action =====
  // The test provider emulates the Action (deny with `email_not_verified`) and
  // Auth0's remembered session for these subjects only (TestIssuer.requireVerifiedEmail).
  const hasSession = async (p) => (await p.cookies([webOrigin])).some((c) => c.name === "__Host-heroos-session");
  // A marker on `window` disappears once the click has really navigated.
  const navigatedBack = (p, extra = "true") =>
    p.waitFor(`!window.__heroosMarker && location.origin === ${JSON.stringify(webOrigin)} && document.readyState === "complete" && ${extra}`, {
      message: "back on the web app after the click",
    });
  const unv = await open();
  await unv.viewport(390, 844);
  const unverifiedSubject = ctx.subject("ui-unverified");
  ctx.issuer.requireVerifiedEmail(unverifiedSubject);
  const beforeUnverified = await counts(ctx);
  await ctx.signIn(unv, unverifiedSubject, { signup: true });
  await unv.waitForText("Please verify your email address first");
  await shot(unv, "verify-email-notice-390");
  check("UI-33", "an unverified sign-up lands on the fixed verify-email notice without a session", new URL(unv.url).search === "?auth=verify_email" && !(await hasSession(unv)), unv.url);
  const noticeActions = await unv.eval(`(() => {
    const n = document.querySelector('[role="alert"]');
    const form = n && n.querySelector("form");
    return n && { link: n.querySelector("a")?.getAttribute("href"), action: form?.getAttribute("action"), method: form?.getAttribute("method") };
  })()`);
  check("UI-34", "the notice offers \"Sign in again\" and a POST \"Use a different account\"; the provider's reason is not rendered",
    noticeActions?.link === "/auth/login" && noticeActions?.action === "/auth/logout" && noticeActions?.method === "post" && !(await unv.html()).includes("email_not_verified"),
    JSON.stringify(noticeActions));

  let mark = ctx.issuer.events.length;
  await unv.eval("window.__heroosMarker = 1");
  await unv.clickText("a", "Sign in again");
  await navigatedBack(unv, `location.search === "?auth=verify_email"`);
  await ctx.sleep(2000);
  const retry = ctx.issuer.events.slice(mark);
  check("UI-35", "still unverified: \"Sign in again\" is denied once through the remembered provider session (no loop, no form, no session)",
    retry.filter((e) => e.type === "authorize").length === 1 && retry.some((e) => e.type === "authorize" && e.session)
      && retry.filter((e) => e.type === "post_login_denied").length === 1 && !(await hasSession(unv)),
    JSON.stringify(retry.map((e) => e.type)));

  ctx.issuer.verifyEmail(unverifiedSubject);
  mark = ctx.issuer.events.length;
  await unv.eval("window.__heroosMarker = 1");
  await unv.clickText("a", "Sign in again");
  await navigatedBack(unv, `document.body.innerText.includes("Set up my company")`);
  const recovered = ctx.issuer.events.slice(mark);
  check("UI-36", "after verifying, \"Sign in again\" signs in (provider session, no form) to the neutral welcome; nothing is created",
    (await hasSession(unv)) && recovered.some((e) => e.type === "authorize" && e.session) && recovered.some((e) => e.type === "token_issued")
      && sameCounts(beforeUnverified, await counts(ctx)),
    JSON.stringify(recovered.map((e) => e.type)));

  const sw = await open();
  await sw.viewport(390, 844);
  const firstAccount = ctx.subject("ui-unverified-switch");
  ctx.issuer.requireVerifiedEmail(firstAccount);
  await ctx.signIn(sw, firstAccount);
  await sw.waitForText("Please verify your email address first");
  mark = ctx.issuer.events.length;
  await sw.eval("window.__heroosMarker = 1");
  await sw.clickText("button", "Use a different account");
  await navigatedBack(sw, `location.pathname === "/" && document.body.innerText.includes("Get started")`);
  check("UI-37", "\"Use a different account\" ends the provider session through RP-initiated logout",
    ctx.issuer.events.slice(mark).some((e) => e.type === "logout" && e.endedSession === true),
    JSON.stringify(ctx.issuer.events.slice(mark)));
  await sw.goto(`${webOrigin}/auth/login`);
  await sw.waitFor(`location.origin === ${JSON.stringify(ctx.issuer.origin)} && document.getElementById("subject")`, { message: "provider form after switching" });
  const switchedTo = ctx.subject("ui-switched-account");
  await sw.type("#subject", switchedTo);
  await sw.click("#continue");
  await sw.waitFor(`location.origin === ${JSON.stringify(webOrigin)} && document.readyState === "complete" && document.body.innerText.includes("Set up my company")`, { message: "signed in as the other account" });
  check("UI-38", "after switching, the provider asks again and a different identity signs in", await hasSession(sw));

  // ===== Session expiry in the browser =====
  const exp = await open();
  await withSession(exp, ctx.token(ctx.subject("ui-expired"), { lifetimeSeconds: -30 }));
  await exp.viewport(390, 844);
  await exp.goto(`${webOrigin}/workspaces`);
  await exp.waitForText("Your session has ended");
  await shot(exp, "session-expired-390");
  check("UI-29", "an expired access token shows the session-ended state", true);

  // ===== Jurisdiction as displayed (only what the API returns) =====
  const jf = ctx.jurisdictionFounders;
  if (jf) {
    const states = [
      ["difc", "Dubai International Financial Centre"],
      ["adgm", "ADGM isn't supported yet"],
      ["notSure", "Your licensing details can be confirmed later"],
      ["otherWithoutAuthority", "Add the licensing authority shown on your business licence"],
      ["missing", "We don't have your licensing details yet"],
    ];
    for (const [name, text] of states) {
      const p = await open();
      await withSession(p, jf[name].token);
      await p.viewport(1024, 900);
      await p.goto(`${webOrigin}/workspaces/${jf[name].companyId}/settings`);
      await p.waitForText("HeroOS uses this information");
      // The Blueprint shows the jurisdiction plainly: the API's readiness in its own words, never a "confirmed" badge.
      check("UI-30", `the Company Blueprint shows the API's readiness for "${name}"`, (await visible(p, text)) && !(await visible(p, "Confirmed")), text);
      if (name === "difc" || name === "adgm") await shot(p, `jurisdiction-${name}-1024`);
      await p.close();
    }
  } else {
    ctx.report.notRun("UI-30", "jurisdiction display per readiness", "jurisdiction suite not selected");
  }
  const lic = await open();
  await withSession(lic, ctx.token(ctx.subject("ui-licensing")));
  await lic.viewport(390, 844);
  await lic.goto(`${webOrigin}/onboarding`);
  await startOnboarding(lic);
  await lic.type("#company-name", "[SYNTHETIC E2E] Licensing Look Co.");
  await lic.clickText("button", "Continue");
  await passAboutStep(lic);
  const radios = await lic.eval(`[...document.querySelectorAll("input[type=radio]")].map((r) => r.value)`);
  await lic.click("#onboarding-location-other");
  await lic.waitFor(`document.getElementById("onboarding-authority")`);
  const control = await lic.eval(`document.getElementById("onboarding-authority").tagName + "/" + (document.getElementById("onboarding-authority").getAttribute("type") ?? "")`);
  check("UI-31", "licensing: exactly DIFC / Other / I'm not sure, no follow-up quiz", JSON.stringify(radios) === JSON.stringify(["difc", "other", "not_sure"]) && !(await lic.eval(`Boolean(document.querySelector("select"))`)));
  check("UI-32", "Other uses free text (no invented authority list)", control.startsWith("INPUT"), control);
  await shot(lic, "licensing-other-390");

  // ===== Responsive layout and accessibility on the real stack =====
  await responsiveAndA11y(ctx, { alpha, open, shot });

  // ===== CSP reproduction attempt: the page shape that showed it in M1-10D =====
  // M1-10D saw React's hidden <svg style="display:none"> streaming container on
  // an administrator's workspace with a confirmed DIFC jurisdiction, a full
  // setup checklist, a case and the company switcher. Rebuild exactly that and
  // load it repeatedly; record how often the container appears and whether it
  // ever survives into a rendered frame.
  const rich = await newFounder(ctx, "csp-rich", {
    company_name: "[SYNTHETIC E2E] CSP Rich Co.",
    blueprint: { legal_name: "CSP Rich Holdings LLC", industry: "Hospitality", employee_count: 42, licensing: { location: "difc" } },
  });
  await fixtures.operator(["confirm-jurisdiction", "--company", rich.companyId, "--jurisdiction", "difc", "--licensing-location", "difc"]);
  await fixtures.ownerQuery(`INSERT INTO cases (id, company_id, case_type, title) VALUES (gen_random_uuid(), ${quote(rich.companyId)}, 'general', '[SYNTHETIC E2E] Case R-1')`);
  await fixtures.operator(["grant", "--company", beta.companyId, "--issuer", ctx.issuer.issuer], rich.subject);
  const repro = await ctx.newPage();
  await repro.addInitScript(CSP_PROBE);
  await withSession(repro, rich.token);
  const loads = [];
  for (const [width, path] of [[1440, ""], [390, ""], [1440, "/settings"], [390, "/settings"]]) {
    await repro.viewport(width, 900);
    for (let i = 0; i < 15; i += 1) {
      await repro.goto(`${webOrigin}/workspaces/${rich.companyId}${path}`);
      await repro.waitForText(path ? "HeroOS uses this information" : "What can HR do for you today?");
      await ctx.sleep(150);
      loads.push({ width, path, ...JSON.parse(await repro.eval(`JSON.stringify({ csp: (window.__csp ?? []).filter((v) => /style-src/.test(v.directive)).length, svg: (window.__containers ?? []).filter((c) => c.tag.toLowerCase() === "svg"), divs: (window.__containers ?? []).filter((c) => c.tag.toLowerCase() !== "svg").length })`)) });
    }
  }
  for (const width of [1440, 390]) {
    await repro.viewport(width, 900);
    for (let i = 0; i < 10; i += 1) {
      await repro.goto(`${webOrigin}/workspaces/${rich.companyId}/ready?outcome=created`);
      await repro.waitForText("Your workspace is ready");
      await ctx.sleep(150);
      loads.push({ width, path: "/ready", ...JSON.parse(await repro.eval(`JSON.stringify({ csp: (window.__csp ?? []).filter((v) => /style-src/.test(v.directive)).length, svg: (window.__containers ?? []).filter((c) => c.tag.toLowerCase() === "svg"), divs: (window.__containers ?? []).filter((c) => c.tag.toLowerCase() !== "svg").length })`)) });
    }
  }
  await repro.close();
  // The signed-out homepage (dynamic, with the large inline hero illustration).
  const home = await ctx.newPage();
  await home.addInitScript(CSP_PROBE);
  for (const width of [1440, 390]) {
    await home.viewport(width, 900);
    for (let i = 0; i < 10; i += 1) {
      await home.goto(`${webOrigin}/`);
      await home.waitForText("Get started");
      await ctx.sleep(150);
      loads.push({ width, path: "/home", ...JSON.parse(await home.eval(`JSON.stringify({ csp: (window.__csp ?? []).filter((v) => /style-src/.test(v.directive)).length, svg: (window.__containers ?? []).filter((c) => c.tag.toLowerCase() === "svg"), divs: (window.__containers ?? []).filter((c) => c.tag.toLowerCase() !== "svg").length })`)) });
    }
  }
  await home.close();
  const withViolation = loads.filter((l) => l.csp > 0);
  const reproPainted = loads.flatMap((l) => l.svg).filter((c) => c.framesAtRemove !== undefined && c.framesAtRemove > c.framesAtInsert);
  ctx.cspReproduction = {
    loads: loads.length,
    loadsWithStyleViolation: withViolation.length,
    byPage: Object.fromEntries([...new Set(loads.map((l) => `${l.width}:${l.path || "/workspace"}`))].map((key) => [key, `${loads.filter((l) => `${l.width}:${l.path || "/workspace"}` === key && l.csp > 0).length}/${loads.filter((l) => `${l.width}:${l.path || "/workspace"}` === key).length}`])),
    svgContainers: loads.reduce((n, l) => n + l.svg.length, 0),
    hiddenDivContainers: loads.reduce((n, l) => n + l.divs, 0),
    svgContainersAcrossAFrame: reproPainted.length,
    svgContents: [...new Set(loads.flatMap((l) => l.svg.map((c) => c.content)))],
  };
  ctx.report.check("CSP-R1", `reproduction attempt recorded: ${JSON.stringify(ctx.cspReproduction)}`, true);
  check("CSP-R2", "in every reproduction load, no hidden SVG container lived across a rendered frame", reproPainted.length === 0, JSON.stringify(reproPainted).slice(0, 300));
  check("CSP-R3", "no reproduction load produced a blocked inline style at all (the current CSP is kept, nothing is relaxed)", withViolation.length === 0, JSON.stringify(ctx.cspReproduction).slice(0, 400));

  // ===== CSP investigation (Phase J) =====
  const violations = [];
  const containers = [];
  for (const p of pages) {
    try {
      const data = await p.eval(`JSON.stringify({ url: location.pathname, csp: window.__csp ?? [], containers: window.__containers ?? [], leftovers: document.querySelectorAll("[id^='S:'],[id^='P:']").length })`);
      const parsed = JSON.parse(data);
      violations.push(...parsed.csp.map((v) => ({ ...v, url: parsed.url })));
      containers.push(...parsed.containers.map((c) => ({ ...c, url: parsed.url })));
      check("CSP-1", `no streaming placeholder is left in the final DOM (${parsed.url.replace(/[0-9a-f-]{36}/g, "{id}")})`, parsed.leftovers === 0);
    } catch {
      // closed page
    }
  }
  const consoleEntries = pages.flatMap((p) => p.console);
  const cspLogs = consoleEntries.filter((e) => e.source === "security" || /Content Security Policy/.test(e.text));
  const hydration = consoleEntries.filter((e) => /hydrat|Minified React error|#418|#423|#425/i.test(e.text));
  const exceptions = consoleEntries.filter((e) => e.level === "exception");
  check("CSP-2", "no hydration errors in any page", hydration.length === 0, hydration.map((h) => h.text).join(" | ").slice(0, 300));
  check("CSP-3", "no uncaught exceptions in any page", exceptions.length === 0, exceptions.map((h) => h.text).join(" | ").slice(0, 300));
  const styleViolations = violations.filter((v) => /style-src/.test(v.directive));
  // UI-11's deliberate fetch of the API is expected to be blocked by connect-src.
  const otherViolations = violations.filter((v) => !/style-src/.test(v.directive) && !(v.directive === "connect-src" && v.blocked.startsWith(ctx.api.url)));
  check("CSP-4", "no CSP violation other than inline style attributes (scripts, frames, connections are clean)", otherViolations.length === 0, JSON.stringify(otherViolations).slice(0, 300));
  const svgContainers = containers.filter((c) => c.tag.toLowerCase() === "svg");
  const painted = svgContainers.filter((c) => c.framesAtRemove !== undefined && c.framesAtRemove > c.framesAtInsert);
  ctx.cspFindings = {
    styleViolations: styleViolations.length,
    samples: [...new Set(styleViolations.map((v) => v.sample))],
    pages: [...new Set(styleViolations.map((v) => v.url.replace(/[0-9a-f-]{36}/g, "{id}")))],
    svgContainers: svgContainers.length,
    svgContainersAcrossAFrame: painted.length,
    consoleLines: cspLogs.length,
  };
  check("CSP-5", "every blocked inline style is React's hidden streaming container (sample \"display:none\")",
    styleViolations.every((v) => v.sample === "display:none"), JSON.stringify(ctx.cspFindings));
  check("CSP-6", "no hidden SVG streaming container survived into a rendered frame (no visible flash)", painted.length === 0, JSON.stringify(painted).slice(0, 300));
  ctx.report.check("CSP-7", `CSP findings recorded: ${JSON.stringify(ctx.cspFindings)}`, true);

  for (const p of pages) await p.close();
}

async function newFounderWithName(ctx, subject, name) {
  const response = await ctx.apiFetch("/company-registrations", { method: "POST", token: ctx.token(subject), body: { company_name: name } });
  if (response.status !== 201) throw new Error(`registration answered ${response.status}`);
  return response.json;
}

async function responsiveAndA11y(ctx, { alpha, open, shot }) {
  const { check, webOrigin } = ctx;
  const page = await open();
  await page.setCookie({ name: "__Host-heroos-session", value: ctx.session(alpha.token), url: webOrigin, path: "/", secure: true, httpOnly: true, sameSite: "Lax" });

  const headerClash = () => page.eval(`(() => {
    const header = document.querySelector("header");
    if (!header) return null;
    const items = [...header.querySelectorAll("a, button")].filter((el) => el.offsetParent !== null && !el.closest("nav, .absolute"))
      .map((el) => ({ t: (el.getAttribute("aria-label") || el.innerText).trim(), r: el.getBoundingClientRect() })).filter((i) => i.r.width > 0);
    for (let i = 0; i < items.length; i += 1) for (let j = i + 1; j < items.length; j += 1) {
      const a = items[i].r, c = items[j].r;
      if (a.left < c.right - 0.5 && c.left < a.right - 0.5 && a.top < c.bottom - 0.5 && c.top < a.bottom - 0.5) return items[i].t + " overlaps " + items[j].t;
    }
    const off = items.find((i) => i.r.left < 0 || i.r.right > innerWidth + 0.5);
    return off ? off.t + " off-screen" : null;
  })()`);
  const smallTargets = () => page.eval(`[...document.querySelectorAll("a, button, input, select, textarea")]
    .filter((el) => el.offsetParent !== null && !el.closest("p, footer") && el.type !== "radio" && el.type !== "hidden" && !el.classList.contains("sr-only"))
    .map((el) => { const r = el.getBoundingClientRect(); return { t: (el.innerText || el.getAttribute("aria-label") || el.id || el.tagName).trim().slice(0, 30), w: Math.round(r.width), h: Math.round(r.height) }; })
    .filter((r) => r.h < 44 || r.w < 44)`);
  const unlabelled = () => page.eval(`[...document.querySelectorAll("input, select, textarea")].filter((el) => el.type !== "hidden" && !el.labels?.length && !el.getAttribute("aria-label") && !el.getAttribute("aria-labelledby")).map((el) => el.id || el.name)`);

  const screens = [
    ["ask", `/workspaces/${alpha.companyId}`, "What can HR do for you today?"],
    ["chooser", "/workspaces", "Choose a workspace"],
    ["blueprint", `/workspaces/${alpha.companyId}/settings`, "HeroOS uses this information"],
    ["space", `/workspaces/${alpha.companyId}/space`, "Your HeroOS access and company overview."],
    ["onboarding", "/onboarding", "Welcome to HeroOS"],
    ["ready", `/workspaces/${alpha.companyId}/ready?outcome=created`, "Your workspace is ready"],
  ];
  for (const [name, path, text] of screens) {
    for (const width of WIDTHS) {
      await page.viewport(width, 900);
      await page.goto(`${webOrigin}${path}`);
      await page.waitForText(text);
      if (width === WIDTHS[0]) {
        // One HeroOS symbol across the signed-in app: the top bar's is the one HeroOS speaks with.
        const logos = await page.eval(`[...document.querySelectorAll("header img")].map((img) => img.getAttribute("src"))`);
        check("UI-39", `${name}: the top bar shows the current HeroOS symbol (/branding/heroos-symbol.png), not the old speech-bubble logo`,
          logos.includes("/branding/heroos-symbol.png") && !logos.includes("/branding/heroos-logo-symbol.png"), JSON.stringify(logos));
      }
      const over = await page.overflow();
      const clash = await headerClash();
      check("A11Y-1", `${name} @${width}px: no horizontal scroll, header items don't overlap`, over <= 0 && clash === null, `${over}px ${clash ?? ""}`);
      if (width === 390) {
        const small = await smallTargets();
        check("A11Y-2", `${name} @390px: interactive targets at least 44px`, small.length === 0, JSON.stringify(small));
        const missing = await unlabelled();
        check("A11Y-3", `${name}: every form control has a label`, missing.length === 0, JSON.stringify(missing));
        const h1 = await page.eval(`document.querySelectorAll("h1").length`);
        check("A11Y-4", `${name}: exactly one h1`, h1 === 1, String(h1));
      }
      if (width === 320 || width === 1440) await shot(page, `${name}-${width}`);
    }
  }

  // Keyboard: the skip link comes first, focus is visible, the account menu works without a mouse.
  await page.viewport(1440, 900);
  await page.goto(`${webOrigin}/workspaces/${alpha.companyId}`);
  await page.waitForText("What can HR do for you today?");
  await page.waitForHydrated('button[aria-label^="Account menu"]');
  await page.press("Tab");
  const first = await page.eval(`document.activeElement?.innerText?.trim()`);
  const outline = await page.eval(`getComputedStyle(document.activeElement).outlineStyle + " " + getComputedStyle(document.activeElement).outlineWidth`);
  check("A11Y-5", "the first Tab stop is \"Skip to content\" and it is visibly focused", first === "Skip to content" && !outline.startsWith("none"), `${first} / ${outline}`);
  await page.eval(`document.querySelector('button[aria-label^="Account menu"]')?.focus()`);
  const menuLabel = await page.eval(`document.activeElement?.getAttribute("aria-label") ?? ""`);
  await page.press("Enter");
  await page.waitFor(`[...document.querySelectorAll('ul[aria-label="Company"] a')].some((a) => a.offsetParent !== null)`, { message: "account menu opened by keyboard" });
  const expanded = await page.eval(`document.activeElement?.getAttribute("aria-expanded")`);
  await page.press("Escape");
  await page.waitFor(`![...document.querySelectorAll('ul[aria-label="Company"] a')].some((a) => a.offsetParent !== null)`, { message: "account menu closed by Escape" });
  const back = await page.eval(`document.activeElement?.getAttribute("aria-expanded")`);
  check("A11Y-6", "the account menu opens with Enter, reports aria-expanded, closes with Escape and returns focus", menuLabel.startsWith("Account menu") && expanded === "true" && back === "false", `${menuLabel} ${expanded} ${back}`);

  // Text fields inside a rounded control (the Ask composer, Search cases): the control's rounded
  // border shows focus and the field draws no rectangle, by keyboard (Tab) and by mouse alike.
  const fieldFocus = (selector) => page.eval(`(() => {
    const field = document.querySelector(${JSON.stringify(selector)});
    const control = getComputedStyle(field.parentElement);
    return { focused: document.activeElement === field, outline: getComputedStyle(field).outlineStyle,
             border: control.borderTopColor, shadow: control.boxShadow, radius: parseFloat(control.borderTopLeftRadius) };
  })()`);
  const FOCUS_BORDER = "rgb(61, 107, 196)";
  const looksFocused = (look) => look.focused && look.outline === "none" && look.border === FOCUS_BORDER && look.shadow.includes("rgba(61, 107, 196, 0.12)") && look.radius >= 12;
  const tabTo = async (selector) => {
    for (let step = 0; step < 12 && !(await page.eval(`document.activeElement === document.querySelector(${JSON.stringify(selector)})`)); step += 1) await page.press("Tab");
  };
  const mouseInto = async (selector) => {
    const { x, y } = await page.eval(`(() => { const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
    for (const type of ["mousePressed", "mouseReleased"]) await page.call("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 });
  };
  // Waits out the control's border/shadow transition, then reads the settled look.
  const settled = async (selector, focused) => {
    const expression = `(() => { const f = document.querySelector(${JSON.stringify(selector)}); return (document.activeElement === f) === ${focused} && getComputedStyle(f.parentElement).borderTopColor ${focused ? "===" : "!=="} ${JSON.stringify(FOCUS_BORDER)}; })()`;
    await page.waitFor(expression, { timeout: 3_000 }).catch(() => {});
    await ctx.sleep(300);
    return fieldFocus(selector);
  };
  for (const width of [1440, 390]) {
    await page.viewport(width, 900);
    await page.goto(`${webOrigin}/workspaces/${alpha.companyId}`);
    await page.waitForHydrated("#ask-heroos");
    const idle = await settled("#ask-heroos", false);
    await tabTo("#ask-heroos");
    const byKeyboard = await settled("#ask-heroos", true);
    await page.eval("document.activeElement.blur()");
    await settled("#ask-heroos", false);
    await mouseInto("#ask-heroos");
    const byMouse = await settled("#ask-heroos", true);
    check("A11Y-12", `Ask composer @${width}px: focus shows on the rounded composer (keyboard and mouse), no rectangle on the field`,
      !looksFocused(idle) && idle.border !== FOCUS_BORDER && looksFocused(byKeyboard) && looksFocused(byMouse), JSON.stringify({ idle, byKeyboard, byMouse }));
    await ctx.screenshotOf(page, `a11y-12-ask-focused-${width}`, "form:has(#ask-heroos)");

    const search = '[role="dialog"] input[type="search"]';
    await page.waitForHydrated('button[aria-label="Cases"]');
    await page.eval(`document.querySelector('button[aria-label="Cases"]').focus()`);
    await page.press("Enter");
    await page.waitFor(`document.querySelector(${JSON.stringify(search)})`, { message: "Cases drawer opened by keyboard" });
    const searchIdle = await settled(search, false);
    await tabTo(search);
    const searchByKeyboard = await settled(search, true);
    await page.eval("document.activeElement.blur()");
    await settled(search, false);
    await mouseInto(search);
    const searchByMouse = await settled(search, true);
    await ctx.screenshotOf(page, `a11y-13-search-focused-${width}`, '[role="dialog"]');
    check("A11Y-13", `Search cases @${width}px: focus shows on the rounded field (keyboard and mouse), no rectangle on the input`,
      searchIdle.border !== FOCUS_BORDER && looksFocused(searchByKeyboard) && looksFocused(searchByMouse), JSON.stringify({ searchIdle, searchByKeyboard, searchByMouse }));
    await page.press("Escape");
  }
  await page.viewport(1440, 900);

  // Onboarding by keyboard: Enter submits, errors are announced and focused.
  await page.goto(`${webOrigin}/onboarding`);
  await page.waitForHydrated("#onboarding-start");
  await page.click("#onboarding-start");
  await page.waitForHydrated("#company-name");
  await page.eval(`document.getElementById("company-name").focus()`);
  await page.press("Enter");
  await page.waitForText("Enter your company name");
  const described = await page.eval(`(() => { const el = document.getElementById("company-name"); const ids = (el.getAttribute("aria-describedby") || "").split(" "); return el.getAttribute("aria-invalid") + " " + ids.map((id) => document.getElementById(id)?.innerText ?? "").join(" | "); })()`);
  check("A11Y-7", "keyboard submit shows the error, marks the field aria-invalid and describes it", described.startsWith("true") && described.includes("Enter your company name"), described);

  // Reduced motion and 200 % zoom.
  // The homepage (signed out: a signed-in visitor is sent to /workspaces).
  const anonymous = await open();
  await anonymous.viewport(1440, 900);
  await anonymous.emulateMedia([{ name: "prefers-reduced-motion", value: "reduce" }]);
  await anonymous.goto(`${webOrigin}/`);
  await anonymous.waitForText("Get started");
  const motion = await anonymous.eval(`JSON.stringify({ scroll: getComputedStyle(document.documentElement).scrollBehavior, animated: [...document.querySelectorAll("*")].filter((el) => { const s = getComputedStyle(el); return s.animationName !== "none" && parseFloat(s.animationDuration) > 0.01 && s.animationPlayState === "running" && s.animationIterationCount === "infinite"; }).length })`);
  const parsed = JSON.parse(motion);
  check("A11Y-8", "prefers-reduced-motion: no smooth scrolling and no endless animations", parsed.scroll === "auto" && parsed.animated === 0, motion);
  // Mobile navigation by keyboard (signed-out homepage at phone width).
  await anonymous.viewport(390, 844);
  await anonymous.goto(`${webOrigin}/`);
  await anonymous.waitForHydrated("button[aria-label='Open menu']");
  await anonymous.eval(`document.querySelector("button[aria-label='Open menu']").focus()`);
  await anonymous.press("Enter");
  await anonymous.waitFor(`document.querySelector("nav[aria-label='Mobile']")`, { message: "mobile menu opened by keyboard" });
  const menuLinks = await anonymous.eval(`[...document.querySelectorAll("nav[aria-label='Mobile'] a")].map((a) => a.getAttribute("href"))`);
  await anonymous.press("Escape");
  await anonymous.waitFor(`!document.querySelector("nav[aria-label='Mobile']")`, { message: "mobile menu closed by Escape" });
  check("A11Y-11", "the mobile menu opens with Enter, offers Sign in, and closes with Escape", menuLinks.includes("/auth/login"), JSON.stringify(menuLinks));
  // The public homepage carries the signed-in app's current HeroOS logo, and nothing of the old one.
  for (const width of [1440, 390]) {
    await anonymous.viewport(width, 900);
    await anonymous.goto(`${webOrigin}/`);
    await anonymous.waitForText("Get started");
    const brand = await anonymous.eval(`({
      header: [...document.querySelectorAll("header img")].map((img) => img.getAttribute("src")),
      footer: [...document.querySelectorAll("footer img")].map((img) => img.getAttribute("src")),
      symbolShown: [...document.querySelectorAll('header img[src="/branding/heroos-symbol.png"]')].some((img) => img.getBoundingClientRect().width > 0),
      old: document.documentElement.outerHTML.includes("heroos-logo-symbol"),
    })`);
    const current = (srcs) => JSON.stringify(srcs) === JSON.stringify(["/branding/heroos-symbol.png", "/branding/heroos-logo-wordmark.png"]);
    check("UI-40", `homepage @${width}px: header and footer show the current HeroOS symbol and wordmark; no old speech-bubble logo on the page`,
      current(brand.header) && current(brand.footer) && brand.symbolShown && !brand.old, JSON.stringify(brand));
    await ctx.screenshotOf(anonymous, `homepage-header-${width}`, "header");
  }
  await page.viewport(720, 900, { deviceScaleFactor: 2 });
  for (const path of [`/workspaces/${alpha.companyId}`, "/onboarding", `/workspaces/${alpha.companyId}/settings`]) {
    await page.goto(`${webOrigin}${path}`);
    await page.waitFor("document.readyState === 'complete'");
    await ctx.sleep(300);
    check("A11Y-9", `200% zoom (1440px window = 720 CSS px) on ${path.replace(/[0-9a-f-]{36}/, "{id}")}: no horizontal scroll`, (await page.overflow()) <= 0);
  }
  ctx.report.notRun("A11Y-10", "screen-reader pass (VoiceOver/NVDA)", "no screen reader is available in this environment; automated checks are not a substitute");
}
