import type { ReactNode, Ref } from "react";

import {
  ArrowRightIcon,
  BuildingIcon,
  CertificateIcon,
  ChecklistIcon,
  DocumentIcon,
  InfoIcon,
  MonitorIcon,
  RocketIcon,
  SparkleIcon,
  UserIcon,
} from "@/components/site/icons";

import { AccentTitle, OnboardingCanvas } from "./onboarding-frame";

const MILESTONES: { title: string; body: string; icon: ReactNode }[] = [
  {
    title: "Company Basics",
    body: "Tell us your company's name and, if you like, a little about how it works.",
    icon: <BuildingIcon className="size-12 stroke-[1.5] sm:size-14" />,
  },
  {
    title: "Jurisdiction",
    body: "Tell us where your business licence was issued. Your jurisdiction is confirmed separately.",
    icon: <CertificateIcon className="size-12 stroke-[1.5] sm:size-14" />,
  },
  {
    title: "Company Blueprint Review",
    body: "Check everything and edit any step. Nothing is saved before you confirm.",
    icon: <ChecklistIcon className="size-12 stroke-[1.5] sm:size-14" />,
  },
  {
    title: "Workspace Ready",
    body: "Create your workspace and open it straight away.",
    icon: <MonitorIcon className="size-12 stroke-[1.5] sm:size-14" />,
  },
];

const NEXT: { title: string; body: string; icon: ReactNode }[] = [
  {
    title: "Set up your company profile",
    body: "Share your company's name and any optional details. Only the name is required.",
    icon: <UserIcon className="size-8 sm:size-9" />,
  },
  {
    title: "Set your jurisdiction",
    body: "Your answer is kept as you give it. Jurisdiction is confirmed separately.",
    icon: <DocumentIcon className="size-8 sm:size-9" />,
  },
  {
    title: "Enter your workspace",
    body: "It's created when you confirm your details, and you can open it straight away.",
    icon: <RocketIcon className="size-8 sm:size-9" />,
  },
];

/**
 * Welcome (JJ design review, screen 01): the first stage of setup, after
 * sign-up. A presentation only: it saves and sends nothing; "Get Started"
 * opens Company Basics. The mockup's "Finish later" is not offered, because
 * unfinished details are not kept anywhere: "Leave setup" says so instead.
 */
