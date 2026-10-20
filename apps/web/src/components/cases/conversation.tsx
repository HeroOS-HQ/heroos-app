import type { ReactNode } from "react";

import { AlertIcon, CheckIcon, ShieldIcon } from "@/components/site/icons";
import { formatDayTime } from "@/lib/workflows/copy";
import type { CautionMessage, HoldMessage, Message } from "@/lib/workflows/model";

/**
 * The guided conversation, oldest first. Every HeroOS message is text the API
 * chose from the Case's saved state (no AI); the employer's turns are the
 * saved answer groups. Rendering only: nothing here decides or infers.
 */

function HeroAvatar() {
  return (
    <span
      aria-hidden="true"
      className="inline-flex size-9 shrink-0 items-center justify-center rounded-full border border-hero-border bg-white"
    >
      {/* Plain <img>: next/image adds an inline style attribute the CSP forbids. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img alt="" className="h-auto w-6" height={144} src="/branding/heroos-logo-symbol.png" width={212} />
    </span>
  );
}

const TONE_CLASSES = {
  info: "border-[#cfe0f8] bg-hero-blue-tint",
  caution: "border-[#f1df8d] bg-hero-yellow-tint",
  success: "border-[#b8dcc6] bg-hero-success-tint",
  hold: "border-[#e9b4c0] bg-hero-danger-tint",
  plain: "border-hero-border bg-white",
} as const;

/** Marks content whose source rule is still under legal review. */
export function ProvisionalTag() {
  return (
    <span className="inline-flex items-center rounded-full border border-hero-border bg-white px-2 py-0.5 text-xs font-bold text-hero-muted">
      Provisional: not legal advice
    </span>
  );
}

/** A caution: information for the employer that doesn't block the case. */
export function CautionCard({ caution }: { caution: CautionMessage }) {
  return (
    <>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 font-bold">
        <AlertIcon className="size-4 shrink-0" />
        <span>Caution: {caution.title}</span>
        {caution.provisional ? <ProvisionalTag /> : null}
      </p>
      <Body>{caution.body}</Body>
    </>
  );
}

/** A hold: the case is paused (block) or needs specialist review first (escalate). */
export function HoldCard({ hold }: { hold: HoldMessage }) {
  return (
    <>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 font-bold">
        <ShieldIcon className="size-4 shrink-0" />
        <span>{hold.title}</span>
        {hold.provisional ? <ProvisionalTag /> : null}
      </p>
      {hold.items.length > 0 ? (
        <div className="mt-2">
          <p className="text-sm font-bold">Reported in the screening</p>
          <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-5 text-[0.9375rem]">
            {hold.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <Body>{hold.body}</Body>
    </>
  );
}

function HeroBubble({
  children,
  tone = "plain",
  compact = false,
}: {
  children: ReactNode;
  tone?: keyof typeof TONE_CLASSES;
  compact?: boolean;
}) {
  return (
    <div className="flex items-start gap-3">
      <HeroAvatar />
      <div className="min-w-0 max-w-[40rem] flex-1">
        <p className="sr-only">HeroOS:</p>
        <div
          className={`rounded-2xl rounded-tl-md border text-hero-navy ${compact ? "px-4 py-2.5" : "px-4 py-3.5 sm:px-5 sm:py-4"} ${TONE_CLASSES[tone]}`}
        >
          {children}
        </div>
      </div>
    </div>
  );
}

function Body({ children }: { children: string }) {
  return <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-navy/85">{children}</p>;
}

export function ConversationMessage({ message }: { message: Message }) {
  switch (message.kind) {
    case "information":
      return (
        <HeroBubble>
          <p className="font-bold">{message.title}</p>
          <Body>{message.body}</Body>
        </HeroBubble>
      );
    case "question_group":
      return (
        <HeroBubble>
          <p className="font-bold">{message.title}</p>
          <Body>{message.body}</Body>
          <ol className="mt-3 flex list-decimal flex-col gap-1 pl-5 text-[0.9375rem] text-hero-navy marker:font-bold marker:text-hero-blue-ink">
            {message.questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ol>
        </HeroBubble>
      );
    case "missing_information":
      return (
        <HeroBubble tone="caution">
          <p className="flex items-center gap-2 font-bold">
            <AlertIcon className="size-4 shrink-0" />
            {message.title}
          </p>
          <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-[0.9375rem]">
            {message.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <Body>{message.body}</Body>
        </HeroBubble>
      );
    case "caution":
      return (
        <HeroBubble tone="caution">
          <CautionCard caution={message} />
        </HeroBubble>
      );
    case "hold":
      return (
        <HeroBubble tone={message.action === "escalate" ? "hold" : "caution"}>
          <HoldCard hold={message} />
        </HeroBubble>
      );
    case "status_notice":
      return message.tone === "success" ? (
        <HeroBubble compact tone="success">
          <p className="flex flex-wrap items-center gap-x-2 text-[0.9375rem]">
            <CheckIcon className="size-4 shrink-0 text-hero-success" />
            <span className="font-bold">{message.title}.</span>
            <span className="text-hero-navy/85">{message.body}</span>
          </p>
        </HeroBubble>
      ) : (
        <HeroBubble tone={message.tone}>
          <p className="font-bold">{message.title}</p>
          <Body>{message.body}</Body>
        </HeroBubble>
      );
    case "answer_confirmation":
      return (
        <div className="flex justify-end">
          <div className="min-w-0 max-w-[36rem] rounded-2xl rounded-tr-md bg-hero-navy px-4 py-3.5 text-white sm:px-5">
            <p className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 text-sm">
              <span className="font-bold">{message.byViewer ? "You" : "A company administrator"}</span>
              <time className="text-white/70" dateTime={message.submittedAt}>
                {formatDayTime(message.submittedAt)}
              </time>
            </p>
            <dl className="mt-2 flex flex-col gap-2">
              {message.items.map((item) => (
                <div key={item.key}>
                  <dt className="text-xs font-bold uppercase tracking-[0.08em] text-white/70">{item.label}</dt>
                  <dd className="mt-0.5 whitespace-pre-wrap break-words text-[0.9375rem] leading-relaxed">
                    {item.display ?? <span className="italic text-white/75">Answer removed</span>}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      );
  }
}

export function Conversation({ messages }: { messages: Message[] }) {
  return (
    <ol aria-label="Conversation" className="flex flex-col gap-4">
      {messages.map((message) => (
        <li key={message.id}>
          <ConversationMessage message={message} />
        </li>
      ))}
    </ol>
  );
}
