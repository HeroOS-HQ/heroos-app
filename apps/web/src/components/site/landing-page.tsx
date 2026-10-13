import { ClosingCta } from "./closing-cta";
import { HeroSection } from "./hero-section";
import { PlatformFoundation } from "./platform-foundation";
import { SiteFooter } from "./site-footer";
import { SiteHeader } from "./site-header";
import { WorkflowJourney } from "./workflow-journey";

/** Signed-out homepage. `notice` carries a fixed sign-in outcome or configuration message. */
export function LandingPage({ notice }: { notice?: { text: string; role: "alert" | "status" } }) {
  return (
    <>
      <SiteHeader variant="landing" />
      {notice ? (
        <p className="border-b border-hero-border bg-hero-yellow-tint px-5 py-3 text-center text-sm font-medium" role={notice.role}>
          {notice.text}
        </p>
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
