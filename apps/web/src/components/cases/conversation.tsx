import type { ReactNode } from "react";

import { AdviserTurn, boxHeading } from "@/components/ask/response-tone";
import { PersonAvatar } from "@/components/app/workspace-chrome";
import { AlertIcon, CheckIcon, HelpIcon, ShieldIcon } from "@/components/site/icons";
import { formatDayTime } from "@/lib/workflows/copy";
import type { CautionMessage, HoldMessage, Message } from "@/lib/workflows/model";

/**
 * The case conversation, oldest first, in the approved thread (Page 1): HeroOS
 * speaks with its own mark, the employer as "You". Every HeroOS message is text
 * the API chose from the Case's saved state (no AI); the employer's turns are
 * the saved answer groups. The outcome of each turn is the workflow's own:
 * a caution is a Warning, a hold until the jurisdiction is confirmed is a
 * Block, a hold for specialist review is Expert Review, everything else is
 * Guidance. Rendering only: nothing here decides or infers.
 */

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
      <HoldItems hold={hold} />
      <Body>{hold.body}</Body>
    </>
  );
}

function HoldItems({ hold }: { hold: HoldMessage }) {
  if (hold.items.length === 0) return null;
  return (
    <div className="mt-2">
      <p className="text-sm font-bold">Reported in the screening</p>
      <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-5 text-[0.9375rem]">
        {hold.items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function Body({ children }: { children: string }) {
  return <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-navy/85">{children}</p>;
}

/** A box inside a turn (approved design): white, ringed in the turn's tone. */
function TurnBox({ heading, help = false, children }: { heading: string; help?: boolean; children: ReactNode }) {
  return (
    <div className="rounded-xl bg-white/90 px-4 py-3 ring-1 ring-(--tone-line)">
      <p className={help ? "flex items-center gap-1.5 text-[0.75rem] font-bold uppercase tracking-[0.1em] text-hero-muted" : boxHeading}>
        {help ? <HelpIcon className="size-3.5" /> : null}
        {heading}
      </p>
      {children}
    </div>
  );
}

function Numbered({ items }: { items: string[] }) {
  return (
    <ol className="mt-2 space-y-2">
      {items.map((item, index) => (
        <li className="flex gap-2.5" key={item}>
          <span
            aria-hidden="true"
            className="mt-[0.2rem] inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-(--tone-chip) text-[0.6875rem] font-extrabold text-(--tone-ink)"
          >
            {index + 1}
          </span>
          <span>{item}</span>
        </li>
      ))}
    </ol>
  );
}

function Provisional({ provisional }: { provisional: boolean }) {
  return provisional ? (
    <p>
      <ProvisionalTag />
    </p>
  ) : null;
}

export function ConversationMessage({ message }: { message: Message }) {
  switch (message.kind) {
    case "information":
      return (
        <AdviserTurn id={message.id} outcome="guidance">
          <p className="font-bold">{message.title}</p>
          <p>{message.body}</p>
        </AdviserTurn>
      );
    case "question_group":
      return (
        <AdviserTurn id={message.id} outcome="guidance">
          <p className="font-bold">{message.title}</p>
          <p>{message.body}</p>
          <TurnBox heading="HeroOS needs to know" help>
            <Numbered items={message.questions} />
          </TurnBox>
        </AdviserTurn>
      );
    case "missing_information":
      // What's still missing is guidance, not a warning: HeroOS needs it to continue.
      return (
        <AdviserTurn id={message.id} outcome="guidance">
          <p className="font-bold">{message.title}</p>
          <TurnBox heading="Still needed">
            <ul className="mt-2 space-y-1.5">
              {message.items.map((item) => (
                <li className="flex gap-2" key={item}>
                  <span aria-hidden="true" className="mt-[0.45rem] size-2.5 shrink-0 rounded-full border-2 border-hero-control" />
                  {item}
                </li>
              ))}
            </ul>
          </TurnBox>
          <p>{message.body}</p>
        </AdviserTurn>
      );
    case "caution":
      return (
        <AdviserTurn id={message.id} outcome="warning" title={message.title}>
          <p>{message.body}</p>
          <Provisional provisional={message.provisional} />
        </AdviserTurn>
      );
    case "hold":
      return (
        <AdviserTurn id={message.id} outcome={message.action === "escalate" ? "expert" : "block"} title={message.title}>
          <HoldItems hold={message} />
          <p>{message.body}</p>
          <Provisional provisional={message.provisional} />
        </AdviserTurn>
      );
    case "status_notice":
      if (message.tone === "success") {
        return (
          <p className="flex items-center gap-3 text-[0.8125rem] text-hero-muted sm:pl-11" role="note">
            <CheckIcon className="size-4 shrink-0 text-hero-blue" />
            <span className="min-w-0">
              <span className="font-bold text-hero-navy">{message.title}.</span> {message.body}
            </span>
          </p>
        );
      }
      return (
        <AdviserTurn
          id={message.id}
          outcome={message.tone === "caution" ? "warning" : "guidance"}
          title={message.tone === "caution" ? message.title : undefined}
        >
          {message.tone === "caution" ? null : <p className="font-bold">{message.title}</p>}
          <p>{message.body}</p>
        </AdviserTurn>
      );
    case "answer_confirmation":
      return (
        <article aria-label={message.byViewer ? "You" : "A company administrator"}>
          <div className="flex items-center gap-3">
            <PersonAvatar />
            <p className="flex flex-wrap items-baseline gap-x-2 text-[0.875rem]">
              <span className="font-bold text-hero-navy">{message.byViewer ? "You" : "A company administrator"}</span>
              <time className="text-xs tabular-nums text-hero-muted" dateTime={message.submittedAt}>
                {formatDayTime(message.submittedAt)}
              </time>
            </p>
          </div>
          <dl className="mt-2 space-y-2.5 rounded-2xl border border-hero-navy/[0.08] bg-white px-4 py-3 text-hero-navy shadow-[0_1px_2px_rgb(14_30_61/0.04)] sm:ml-11">
            {message.items.map((item) => (
              <div key={item.key}>
                <dt className="text-xs font-bold uppercase tracking-[0.08em] text-hero-muted">{item.label}</dt>
                <dd className="mt-0.5 whitespace-pre-wrap break-words text-base leading-[1.65]">
                  {item.display ?? <span className="italic text-hero-muted">Answer removed</span>}
                </dd>
              </div>
            ))}
          </dl>
        </article>
      );
  }
}

export function Conversation({ messages, label = "Conversation" }: { messages: Message[]; label?: string }) {
  return (
    <ol aria-label={label} className="flex flex-col gap-7" role="log">
      {messages.map((message) => (
        <li key={message.id}>
          <ConversationMessage message={message} />
        </li>
      ))}
    </ol>
  );
}
