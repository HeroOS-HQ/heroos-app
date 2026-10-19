// @vitest-environment node
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Structural checks on the source (M1-10D): the browser never holds or sends an
 * access token, never calls the HeroOS API, and never stores data.
 */

const SRC = join(import.meta.dirname, ".");

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return name === "test" ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

const files = sourceFiles(SRC).map((path) => ({ path: relative(SRC, path), text: readFileSync(path, "utf8") }));
const clientFiles = files.filter(({ text }) => /^["']use client["'];?/m.test(text.trimStart().split("\n")[0]));

describe("browser/server boundary", () => {
  it("finds the client components it checks", () => {
    expect(clientFiles.map(({ path }) => path).sort()).toEqual([
      "components/app/back-forward-cache-guard.tsx",
      "components/app/company-switcher.tsx",
      "components/cases/answers-form.tsx",
      "components/cases/case-timeline.tsx",
      "components/cases/case-workspace.tsx",
      "components/cases/decision-form.tsx",
      "components/cases/decisions-panel.tsx",
      "components/cases/document-form.tsx",
      "components/cases/documents-panel.tsx",
      "components/cases/new-case-form.tsx",
      "components/cases/progression-panel.tsx",
      "components/onboarding/onboarding-wizard.tsx",
      "components/settings/company-settings-form.tsx",
      "components/site/icons.tsx",
      "components/site/reveal.tsx",
      "components/site/site-header.tsx",
      "components/site/workflow-journey.tsx",
    ]);
  });

  it("client components only *type*-import server modules", () => {
    for (const { path, text } of clientFiles) {
      const runtime = [...text.matchAll(/^import (?!type )[^;]*from ["'](@\/lib\/server\/[^"']+|server-only)["']/gm)];
      expect(runtime.map((match) => match[1]), path).toEqual([]);
    }
  });

  it("no client component handles tokens or calls the HeroOS API directly", () => {
    for (const { path, text } of clientFiles) {
      expect(text, path).not.toMatch(/accessToken|Authorization|Bearer |HEROOS_API_BASE_URL|apiBaseUrl/);
      for (const match of text.matchAll(/fetch\)?\(\s*([`"'])([^`"']*)/g)) {
        expect(match[2], path).toMatch(/^\/bff\//);
      }
    }
  });

  it("nothing uses browser storage or public (browser-inlined) environment variables", () => {
    for (const { path, text } of files) {
      expect(text, path).not.toMatch(/\b(localStorage|sessionStorage|indexedDB)\s*[.[]|process\.env\.NEXT_PUBLIC_/);
    }
  });

  it("every BFF mutation goes through the shared CSRF and session guard", () => {
    const bff = files.find(({ path }) => path === "lib/server/bff.ts")!.text;
    expect(bff).toMatch(/isSameOriginRequest\(request, config\)/);
    expect(bff).toMatch(/sessionFromRequest\(request, config/);
    // The reads (M2-04: an older page of the case history; M2-04C: a Case's
    // templates and one template's form) are GET-only.
    const reads = {
      "app/bff/companies/[companyId]/cases/[caseId]/history/route.ts": "handleHistoryPage",
      "app/bff/companies/[companyId]/cases/[caseId]/documents/route.ts": "handleDocumentsList",
      "app/bff/companies/[companyId]/cases/[caseId]/documents/[templateKey]/route.ts": "handleDocumentForm",
    };
    const routes = files.filter(({ path }) => path.startsWith("app/bff/") && !(path in reads));
    expect(routes.map(({ path }) => path).sort()).toEqual([
      "app/bff/companies/[companyId]/blueprint/route.ts",
      "app/bff/companies/[companyId]/cases/[caseId]/decisions/[recordId]/corrections/route.ts",
      "app/bff/companies/[companyId]/cases/[caseId]/decisions/route.ts",
      "app/bff/companies/[companyId]/cases/[caseId]/documents/[templateKey]/preview/route.ts",
      "app/bff/companies/[companyId]/cases/[caseId]/progression/pathway/route.ts",
      "app/bff/companies/[companyId]/cases/[caseId]/progression/transitions/route.ts",
      "app/bff/companies/[companyId]/cases/[caseId]/steps/[stepKey]/answers/route.ts",
      "app/bff/companies/[companyId]/workflows/[workflowKey]/cases/route.ts",
      "app/bff/registrations/route.ts",
    ]);
    for (const { path, text } of routes) {
      expect(text, path).toMatch(
        /handle(Registration|BlueprintUpdate|CaseCreate|AnswersSave|PathwaySelect|TransitionRequest|DecisionRecord|DecisionCorrection|DocumentPreview)\(request/,
      );
      expect(text, path).not.toMatch(/export async function GET/);
    }
    for (const [path, handler] of Object.entries(reads)) {
      const text = files.find((file) => file.path === path)!.text;
      expect(text, path).toMatch(/export async function GET/);
      expect(text, path).not.toMatch(/export async function (POST|PUT|PATCH|DELETE)/);
      expect(text, path).toMatch(new RegExp(`${handler}\\(request`));
    }
    // The reads check the origin and the session themselves (they have no body to guard).
    const history = bff.slice(bff.indexOf("export async function handleHistoryPage"));
    expect(history).toMatch(/^[\s\S]*?isSameOriginRequest\(request, config\)[\s\S]*?sessionFromRequest\(request, config/);
    const guardRead = bff.slice(bff.indexOf("function guardRead"));
    expect(guardRead).toMatch(/^[\s\S]*?isSameOriginRequest\(request, config\)[\s\S]*?sessionFromRequest\(request, config/);
    for (const handler of ["handleDocumentsList", "handleDocumentForm"]) {
      const body = bff.slice(bff.indexOf(`export async function ${handler}`));
      expect(body, handler).toMatch(/^[^}]*?guardRead\(request, config, deps\)/);
    }
    // The preview (a POST, so personal details never travel in a URL) goes through the shared guard.
    const preview = bff.slice(bff.indexOf("export async function handleDocumentPreview"));
    expect(preview).toMatch(/^[\s\S]*?await guard\(request, config, deps, MAX_PREVIEW_BYTES\)/);
  });

  it("nothing renders an HTML string or runs code from text", () => {
    // Previews are structured text blocks rendered as text nodes (M2-04C).
    for (const { path, text } of files) {
      expect(text, path).not.toMatch(/dangerouslySetInnerHTML|\.innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function\(/);
    }
  });

  it("document previews are never downloaded, sent, stored or issued (M2-04C)", () => {
    const documentFiles = files.filter(({ path }) => /components\/cases\/document|lib\/documents\//.test(path));
    expect(documentFiles.length).toBeGreaterThanOrEqual(6);
    for (const { path, text } of documentFiles) {
      expect(text, path).not.toMatch(/createObjectURL|new Blob|\bdownload=|mailto:|window\.print|navigator\.clipboard|sendBeacon/);
    }
    // Typed details aren't remembered by the browser's autofill either.
    const form = files.find(({ path }) => path === "components/cases/document-form.tsx")!.text;
    expect(form).toMatch(/<form[\s\S]*?autoComplete="off"/);
  });

  it("no web source carries or reads workflow rule content (M2-03)", () => {
    // Rules live in a private bundle the API loads server-side; the web app only
    // renders what the API answers for one Case.
    for (const { path, text } of files) {
      expect(text, path).not.toMatch(/heroos\.rule-bundle|rule_bundles|\b(start|complete|select)_rules\b|HEROOS_RULE_BUNDLE/);
    }
  });

  it("no web source carries or reads document template content (M2-04C)", () => {
    // Templates live in a private bundle the API loads server-side; the web app
    // only renders one template's form or preview, fetched at run time.
    for (const { path, text } of files) {
      expect(text, path).not.toMatch(/heroos\.template-bundle|template_bundles|HEROOS_TEMPLATE_BUNDLE|source_sha256/);
    }
  });
});
