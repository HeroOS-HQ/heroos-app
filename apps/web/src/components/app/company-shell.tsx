import type { ReactNode } from "react";

import { roleLabel } from "@/lib/onboarding/copy";
import type { Workspace, WorkspaceDetails } from "@/lib/server/heroos-api";
import type { CaseSummary } from "@/lib/workflows/model";

import type { MenuPage } from "./account-menu";
import { WorkspaceLayout } from "./workspace-chrome";
import { WorkspaceHeader, type WorkspaceHeaderData } from "./workspace-header";

/** The header's data for one Company: everything in it is the API's answer for this account. */
export function workspaceHeaderData(
  details: WorkspaceDetails,
  workspaces: Workspace[],
  cases: CaseSummary[] | null,
): WorkspaceHeaderData {
  const { company, membership } = details;
  // The list always includes the open Company; more than one means there is somewhere to switch to.
  const others = workspaces.filter((item) => item.companyId !== company.id).length;
  return {
    companyId: company.id,
    companyName: company.name,
    roleLabel: roleLabel(membership?.role ?? null),
    multipleWorkspaces: others > 0,
    cases,
  };
}

/**
 * The signed-in frame of one Company (approved Oct 20 workspace): the quiet
 * background, the header (HeroOS's mark, Cases, the account menu) and the
 * page. `cases` is the Company's case list for the Cases drawer, given only to
 * those the API lets see cases; `current` marks the account menu's page.
 */
export function CompanyShell({
  details,
  workspaces,
  cases = null,
  current,
  quiet = true,
  initialCasesOpen = false,
  children,
}: {
  details: WorkspaceDetails;
  workspaces: Workspace[];
  cases?: CaseSummary[] | null;
  current?: MenuPage;
  /** Dim the background lights (every page but the empty Ask). */
  quiet?: boolean;
  initialCasesOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <WorkspaceLayout
      header={
        <WorkspaceHeader
          data={workspaceHeaderData(details, workspaces, cases)}
          initialCasesOpen={initialCasesOpen}
          menuCurrent={current}
        />
      }
      quiet={quiet}
    >
      {children}
    </WorkspaceLayout>
  );
}
