import { ArrowRightIcon } from "@/components/site/icons";

import { CandidateBrandMark } from "../_mockup/brand";

import { blueprintHref } from "../_mockup/blueprint";
import { finalHref } from "../_mockup/final";
import { spaceHref } from "../_mockup/space";

/**
 * The JJ review flow (20 Oct 2026): the three logged-in pages, the nine
 * screens to show in order, a few more if asked, and the open decisions.
 * Every link opens the clean view (no review bar, no internal notes).
 */

const PAGES = [
  {
    name: "Ask HeroOS",
    line: "The main workspace. Founders explain an HR situation in their own words; HeroOS opens and names the case, asks what it needs, and guides, warns, stops or suggests Expert Review.",
  },
  {
    name: "Company Blueprint",
    line: "The company context HeroOS uses when advising: company basics, jurisdiction, policies, HR support and people.",
  },
  {
    name: "Company Space",
    line: "A light overview of the company's HeroOS access, what is available to it, and the Blueprint's status.",
  },
];

const WALKTHROUGH = [
  { page: "Ask HeroOS", title: "Empty", href: finalHref("empty", true), notice: "One question, one box. Nothing to learn first." },
  { page: "Ask HeroOS", title: "Active conversation", href: finalHref("conversation", true), notice: "HeroOS opens and names the case, then asks only what it needs." },
  { page: "Ask HeroOS", title: "Warning", href: finalHref("warning", true), notice: "Amber means HeroOS is warning you, with a safe next step." },
  { page: "Ask HeroOS", title: "Expert Review", href: finalHref("expert", true), notice: "Outside the playbooks, HeroOS says a human is needed. Nothing is sent until the founder chooses." },
  { page: "Ask HeroOS", title: "Case status", href: finalHref("status", true), notice: "Where the case stands and what's next, out of the way until opened." },
  { page: "Company Blueprint", title: "Review", href: blueprintHref("review", true), notice: "What HeroOS knows about the company, on one sheet." },
  { page: "Company Blueprint", title: "Edit", href: blueprintHref("edit", true), notice: "One Edit for everything; Save appears only after a change." },
  { page: "Company Space", title: "Full access", href: spaceHref("full", true), notice: "What the company has in HeroOS, at a glance." },
  { page: "Company Space", title: "Limited access", href: spaceHref("limited", true), notice: "Case-based access: one case, and which case uses it." },
];

const MORE = [
  { label: "Ask HeroOS · Block (shown as “Stop”)", href: finalHref("block", true) },
  { label: "Ask HeroOS · Cases drawer", href: finalHref("cases", true) },
  { label: "Ask HeroOS · Opening a case", href: finalHref("opening", true) },
  { label: "Ask HeroOS · Previous case reopened", href: finalHref("reopened", true) },
  { label: "Company Blueprint · Unsaved changes", href: blueprintHref("unsaved", true) },
  { label: "Company Blueprint · Saved", href: blueprintHref("saved", true) },
  { label: "Company Blueprint · Missing information", href: blueprintHref("incomplete", true) },
  { label: "Company Blueprint · No policies yet", href: blueprintHref("no-policies", true, "policies") },
  { label: "Company Space · Blueprint needs attention", href: spaceHref("attention", true, "blueprint") },
  { label: "Company Space · Expert Review not included", href: spaceHref("no-expert", true, "expert-review") },
];

const SOON = [
  ["Page 3's name", "“Company Space”, or the company's own name (“Bush & Bush space”)."],
  ["Final logo", "The mockups use the current approved logo."],
  ["Headline", "“What can HR do for you today?” or “What can HeroOS do for you today?”"],
  ["Access model", "Package names; what case access and full access include; what happens after the included case."],
  ["Expert Review", "What each package includes, and what happens after Request Expert Review (who replies, when it becomes paid consultancy)."],
  ["Stop and Expert Review colours", "Two shades (red for Stop, dark pink for Expert Review), or one shared “stop and escalate” colour."],
];

const LATER = [
  "Supported jurisdictions (and the licensing authorities under them).",
  "How policy documents are handled over time.",
  "With several logins, who sees which cases; final user roles and permissions.",
  "What the 30-day comment means (the mockups show nothing about it).",
  "Where billing and account settings live.",
  "Company summary length; Blueprint saving (explicit Save today, or automatic).",
  "“In your own language”: plain words, or other languages such as Arabic.",
];

