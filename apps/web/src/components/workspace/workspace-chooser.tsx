import { ArrowRightIcon, BuildingIcon } from "@/components/site/icons";
import { StatusBadge } from "@/components/ui/status-badge";
import { lede, pageTitle } from "@/components/ui/styles";
import { roleLabel } from "@/lib/onboarding/copy";
import type { Workspace } from "@/lib/server/heroos-api";

/**
 * WORKSPACE_SELECTION: only the Companies the API listed for this user. Each
 * link is a full page load; the destination is authorized again by the API.
 */
export function WorkspaceChooser({ workspaces }: { workspaces: Workspace[] }) {
  return (
    <div className="mx-auto w-full max-w-[48rem] px-4 py-10 sm:px-6 sm:py-16">
      <h1 className={pageTitle}>Choose a workspace</h1>
      <p className={`mt-3 ${lede}`}>Your account can open these company workspaces.</p>
      <ul aria-label="Your workspaces" className="mt-8 flex flex-col gap-3">
        {workspaces.map((workspace) => {
          const role = roleLabel(workspace.role);
          return (
            <li key={workspace.companyId}>
              <a
                className="group flex min-h-20 items-center gap-4 rounded-2xl border border-hero-border bg-white px-4 py-4 shadow-hero-card transition-[box-shadow,transform] duration-200 hover:-translate-y-px hover:shadow-hero-card-hover sm:px-6"
                href={`/workspaces/${encodeURIComponent(workspace.companyId)}`}
              >
                <span className="inline-flex size-11 shrink-0 items-center justify-center rounded-xl bg-hero-blue-tint text-hero-blue">
                  <BuildingIcon className="size-6" />
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-1 sm:flex-row sm:items-center sm:gap-3">
                  <span className="min-w-0 break-words text-base font-extrabold text-hero-navy">{workspace.name}</span>
                  {role ? (
                    <span>
                      <StatusBadge tone={workspace.role === "company_admin" ? "positive" : "neutral"}>{role}</StatusBadge>
                    </span>
                  ) : null}
                </span>
                <ArrowRightIcon className="size-5 shrink-0 text-hero-blue transition-transform duration-200 group-hover:translate-x-0.5" />
              </a>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
