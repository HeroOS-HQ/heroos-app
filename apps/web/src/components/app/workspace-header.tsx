"use client";

import { type ReactNode, useCallback, useRef, useState, useSyncExternalStore } from "react";

import { WorkspaceBrandMark } from "@/components/site/brand-mark";
import { ClockIcon } from "@/components/site/icons";
import type { CaseSummary } from "@/lib/workflows/model";

import { AccountMenu, type MenuPage } from "./account-menu";
import { CasesPanel } from "./cases-panel";
import { ghostButton } from "./workspace-chrome";

const noSubscription = () => () => {};

/** What the header needs, all of it the API's answer for this account and Company. */
export type WorkspaceHeaderData = {
  companyId: string;
  companyName: string;
  /** The account's role here, in words. */
  roleLabel: string | null;
  /** The account can open more than one workspace. */
  multipleWorkspaces: boolean;
  /** The Company's cases; null when the account can't see cases (members), so there is no Cases control. */
  cases: CaseSummary[] | null;
};

/**
 * The workspace header (approved design): HeroOS's mark (back to Ask
 * HeroOS) and the Cases control on the left, the page's own centre (the open
 * case on a case page), and the account menu on the right. No permanent
 * navigation: the Blueprint and Company Space are in the account menu.
 */
export function WorkspaceHeader({
  data,
  menuCurrent,
  currentCaseId,
  initialCasesOpen = false,
  center,
  actions,
}: {
  data: WorkspaceHeaderData;
  menuCurrent?: MenuPage;
  currentCaseId?: string;
  /** Open the Cases drawer once the page has loaded (`?cases=open`). */
  initialCasesOpen?: boolean;
  center?: ReactNode;
  actions?: ReactNode;
}) {
  // null: not touched yet, so `?cases=open` decides. The drawer only ever renders in the
  // browser (after hydration): it groups cases by the viewer's own "today".
  const [chosen, setChosen] = useState<boolean | null>(null);
  const hydrated = useSyncExternalStore(noSubscription, () => true, () => false);
  const casesOpen = data.cases !== null && hydrated && (chosen ?? initialCasesOpen);
  const closeCases = useCallback(() => setChosen(false), []);
  const casesButton = useRef<HTMLButtonElement>(null);
  const ask = `/workspaces/${encodeURIComponent(data.companyId)}`;

  return (
    <>
      <header className="sticky top-0 z-30 grid h-16 shrink-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 bg-[#fbfaf8]/85 px-2 backdrop-blur-md sm:grid-cols-[1fr_auto_1fr] sm:px-5">
        <div className="flex items-center gap-1 sm:gap-1.5">
          <a aria-label="HeroOS: ask a new question" className="hidden min-h-11 items-center rounded-lg px-1 sm:inline-flex" href={ask}>
            <WorkspaceBrandMark />
          </a>
          {data.cases !== null ? (
            <>
              <span aria-hidden="true" className="mx-1.5 hidden h-5 w-px bg-hero-navy/15 sm:block" />
              <button
                aria-expanded={casesOpen}
                aria-haspopup="dialog"
                aria-label="Cases"
                className={ghostButton}
                onClick={() => setChosen(true)}
                ref={casesButton}
                type="button"
              >
                <ClockIcon className="size-5" />
                <span className="hidden sm:inline">Cases</span>
              </button>
            </>
          ) : null}
        </div>

        <div className="flex min-w-0 justify-center">
          {center ?? (
            <a aria-label="HeroOS: ask a new question" className="inline-flex min-h-11 items-center sm:hidden" href={ask}>
              <WorkspaceBrandMark />
            </a>
          )}
        </div>

        <div className="flex items-center justify-end gap-1">
          {actions}
          <AccountMenu
            companyId={data.companyId}
            companyName={data.companyName}
            current={menuCurrent}
            multipleWorkspaces={data.multipleWorkspaces}
            roleLabel={data.roleLabel}
          />
        </div>
      </header>
      {casesOpen && data.cases !== null ? (
        <CasesPanel
          cases={data.cases}
          companyId={data.companyId}
          currentCaseId={currentCaseId}
          onClose={closeCases}
          returnTo={casesButton}
        />
      ) : null}
    </>
  );
}
