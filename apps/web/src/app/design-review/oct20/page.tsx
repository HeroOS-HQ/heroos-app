import { ArrowRightIcon } from "@/components/site/icons";

import { CandidateBrandMark } from "./_mockup/brand";

import { blueprintHref } from "./_mockup/blueprint";
import { BLUEPRINT_STATES } from "./_mockup/blueprint-scenario";
import { finalHref } from "./_mockup/final";
import { spaceHref } from "./_mockup/space";
import { SPACE_STATES } from "./_mockup/space-scenario";
import { FINAL_STATES } from "./_mockup/final-scenario";
import { stateHref, ToneLabel } from "./_mockup/parts";
import { DIRECTION_NAMES, DIRECTIONS, type Tone } from "./_mockup/scenario";

const INVENTORY = [
  {
    page: "1 · Ask HeroOS",
    status: "Approved",
    holds: "The default signed-in page. One question, one box. Every case lives here as a state: the conversation, the four response states, cases, case status.",
  },
  {
    page: "2 · Company Blueprint",
    status: "Approved",
    holds: "Company name, legal name, industry, summary, jurisdiction, existing HR policies, HR context, primary contact, users.",
  },
  {
    page: "3 · Company Space",
    status: "Approved",
    holds: "The evolution of the dashboard: company overview, plan and service entitlement, account and company status.",
  },
];

const NOT_PAGES = [
  ["Dashboard", "Not a page. Its useful parts move to Company Space (Page 3)."],
  ["Cases", "A drawer on Page 1: search, Today, Earlier. Cases only."],
  ["Case page", "The Ask page in conversation: the same surface, opened and named by HeroOS."],
  ["Case status", "A slide-over on Page 1 (a sheet on phones), opened from the case title."],
  ["New-case form, case title", "Gone. HeroOS opens and names every case."],
  ["Expert Review", "A response state with a Request Expert Review action, inside the case."],
  ["Explore HR / HR Services", "Marketing and pre-subscription pages, not the signed-in workspace."],
];

const TONES: { tone: Tone; meaning: string }[] = [
  { tone: "guidance", meaning: "HeroOS guiding and asking: calm blue rule, no panel." },
  { tone: "warning", meaning: "HeroOS warning before you act: amber panel, safe next step." },
  { tone: "stop", meaning: "HeroOS can't proceed with this request: red panel, safe alternatives." },
  { tone: "expert", meaning: "Needs a human HR expert: dark-pink panel, Request Expert Review." },
];

