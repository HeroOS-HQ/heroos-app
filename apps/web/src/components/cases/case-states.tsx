import type { ReactNode } from "react";

import { AppShell } from "@/components/app/app-shell";
import {
  AccessDeniedView,
  ApiUnavailableView,
  NotConfiguredView,
  SessionExpiredView,
  SignedOutView,
} from "@/components/app/state-views";
import { StatePanel } from "@/components/ui/state-panel";
import { buttonPrimary, buttonQuiet } from "@/components/ui/styles";
import type { CaseState, CasesState } from "@/lib/server/app-state";
import type { Workspace, WorkspaceDetails } from "@/lib/server/heroos-api";

type Ready = { details: WorkspaceDetails; workspaces: Workspace[] };

/** The signed-in frame for one Company (switcher, sign-out). */
export function CompanyShell({ details, workspaces, children }: Ready & { children: ReactNode }) {
  return (
    <AppShell
      context={details.company.name}
      switcher={{
        currentId: details.company.id,
        items: workspaces.map(({ companyId, name }) => ({ companyId, name })),
      }}
    >
      {children}
    </AppShell>
  );
}

/** The full-page states every Case page shares; null when the page has data to render. */
export function commonStateView(state: CasesState | CaseState, retryHref: string): ReactNode | null {
  switch (state.kind) {
    case "not_configured":
      return <NotConfiguredView />;
    case "signed_out":
      return <SignedOutView />;
    case "session_expired":
      return <SessionExpiredView />;
    case "access_denied":
      return <AccessDeniedView />;
    case "api_unavailable":
      return <ApiUnavailableView retryHref={retryHref} />;
    case "admin_only":
      return <AdminOnlyView details={state.details} workspaces={state.workspaces} />;
    case "workflow_unavailable":
      return (
        <CompanyShell details={state.details} workspaces={state.workspaces}>
          <StatePanel
            actions={
              <a className={buttonPrimary} href={`/workspaces/${encodeURIComponent(state.details.company.id)}`}>
                Back to your workspace
              </a>
            }
            role="status"
            title="Disciplinary cases aren't available here yet"
          >
            <p>The HeroOS service this workspace uses doesn&apos;t offer guided Disciplinary cases yet.</p>
          </StatePanel>
        </CompanyShell>
      );
    default:
      return null;
  }
}

/**
 * ADMIN_ONLY (M2-01 interim policy): Disciplinary Cases are confidential and
 * open only to Company administrators until dedicated HR access roles are
 * approved. Nothing about any Case is shown or was requested.
 */
export function AdminOnlyView({ details, workspaces }: Ready) {
  return (
    <CompanyShell details={details} workspaces={workspaces}>
      <StatePanel
        actions={
          <a className={buttonPrimary} href={`/workspaces/${encodeURIComponent(details.company.id)}`}>
            Back to your workspace
          </a>
        }
        role="status"
        title="Disciplinary cases are for company administrators"
      >
        <p>
          Disciplinary cases are confidential. For now, only your company&apos;s administrators can see or work on them.
        </p>
      </StatePanel>
    </CompanyShell>
  );
}

/** CASE_NOT_FOUND: identical for a Case of another Company and one that doesn't exist. */
export function CaseNotFoundView({ details, workspaces }: Ready) {
  const casesHref = `/workspaces/${encodeURIComponent(details.company.id)}/cases`;
  return (
    <CompanyShell details={details} workspaces={workspaces}>
      <StatePanel
        actions={
          <>
            <a className={buttonPrimary} href={casesHref}>
              See Disciplinary cases
            </a>
            <a className={buttonQuiet} href={`/workspaces/${encodeURIComponent(details.company.id)}`}>
              Back to your workspace
            </a>
          </>
        }
        role="alert"
        title="This case can't be opened"
      >
        <p>It doesn&apos;t exist, isn&apos;t a guided case, or isn&apos;t available to you in this workspace.</p>
      </StatePanel>
    </CompanyShell>
  );
}