const link = "font-bold text-hero-blue-ink underline-offset-4 hover:underline";

export default function JJReview() {
  return (
    <div className="min-h-dvh bg-[#f6f5f2]">
      <header className="border-b border-hero-border bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-4 sm:px-6">
          <CandidateBrandMark />
          <p className="text-[0.875rem] font-semibold text-hero-muted">Signed-in product · review with JJ</p>
          <p className="text-[0.8125rem] text-hero-muted sm:ml-auto">Mockups with demo data · not connected to the product</p>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-12 px-4 py-10 sm:px-6" id="main">
        <section aria-labelledby="structure">
          <h1 className="text-[2rem] font-extrabold leading-tight tracking-[-0.03em] text-hero-navy sm:text-[2.5rem]" id="structure">
            Three pages. One main task.
          </h1>
          <p className="mt-2 max-w-3xl text-lg leading-relaxed text-hero-muted">
            Founders tell HeroOS what is happening; HeroOS handles the HR process. Everything else is a panel or a state of these
            three pages.
          </p>
          <ol className="mt-6 divide-y divide-hero-border rounded-3xl border border-hero-border bg-white">
            {PAGES.map((page, index) => (
              <li className="grid gap-1 px-5 py-4 sm:grid-cols-[13rem_1fr] sm:gap-6" key={page.name}>
                <p className="font-extrabold text-hero-navy">
                  <span className="mr-2 text-hero-blue-ink">{index + 1}</span>
                  {page.name}
                </p>
                <p className="text-[0.9375rem] leading-relaxed text-hero-navy/80">{page.line}</p>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="walkthrough">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <h2 className="text-xl font-extrabold text-hero-navy" id="walkthrough">
              Walkthrough for the call
            </h2>
            <a
              className="inline-flex min-h-11 items-center gap-2 rounded-full bg-hero-navy px-5 font-bold text-white transition-colors duration-150 hover:bg-[#182c55]"
              href={WALKTHROUGH[0].href}
            >
              Start with screen 1
              <ArrowRightIcon className="size-4" />
            </a>
          </div>
          <ol className="mt-4 divide-y divide-hero-border rounded-3xl border border-hero-border bg-white">
            {WALKTHROUGH.map((screen, index) => (
              <li key={screen.href}>
                <a className="group grid items-center gap-x-4 gap-y-0.5 px-5 py-3.5 sm:grid-cols-[2rem_15rem_1fr_auto]" href={screen.href}>
                  <span className="text-[0.875rem] font-extrabold text-hero-blue-ink">{index + 1}</span>
                  <span className="font-bold text-hero-navy group-hover:underline">
                    {screen.page} <span className="font-semibold text-hero-muted">· {screen.title}</span>
                  </span>
                  <span className="text-[0.9375rem] text-hero-navy/75">{screen.notice}</span>
                  <ArrowRightIcon className="size-4 text-hero-muted max-sm:hidden" />
                </a>
              </li>
            ))}
          </ol>
          <h3 className="mt-6 font-extrabold text-hero-navy">More states, if JJ asks</h3>
          <ul className="mt-2 grid gap-x-6 gap-y-1.5 text-[0.9375rem] sm:grid-cols-2">
            {MORE.map((item) => (
              <li key={item.href}>
                <a className={link} href={item.href}>
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="decisions">
          <h2 className="text-xl font-extrabold text-hero-navy" id="decisions">
            Decisions for JJ
          </h2>
          <div className="mt-4 grid gap-5 md:grid-cols-2">
            <div className="rounded-3xl border border-hero-border bg-white px-5 py-4">
              <h3 className="text-[0.75rem] font-bold uppercase tracking-[0.12em] text-[#8a4a00]">Confirm soon</h3>
              <dl className="mt-3 space-y-3">
                {SOON.map(([term, detail]) => (
                  <div key={term}>
                    <dt className="font-bold text-hero-navy">{term}</dt>
                    <dd className="text-[0.9375rem] leading-relaxed text-hero-navy/75">{detail}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <div className="rounded-3xl border border-hero-border bg-white px-5 py-4">
              <h3 className="text-[0.75rem] font-bold uppercase tracking-[0.12em] text-hero-muted">Can confirm later</h3>
              <ul className="mt-3 list-disc space-y-2 pl-5 text-[0.9375rem] leading-relaxed text-hero-navy/80">
                {LATER.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