export default function DesignReviewIndex() {
  return (
    <div className="min-h-dvh bg-[#f6f5f2]">
      <header className="border-b border-hero-border bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-4 sm:px-6">
          <CandidateBrandMark />
          <p className="text-[0.875rem] font-semibold text-hero-muted">Design review · all three pages approved in direction · Aries/JJ catch-up, 20 Oct 2026</p>
          <p className="text-[0.8125rem] text-hero-muted sm:ml-auto">Mockup only: not connected to data · final logo subject to JJ</p>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-12 px-4 py-10 sm:px-6" id="main">
        <a
          className="flex flex-wrap items-center justify-between gap-3 rounded-3xl bg-hero-navy px-6 py-5 text-white transition-colors duration-150 hover:bg-[#182c55]"
          href={`/design-review/oct20/jj`}
        >
          <span>
            <span className="block text-lg font-extrabold">JJ review flow</span>
            <span className="block text-[0.9375rem] text-white/75">The nine screens to show, in order, in the clean view; plus the decisions for JJ.</span>
          </span>
          <ArrowRightIcon className="size-5" />
        </a>

        <section>
          <p className="text-[0.75rem] font-bold uppercase tracking-[0.12em] text-hero-success">Page 3 · approved</p>
          <h1 className="mt-1 text-[2rem] font-extrabold leading-tight tracking-[-0.03em] text-hero-navy sm:text-[2.5rem]">Company Space</h1>
          <p className="mt-3 max-w-3xl text-lg leading-relaxed text-hero-muted">
            A calm reference page, not a dashboard: what this company has in HeroOS (access, what is available, Expert Review), the
            Company Blueprint status, and who is signed in. Plan names and limits are mock data until JJ confirms them.
          </p>
          <a
            className="mt-5 inline-flex min-h-12 items-center gap-2 rounded-full bg-hero-navy px-6 font-bold text-white transition-colors duration-150 hover:bg-[#182c55]"
            href={spaceHref("full", false)}
          >
            Open Page 3
            <ArrowRightIcon className="size-4" />
          </a>
          <ol className="mt-6 grid gap-x-6 border-t border-hero-border sm:grid-cols-2">
            {SPACE_STATES.map((s) => (
              <li className="border-b border-hero-border" key={s.key}>
                <a className="group flex items-center gap-3 py-2.5" href={spaceHref(s.key, false, s.anchor)}>
                  <span className="w-10 shrink-0 text-[0.8125rem] font-extrabold text-hero-blue-ink">{s.n}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-bold text-hero-navy group-hover:underline">{s.name}</span>
                    <span className="block text-[0.8125rem] text-hero-muted">{s.note}</span>
                  </span>
                  <ArrowRightIcon className="size-4 shrink-0 text-hero-muted" />
                </a>
              </li>
            ))}
          </ol>
        </section>

        <section>
          <p className="text-[0.75rem] font-bold uppercase tracking-[0.12em] text-hero-success">Page 2 · approved</p>
          <h2 className="mt-1 text-[1.75rem] font-extrabold leading-tight tracking-[-0.03em] text-hero-navy">Company Blueprint</h2>
          <p className="mt-3 max-w-3xl text-lg leading-relaxed text-hero-muted">
            The company context HeroOS uses to tailor its advice: basics and a short summary, jurisdiction, policies, HR support,
            and the people who use HeroOS. Read first, one Edit for everything, and a save bar only when something changed.
          </p>
          <a
            className="mt-5 inline-flex min-h-12 items-center gap-2 rounded-full bg-hero-navy px-6 font-bold text-white transition-colors duration-150 hover:bg-[#182c55]"
            href={blueprintHref("review", false)}
          >
            Open Page 2
            <ArrowRightIcon className="size-4" />
          </a>
          <ol className="mt-6 grid gap-x-6 border-t border-hero-border sm:grid-cols-2">
            {BLUEPRINT_STATES.map((s) => (
              <li className="border-b border-hero-border" key={s.key}>
                <a className="group flex items-center gap-3 py-2.5" href={blueprintHref(s.key, false, s.anchor)}>
                  <span className="w-10 shrink-0 text-[0.8125rem] font-extrabold text-hero-blue-ink">{s.n}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-bold text-hero-navy group-hover:underline">{s.name}</span>
                    <span className="block text-[0.8125rem] text-hero-muted">{s.note}</span>
                  </span>
                  <ArrowRightIcon className="size-4 shrink-0 text-hero-muted" />
                </a>
              </li>
            ))}
          </ol>
        </section>

        <section>
          <p className="text-[0.75rem] font-bold uppercase tracking-[0.12em] text-hero-success">Page 1 · approved</p>
          <h2 className="mt-1 text-[1.75rem] font-extrabold leading-tight tracking-[-0.03em] text-hero-navy">Ask HeroOS: one workspace</h2>
          <p className="mt-3 max-w-3xl text-lg leading-relaxed text-hero-muted">
            Founders arrive and see one thing: <strong className="text-hero-navy">“What can HR do for you today?”</strong> They explain the
            situation in their own words. HeroOS opens and names the case, asks only what it needs, and answers in four labelled states.
          </p>
          <a
            className="mt-5 inline-flex min-h-12 items-center gap-2 rounded-full bg-hero-navy px-6 font-bold text-white transition-colors duration-150 hover:bg-[#182c55]"
            href={finalHref("empty", false)}
          >
            Open Page 1
            <ArrowRightIcon className="size-4" />
          </a>
          <ol className="mt-6 grid gap-x-6 border-t border-hero-border sm:grid-cols-2">
            {FINAL_STATES.map((s) => (
              <li className="border-b border-hero-border" key={s.key}>
                <a className="group flex items-center gap-3 py-2.5" href={finalHref(s.key, false)}>
                  <span className="w-10 shrink-0 text-[0.8125rem] font-extrabold text-hero-blue-ink">{s.n}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-bold text-hero-navy group-hover:underline">{s.name}</span>
                    <span className="block text-[0.8125rem] text-hero-muted">{s.note}</span>
                  </span>
                  <ArrowRightIcon className="size-4 shrink-0 text-hero-muted" />
                </a>
              </li>
            ))}
          </ol>
          <p className="mt-3 text-[0.875rem] text-hero-muted">
            Phones: narrow the window below 640 px (or use device mode). Add <code>?clean=1</code> to hide the review bar.
          </p>
        </section>

        <section aria-labelledby="tones">
          <h2 className="text-xl font-extrabold text-hero-navy" id="tones">
            Response states (colour is never the only signal)
          </h2>
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {TONES.map(({ tone, meaning }) => (
              <li className="flex items-center gap-3 rounded-2xl border border-hero-border bg-white px-4 py-3" key={tone}>
                <ToneLabel tone={tone} />
                <span className="text-[0.9375rem] text-hero-navy/85">{meaning}</span>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="later-pages" className="scroll-mt-6" id="later-pages">
          <h2 className="text-xl font-extrabold text-hero-navy">Page inventory: three true pages</h2>
          <p className="mt-1 text-[0.9375rem] text-hero-muted">Account (in the account menu) is a menu entry, not a page; it is not designed.</p>
          <div className="mt-4 overflow-hidden rounded-3xl border border-hero-border bg-white">
            <table className="w-full text-left text-[0.9375rem]">
              <thead className="bg-hero-navy/[0.03] text-[0.8125rem] uppercase tracking-[0.08em] text-hero-muted">
                <tr>
                  <th className="px-5 py-3 font-bold">Page</th>
                  <th className="px-5 py-3 font-bold">Status</th>
                  <th className="hidden px-5 py-3 font-bold md:table-cell">Holds</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hero-border">
                {INVENTORY.map((row) => (
                  <tr key={row.page}>
                    <td className="px-5 py-3 font-extrabold text-hero-navy">{row.page}</td>
                    <td className="px-5 py-3 text-hero-muted">{row.status}</td>
                    <td className="hidden px-5 py-3 text-hero-navy/85 md:table-cell">{row.holds}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3 className="mt-6 font-extrabold text-hero-navy">States, panels and drawers (not pages)</h3>
          <dl className="mt-2 grid gap-x-6 gap-y-2 text-[0.9375rem] sm:grid-cols-[13rem_1fr]">
            {NOT_PAGES.map(([term, detail]) => (
              <div className="contents" key={term}>
                <dt className="font-bold text-hero-navy">{term}</dt>
                <dd className="text-hero-muted">{detail}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section aria-labelledby="archive" className="rounded-3xl border border-dashed border-hero-control/60 px-5 py-4">
          <h2 className="font-extrabold text-hero-navy" id="archive">
            Round 1 archive (superseded)
          </h2>
          <p className="mt-1 text-[0.9375rem] text-hero-muted">
            Kept for reference only. Direction A became the final above; Direction B was not chosen.
          </p>
          <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[0.9375rem]">
            {DIRECTIONS.map((d) => (
              <li key={d}>
                <a className="font-semibold text-hero-blue-ink underline-offset-4 hover:underline" href={stateHref(d, "empty", { clean: false, rail: true })}>
                  Direction {d.toUpperCase()} · {DIRECTION_NAMES[d].name}
                </a>
              </li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  );
}
