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
      "components/cases/case-workspace.tsx",
      "components/cases/new-case-form.tsx",
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
    const routes = files.filter(({ path }) => path.startsWith("app/bff/"));
    expect(routes.map(({ path }) => path).sort()).toEqual([
      "app/bff/companies/[companyId]/blueprint/route.ts",
      "app/bff/companies/[companyId]/cases/[caseId]/steps/[stepKey]/answers/route.ts",
      "app/bff/companies/[companyId]/workflows/[workflowKey]/cases/route.ts",
      "app/bff/registrations/route.ts",
    ]);
    for (const { path, text } of routes) {
      expect(text, path).toMatch(/handle(Registration|BlueprintUpdate|CaseCreate|AnswersSave)\(request/);
      expect(text, path).not.toMatch(/export async function GET/);
    }
  });
});
