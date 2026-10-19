import type { ReactNode } from "react";

import { roleLabel } from "@/lib/onboarding/copy";
import type { Workspace, WorkspaceDetails } from "@/lib/server/heroos-api";

import { CompanyFrame, type CompanySection } from "./company-frame";

/**
 * The signed-in frame of one Company (header, identity or switcher, sign-out
 * and the company navigation). Everything it shows is the API's answer for
 * this Company: its name, the account's role, and the Companies the account
 * may open. `mode="case"` leaves the side to the Case workspace's own list.
 */
export function CompanyShell({
  details,
  workspaces,
  current,
  mode = "standard",
  children,
}: {
  details: WorkspaceDetails;
  workspaces: Workspace[];
  current?: CompanySection;
  mode?: "standard" | "case";
  children: ReactNode;
}) {
  const { company, membership } = details;
  // The list always includes the open Company (its name from the Company's own answer).
  const companies = workspaces.some((item) => item.companyId === company.id)
    ? workspaces.map(({ companyId, name }) => ({ companyId, name }))
    : [{ companyId: company.id, name: company.name }];
  return (
    <CompanyFrame
      admin={membership?.role === "company_admin"}
      companies={companies}
      companyId={company.id}
      companyName={company.name}
      current={current}
      mode={mode}
      role={roleLabel(membership?.role ?? null)}
    >
      {children}
    </CompanyFrame>
  );
}
