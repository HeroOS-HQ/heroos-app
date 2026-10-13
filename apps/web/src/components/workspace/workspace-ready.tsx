import { ArrowRightIcon, CheckIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { buttonPrimary, card, lede, pageTitle } from "@/components/ui/styles";
import type { WorkspaceDetails } from "@/lib/server/heroos-api";

import { JurisdictionStatus } from "./jurisdiction-status";

/**
 * After a confirmed registration only (REGISTRATION_CREATED or
 * REGISTRATION_EXISTING). Everything shown is read back from the API: the
 * Company name, the role and the jurisdiction readiness. Workspace creation
 * is never presented as a legal or jurisdiction confirmation.
 */
export function WorkspaceReady({ details, outcome }: { details: WorkspaceDetails; outcome: "created" | "existing" }) {
  const { company, membership, blueprint } = details;
  const workspaceHref = `/workspaces/${encodeURIComponent(company.id)}`;
  const admin = membership?.role === "company_admin";
  return (
    <div className="mx-auto w-full max-w-[44rem] px-4 py-10 sm:px-6 sm:py-16">
      <section aria-labelledby="ready-heading" className={`${card} px-6 py-9 sm:px-12 sm:py-12`}>
        <span
          aria-hidden="true"
          className="inline-flex size-12 items-center justify-center rounded-full bg-hero-yellow text-hero-navy"
        >
          <CheckIcon className="size-6" />
        </span>
        {outcome === "created" ? (
          <>
            <h1 className={`${pageTitle} mt-5`} id="ready-heading">
              Your workspace is ready
            </h1>
            <p className={`mt-3 ${lede}`}>
              <strong className="font-bold text-hero-navy">{company.name}</strong> is set up on HeroOS
              {admin ? ", and you're its administrator." : "."}
            </p>
          </>
        ) : (
          <>
            <h1 className={`${pageTitle} mt-5`} id="ready-heading">
              You already have a workspace
            </h1>
            <p className={`mt-3 ${lede}`}>
              We found the company workspace you set up earlier:{" "}
              <strong className="font-bold text-hero-navy">{company.name}</strong>.
            </p>
            {/* Also true after a retry of an uncertain first attempt that did create it. */}
            <Notice className="mt-5" title="Your existing workspace wasn't changed">
              Your account can set up one company workspace by itself, so nothing new was created and HeroOS kept the
              details already on record.
              {admin ? " Check them from your workspace and update them if needed." : null}
            </Notice>
          </>
        )}
        {blueprint !== null ? (
          <div className="mt-6">
            <JurisdictionStatus headingLevel={2} jurisdiction={blueprint.jurisdiction} />
          </div>
        ) : null}
        <div className="mt-8">
          <a className={`${buttonPrimary} w-full sm:w-auto`} href={workspaceHref}>
            Open my workspace
            <ArrowRightIcon className="size-4" />
          </a>
        </div>
      </section>
    </div>
  );
}
