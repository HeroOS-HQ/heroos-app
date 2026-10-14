import { ClosingCta } from "./closing-cta";
import { HeroSection } from "./hero-section";
import { PlatformFoundation } from "./platform-foundation";
import { SiteFooter } from "./site-footer";
import { SiteHeader } from "./site-header";
import { WorkflowJourney } from "./workflow-journey";

type Notice = {
  text: string;
  role: "alert" | "status";
  /**
   * After a denied sign-in (e-mail not verified): a way back in once verified,
   * and a way out of the provider's remembered session to use another account.
   */
  accountActions?: boolean;
};

const noticeAction =
  "inline-flex min-h-11 items-center font-bold text-hero-blue-ink underline-offset-4 hover:underline";

/** Signed-out homepage. `notice` carries a fixed sign-in outcome or configuration message. */
export function LandingPage({ notice }: { notice?: Notice }) {
  return (
    <>
      <SiteHeader variant="landing" />
      {notice ? (
        <div className="border-b border-hero-border bg-hero-yellow-tint px-5 py-3 text-center text-sm font-medium" role={notice.role}>
          <p>{notice.text}</p>
          {notice.accountActions ? (
            <div className="mt-1 flex flex-wrap items-center justify-center gap-x-4">
              <a className={noticeAction} href="/auth/login">
                Sign in again
              </a>
              {/* POST-only sign-out also ends the provider session (the route refuses cross-site requests). */}
              <form action="/auth/logout" method="post">
                <button className={noticeAction} type="submit">
                  Use a different account
                </button>
              </form>
            </div>
          ) : null}
        </div>
      ) : null}
      <main className="flex-1">
        <HeroSection />
        <WorkflowJourney />
        <PlatformFoundation />
        <ClosingCta />
      </main>
      <SiteFooter />
    </>
  );
}
