"use client";

import { type KeyboardEvent, type ReactNode, useRef, useState } from "react";

import { ArrowRightIcon, ChatIcon, ChecklistIcon, DocumentIcon, PeopleIcon } from "./icons";
import { Reveal } from "./reveal";

type Step = {
  id: string;
  title: string;
  summary: string;
  detail: string;
  icon: ReactNode;
};

const STEPS: Step[] = [
  {
    id: "describe",
    title: "Tell us what's happening",
    summary: "Describe the situation in your own words.",
    detail: "Start in plain language: what happened, who is involved and what worries you. No forms to learn and no HR vocabulary needed.",
    icon: <ChatIcon />,
  },
  {
    id: "guidance",
    title: "Get guidance",
    summary: "Understand the context and your options.",
    detail: "HeroOS is designed to set out the relevant context and the options in front of you, so you can see the situation clearly.",
    icon: <DocumentIcon />,
  },
  {
    id: "decide",
    title: "Make your decision",
    summary: "Choose the right next step.",
    detail: "The decision stays with you. The trade-offs are laid out plainly, so you can choose with confidence.",
    icon: <PeopleIcon />,
  },
  {
    id: "prepare",
    title: "Complete the process",
    summary: "Follow guided steps and prepare the documents you need.",
    detail:
      "Once you make your decision, HeroOS is designed to guide the required actions, help keep the process organised, and prepare the documents you need.",
    icon: <ChecklistIcon />,
  },
];

/**
 * Explains the intended HeroOS workflow. It is an explainer, not a working
 * guidance feature: the panel says so, and nothing here generates output.
 */
export function WorkflowJourney() {
  const [selected, setSelected] = useState(0);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const select = (index: number, moveFocus: boolean) => {
    setSelected(index);
    if (moveFocus) tabRefs.current[index]?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = STEPS.length - 1;
    const target =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? (index + 1) % STEPS.length
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? (index - 1 + STEPS.length) % STEPS.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : null;
    if (target === null) return;
    event.preventDefault();
    select(target, true);
  };

  const current = STEPS[selected];

  return (
    <section
      aria-labelledby="workflow-heading"
      className="scroll-mt-20 px-5 py-24 sm:px-8 sm:py-28 lg:py-36"
      id="how-it-works"
    >
      <div className="mx-auto w-full max-w-[1240px]">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-4xl lg:text-[2.75rem] lg:leading-[1.15]" id="workflow-heading">
            How Hero<span className="text-hero-blue">OS</span> Works
          </h2>
          <p className="mt-5 text-lg text-hero-muted">From your situation to a clear plan.</p>
        </Reveal>

        <div
          aria-label="How HeroOS works"
          className="mt-12 grid gap-5 sm:grid-cols-2 sm:gap-8 lg:mt-14 lg:grid-cols-4"
          role="tablist"
        >
          {STEPS.map((step, index) => {
            const isSelected = index === selected;
            return (
              <Reveal key={step.id} className="relative" index={Math.min(index, 3) as 0 | 1 | 2 | 3}>
                <button
                  ref={(node) => {
                    tabRefs.current[index] = node;
                  }}
                  aria-controls="workflow-panel"
                  aria-selected={isSelected}
                  className={`group flex h-full min-h-[15rem] w-full flex-col rounded-3xl border-2 p-8 text-left shadow-hero-card transition-[transform,box-shadow,border-color,background-color] duration-200 hover:-translate-y-1 hover:shadow-hero-card-hover lg:p-9 ${
                    isSelected
                      ? "border-hero-yellow bg-hero-yellow-tint"
                      : "border-transparent bg-hero-surface hover:border-hero-border"
                  }`}
                  id={`workflow-tab-${step.id}`}
                  onClick={() => select(index, false)}
                  onKeyDown={(event) => onKeyDown(event, index)}
                  role="tab"
                  tabIndex={isSelected ? 0 : -1}
                  type="button"
                >
                  <span className="flex items-center justify-between">
                    <span
                      className={`flex size-12 items-center justify-center rounded-2xl transition-[background-color,transform] duration-200 group-hover:scale-105 ${
                        isSelected ? "bg-hero-yellow text-hero-navy" : "bg-hero-blue-tint text-hero-blue-ink"
                      }`}
                    >
                      {step.icon}
                    </span>
                    <span
                      className={`flex size-8 items-center justify-center rounded-full text-sm font-bold ${
                        isSelected ? "bg-hero-navy text-hero-yellow" : "border border-hero-border text-hero-muted"
                      }`}
                    >
                      {index + 1}
                    </span>
                  </span>
                  <span className="mt-6 text-xl font-bold leading-snug text-hero-navy">{step.title}</span>
                  <span className="mt-3 text-base leading-relaxed text-hero-muted">{step.summary}</span>
                </button>
                {index < STEPS.length - 1 ? (
                  <ArrowRightIcon className="pointer-events-none absolute -right-[26px] top-1/2 hidden size-5 -translate-y-1/2 text-hero-blue lg:block" />
                ) : null}
              </Reveal>
            );
          })}
        </div>

        <Reveal className="mx-auto mt-10 max-w-3xl lg:mt-12">
          <div
            aria-labelledby={`workflow-tab-${current.id}`}
            className="min-h-[11.5rem] rounded-3xl border border-hero-border bg-hero-surface/70 p-8 sm:min-h-[10rem] lg:p-10"
            id="workflow-panel"
            role="tabpanel"
          >
            <div className="fade-swap" key={current.id}>
              <p className="text-sm font-bold uppercase tracking-[0.14em] text-hero-blue-ink">
                Step {selected + 1} of {STEPS.length}
              </p>
              <p className="mt-3 text-lg leading-relaxed text-hero-navy">{current.detail}</p>
            </div>
            <p className="mt-5 text-sm text-hero-muted">
              This shows how HeroOS is meant to work. Guided steps are not available yet.
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