export function OnboardingWelcome({
  headingRef,
  notice,
  onStart,
}: {
  headingRef: Ref<HTMLHeadingElement>;
  notice?: ReactNode;
  onStart: () => void;
}) {
  return (
    <OnboardingCanvas>
      <div className="mx-auto w-full max-w-[90rem] px-4 pb-12 sm:px-8 xl:px-14">
        <section aria-labelledby="onboarding-heading" className="relative">
          <WelcomeArt />
          <div className="relative pt-8 sm:pt-12 lg:max-w-[40rem] lg:pb-6 lg:pt-[4.25rem]">
            {notice ? <div className="mb-6">{notice}</div> : null}
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-sm font-bold uppercase tracking-[0.18em] text-hero-muted">Get started</p>
                <span aria-hidden="true" className="mt-2.5 block h-1 w-10 rounded-full bg-hero-yellow" />
              </div>
              {/* Phones and tablets: Hannah, small, beside the eyebrow (decorative). */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                alt=""
                aria-hidden="true"
                className="-mb-16 -mt-4 h-auto w-24 shrink-0 sm:w-32 lg:hidden"
                height={900}
                src="/branding/hannah-hero-front.webp"
                width={600}
              />
            </div>
            <AccentTitle
              accent="HeroOS"
              className="mt-6 text-[2.5rem] leading-[1.05] tracking-[-0.04em] sm:text-[3.25rem] xl:text-[3.75rem]"
              headingRef={headingRef}
              id="onboarding-heading"
              lead="Welcome to"
            />
            <p className="mt-5 max-w-[36rem] text-lg leading-[1.55] text-hero-muted xl:text-[1.375rem]">
              We&apos;ll guide you through a short setup to describe your company and create its HeroOS workspace, so
              you can start strong.
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-10">
              <button
                className="inline-flex min-h-[3.75rem] items-center justify-center gap-3 rounded-2xl bg-hero-yellow px-12 text-[1.25rem] font-bold text-hero-navy shadow-[0_10px_24px_-12px_rgb(255_212_1/0.95)] transition-[box-shadow,transform,background-color] duration-200 hover:-translate-y-px hover:bg-[#f6cb00] focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-hero-blue"
                id="onboarding-start"
                onClick={onStart}
                type="button"
              >
                Get Started
                <ArrowRightIcon className="size-5 stroke-[2.25]" />
              </button>
              {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- a full page load, so the unsaved-details warning applies */}
              <a
                className="inline-flex min-h-11 items-center justify-center rounded-lg px-1 text-[1.0625rem] font-semibold text-hero-navy underline underline-offset-[6px] hover:text-hero-blue-ink focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-hero-blue"
                href="/workspaces"
              >
                Leave setup
              </a>
            </div>
          </div>
        </section>

        <ol aria-label="Setup steps" className="relative z-10 mt-12 grid gap-4 sm:grid-cols-2 lg:mt-0 lg:grid-cols-4 lg:gap-[1.875rem]">
          {MILESTONES.map((milestone, position) => (
            <li
              className="relative flex flex-col items-center rounded-[1.125rem] border border-hero-border/60 bg-white px-5 pb-6 pt-5 text-center shadow-[0_1px_2px_rgb(14_30_61/0.04),0_14px_30px_-20px_rgb(14_30_61/0.25)] lg:min-h-[17.375rem]"
              key={milestone.title}
            >
              <span
                aria-hidden="true"
                className="absolute left-4 top-4 inline-flex size-11 items-center justify-center rounded-full bg-hero-yellow-tint text-lg font-bold text-hero-navy sm:left-5 sm:top-5 sm:size-12 sm:text-xl"
              >
                {position + 1}
              </span>
              <span aria-hidden="true" className="relative flex size-24 items-center justify-center rounded-full bg-hero-blue-tint text-hero-navy sm:size-[6.5rem]">
                {milestone.icon}
                <SparkleIcon className="absolute bottom-3 right-2.5 size-5 text-hero-yellow" />
              </span>
              <h2 className="mt-3.5 text-[1.1875rem] font-extrabold leading-[1.2] text-hero-navy sm:text-xl">
                <span className="sr-only">Step {position + 1}: </span>
                {milestone.title}
              </h2>
              <p className="mt-2 max-w-[16rem] text-base leading-[1.45] text-hero-muted xl:text-[1.0625rem]">{milestone.body}</p>
              {position < MILESTONES.length - 1 ? (
                <ArrowRightIcon className="absolute -right-[1.45rem] top-[7rem] hidden size-5 text-hero-muted lg:block" />
              ) : null}
            </li>
          ))}
        </ol>

        <section
          aria-labelledby="onboarding-next-heading"
          className="mt-5 rounded-[1.125rem] border border-hero-border/60 bg-white px-5 pb-4 pt-6 shadow-[0_1px_2px_rgb(14_30_61/0.04),0_14px_30px_-20px_rgb(14_30_61/0.25)] sm:px-9"
        >
          <h2 className="text-[1.625rem] font-extrabold tracking-[-0.02em] text-hero-navy xl:text-[1.875rem]" id="onboarding-next-heading">
            What happens next
          </h2>
          <span aria-hidden="true" className="mt-2.5 block h-1 w-10 rounded-full bg-hero-yellow" />
          <ul className="mt-6 grid gap-6 lg:grid-cols-3 lg:gap-0 lg:divide-x lg:divide-hero-border">
            {NEXT.map((item) => (
              <li className="flex items-center gap-5 lg:px-6 lg:first:pl-0 lg:last:pr-0" key={item.title}>
                <span
                  aria-hidden="true"
                  className="inline-flex size-16 shrink-0 items-center justify-center rounded-full bg-hero-yellow-tint text-hero-navy sm:size-[5.25rem]"
                >
                  {item.icon}
                </span>
                <span className="min-w-0">
                  <span className="block text-[1.0625rem] font-bold text-hero-navy">{item.title}</span>
                  <span className="mt-1 block text-[0.9375rem] leading-relaxed text-hero-muted">{item.body}</span>
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-6 flex items-center gap-4 border-t border-hero-border pt-4">
            <span aria-hidden="true" className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-hero-blue-tint text-hero-blue">
              <InfoIcon className="size-5" />
            </span>
            <p className="text-[0.9375rem] leading-relaxed text-hero-muted sm:text-base">
              Need to step away? You can leave at any time, but what you enter here isn&apos;t saved until you create
              your workspace, so you&apos;d start again next time.
            </p>
          </div>
        </section>
      </div>
    </OnboardingCanvas>
  );
}

/** Wide screens: Hannah large on the right, in front of a warm sun, behind the step cards (decorative). */
function WelcomeArt() {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 right-0 hidden w-[56%] lg:block">
      <div className="absolute -right-[10%] -top-[9rem] size-[46rem] rounded-full bg-[#fcefc2]/70" />
      <div className="absolute right-[24%] top-[3rem] size-56 rounded-full bg-hero-yellow/20 blur-3xl" />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        className="absolute right-[17%] top-4 h-auto w-[23rem] max-w-none drop-shadow-[0_16px_26px_rgb(14_30_61/0.18)] xl:w-[26rem]"
        height={900}
        src="/branding/hannah-hero-front.webp"
        width={600}
      />
      <SparkleIcon className="absolute right-[13%] top-[3.5rem] size-10 text-hero-yellow" />
      <SparkleIcon className="absolute left-[14%] top-[16rem] size-8 text-hero-yellow" />
      <SparkleIcon className="absolute right-[14%] top-[18rem] size-12 text-hero-yellow" />
      <span className="absolute left-[12%] top-[6rem] flex rotate-[35deg] flex-col gap-2">
        <span className="h-1.5 w-9 rounded-full bg-hero-yellow" />
        <span className="ml-3 h-1.5 w-7 rounded-full bg-hero-yellow" />
      </span>
      <p className="absolute right-0 top-[7.5rem] w-[11.5rem] rotate-[-7deg] rounded-[2.5rem] border-2 border-hero-yellow bg-white px-5 py-4 text-center text-[1.125rem] font-extrabold italic leading-snug text-hero-navy shadow-[0_10px_24px_-16px_rgb(14_30_61/0.4)] xl:w-[12.5rem] xl:text-[1.25rem]">
        Let&apos;s build something great together!
        <span className="mx-auto mt-2 block h-1 w-14 rounded-full bg-hero-yellow" />
        <span className="absolute -left-[0.55rem] bottom-8 size-4 rotate-45 border-b-2 border-l-2 border-hero-yellow bg-white" />
      </p>
    </div>
  );
}
