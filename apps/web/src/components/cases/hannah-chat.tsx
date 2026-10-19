"use client";

import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";

import { AlertIcon, ChecklistIcon, SendIcon } from "@/components/site/icons";
import {
  type AssistantLoad,
  assistantLoadOf,
  boundedHistory,
  type ChatTurn,
  isAssistantReply,
  isAssistantStatus,
  MAX_MESSAGE_CHARS,
} from "@/lib/assistant/model";

/**
 * The Hannah AI demo: a conversation with a language model about fictional
 * scenarios, the case page's main view when the API says this administrator
 * can use it. It is NOT the case record: nothing here is saved, nothing changes
 * the Case, and the panels around it keep showing only what the API recorded.
 * The turns live in this component's state (kept while the guided workflow tab
 * is open) and are gone on reload. Its status comes from the page (read with
 * the Case); "Check again" re-reads it through the BFF.
 */

// The BFF waits up to 45 s for the API (lib/server/heroos-api.ts), within the
// route's 60 s maxDuration; the browser waits a little longer than the BFF.
export const HANNAH_BROWSER_TIMEOUT_MS = 55_000;
export const NOTICE =
  "Hannah AI Demo — Use fictional employee scenarios only. Responses are exploratory and do not authorize disciplinary decisions.";

type Turn = ChatTurn & { id: number; at: number; failed?: boolean };
type Failure =
  "rate_limited" | "timeout" | "not_configured" | "refused" | "session_expired" | "invalid" | "unavailable";

const FAILURE_TEXT: Record<Failure, { title: string; body: string }> = {
  rate_limited: {
    title: "Hannah needs a short break",
    body: "The demo's usage limit was reached. Wait a minute, then retry your message.",
  },
  timeout: {
    title: "Hannah took too long to answer",
    body: "Nothing was changed. Retry your message.",
  },
  not_configured: {
    title: "Hannah AI isn't set up in this environment",
    body: "The demo's model provider isn't configured yet. The guided case workflow works as usual.",
  },
  refused: {
    title: "Hannah AI isn't available to you here",
    body: "Only company administrators can use Hannah in their own company's cases. Reload the page to see the case as it is now.",
  },
  session_expired: {
    title: "Your session has ended",
    body: "Sign in again, then retry your message.",
  },
  invalid: {
    title: "That message couldn't be sent",
    body: "Shorten it or remove unusual characters, then retry.",
  },
  unavailable: {
    title: "Hannah couldn't answer just now",
    body: "Nothing was changed. Retry your message.",
  },
};

const STATUS_FAILURE: Record<number, Failure> = {
  401: "session_expired",
  403: "refused",
  404: "refused",
  413: "invalid",
  422: "invalid",
  429: "rate_limited",
  504: "timeout",
};

const TIME = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });

/**
 * Hannah's face from the approved illustration (no new artwork): the full
 * figure scaled up inside a circle, positioned on her face with classes only
 * (the CSP forbids inline style attributes).
 */
export function HannahAvatar({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const box = size === "lg" ? "size-14" : size === "sm" ? "size-6" : "size-10 sm:size-11";
  return (
    <span
      aria-hidden="true"
      className={`relative inline-block shrink-0 overflow-hidden rounded-full border-2 border-white bg-hero-blue-tint shadow-[0_0_0_1px_rgb(61_107_196/0.35)] ${box}`}
    >
      {/* Plain <img>: next/image adds an inline style attribute the CSP forbids. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        className="absolute left-[-76%] top-[-30%] h-auto w-[210%] max-w-none"
        height={900}
        src="/branding/hannah-hero-front.webp"
        width={600}
      />
    </span>
  );
}

function YouAvatar() {
  return (
    <span
      aria-hidden="true"
      className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-[#e8e4fb] text-xs font-extrabold text-hero-navy sm:size-11"
    >
      You
    </span>
  );
}

function Speaker({ name, at, end = false }: { name: string; at?: number; end?: boolean }) {
  return (
    <p className={`flex items-baseline gap-2 text-sm ${end ? "justify-end" : ""}`}>
      <span className="font-bold text-hero-navy">{name}</span>
      {at ? (
        <time className="text-xs text-hero-muted tabular-nums" dateTime={new Date(at).toISOString()}>
          {TIME.format(at)}
        </time>
      ) : null}
    </p>
  );
}

const hannahBubble =
  "whitespace-pre-wrap break-words rounded-2xl rounded-tl-md border border-[#d6e4fa] bg-hero-blue-tint px-4 py-3 text-[0.9375rem] leading-relaxed text-hero-navy";
const quietButton =
  "inline-flex min-h-10 items-center gap-1.5 rounded-full border border-hero-control bg-white px-4 text-sm font-bold text-hero-navy transition-colors duration-150 hover:bg-hero-blue-tint disabled:cursor-not-allowed disabled:opacity-60";

/** Not a working chat: the reason in words, a way to the guided workflow and, where it may help, a re-check. */
function StatusPanel({
  title,
  children,
  onOpenWorkflow,
  recheck,
}: {
  title: string;
  children: string;
  onOpenWorkflow: () => void;
  recheck?: { busy: boolean; run: () => void; failed: boolean };
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 py-12 text-center sm:px-6">
      <HannahAvatar size="lg" />
      <h2 className="mt-4 text-lg font-extrabold tracking-[-0.01em] text-hero-navy" id="hannah-heading">
        {title}
      </h2>
      <p className="mt-1.5 max-w-md text-[0.9375rem] leading-relaxed text-hero-navy/85">{children}</p>
      <p aria-live="polite" className="mt-2 min-h-5 text-sm font-semibold text-hero-danger">
        {recheck?.failed && !recheck.busy ? "Still not responding. Try again in a minute." : ""}
      </p>
      <div className="mt-3 flex flex-wrap justify-center gap-2">
        {recheck ? (
          <button className={quietButton} disabled={recheck.busy} onClick={recheck.run} type="button">
            {recheck.busy ? "Checking…" : "Check again"}
          </button>
        ) : null}
        <button className={quietButton} onClick={onOpenWorkflow} type="button">
          <ChecklistIcon className="size-4" />
          Open the guided case workflow
        </button>
      </div>
    </div>
  );
}

export function HannahChat({
  companyId,
  caseId,
  load,
  onLoad,
  onOpenWorkflow,
  fetcher,
}: {
  companyId: string;
  caseId: string;
  /** The demo's status for this administrator and Case (never `hidden` here). */
  load: AssistantLoad;
  /** A re-read status ("Check again"). */
  onLoad: (load: AssistantLoad) => void;
  /** Shows the guided case workflow. */
  onOpenWorkflow: () => void;
  fetcher?: typeof fetch;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [checking, setChecking] = useState(false);
  // A "Check again" that found Hannah still unreachable.
  const [stillDown, setStillDown] = useState(false);
  const nextId = useRef(1);
  // Bumped by "Start over": a reply to an earlier conversation is dropped.
  const conversation = useRef(0);
  const endRef = useRef<HTMLLIElement>(null);

  // Keep the newest turn in view: the list scrolls on large screens, the page on small ones.
  useEffect(() => {
    if (turns.length > 0 || pending) endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [turns, pending]);

  async function recheck() {
    if (checking) return;
    setChecking(true);
    let next: AssistantLoad = { state: "unreachable" };
    try {
      const response = await (fetcher ?? fetch)(
        `/bff/companies/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}/assistant`,
        {
          headers: { Accept: "application/json" },
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
          signal: AbortSignal.timeout(20_000),
        },
      );
      const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
      if (response.status === 200 && body && isAssistantStatus(body.status)) next = assistantLoadOf(body.status);
      // Not for this person here (a role change, an API without the demo): out of sight, as on load.
      else if (response.status === 403 || response.status === 404) next = { state: "hidden" };
    } catch {
      // Still unreachable.
    }
    setChecking(false);
    setStillDown(next.state === "unreachable");
    onLoad(next);
  }

  async function deliver(message: Turn, earlier: Turn[]) {
    const generation = conversation.current;
    setPending(true);
    setFailure(null);
    let outcome: { reply: string } | { failure: Failure };
    try {
      const response = await (fetcher ?? fetch)(
        `/bff/companies/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}/assistant/messages`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          body: JSON.stringify({
            message: message.content,
            history: boundedHistory(earlier),
          }),
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
          signal: AbortSignal.timeout(HANNAH_BROWSER_TIMEOUT_MS),
        },
      );
      const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
      if (response.status === 200 && body && isAssistantReply(body.reply)) {
        outcome = { reply: body.reply.reply };
      } else {
        const code = body?.error === "not_configured" ? "not_configured" : STATUS_FAILURE[response.status];
        outcome = { failure: code ?? "unavailable" };
      }
    } catch (error) {
      const name = error instanceof Error ? error.name : "";
      outcome = {
        failure: name === "TimeoutError" || name === "AbortError" ? "timeout" : "unavailable",
      };
    }
    if (generation !== conversation.current) return;
    setPending(false);
    if ("reply" in outcome) {
      const reply: Turn = {
        id: nextId.current++,
        at: Date.now(),
        role: "assistant",
        content: outcome.reply,
      };
      setTurns((all) => [...all.map((turn) => (turn.id === message.id ? { ...turn, failed: false } : turn)), reply]);
    } else {
      const failed = outcome.failure;
      setTurns((all) => all.map((turn) => (turn.id === message.id ? { ...turn, failed: true } : turn)));
      setFailure(failed);
    }
  }

  function send(event?: FormEvent) {
    event?.preventDefault();
    const content = draft.trim();
    if (pending || content.length === 0 || content.length > MAX_MESSAGE_CHARS) return;
    // An unsent message is replaced by the new one, never sent twice.
    const earlier = turns.filter((turn) => !turn.failed);
    const message: Turn = { id: nextId.current++, at: Date.now(), role: "user", content };
    setTurns([...earlier, message]);
    setDraft("");
    void deliver(message, earlier);
  }

  function retry() {
    const index = turns.findIndex((turn) => turn.failed);
    if (pending || index === -1) return;
    void deliver(turns[index], turns.slice(0, index));
  }

  function restart() {
    conversation.current += 1;
    setTurns([]);
    setDraft("");
    setPending(false);
    setFailure(null);
    requestAnimationFrame(() => document.getElementById("hannah-message")?.focus());
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  }

  if (load.state === "hidden") return null;
  if (load.state === "unreachable") {
    return (
      <StatusPanel
        onOpenWorkflow={onOpenWorkflow}
        recheck={{ busy: checking, run: () => void recheck(), failed: stillDown }}
        title="Hannah AI isn't responding right now"
      >
        HeroOS couldn&apos;t check whether Hannah is available for this case. Nothing was changed, and the guided case
        workflow works as usual.
      </StatusPanel>
    );
  }
  if (!load.status.available) {
    return (
      <StatusPanel onOpenWorkflow={onOpenWorkflow} title={FAILURE_TEXT.not_configured.title}>
        {FAILURE_TEXT.not_configured.body}
      </StatusPanel>
    );
  }

  const left = MAX_MESSAGE_CHARS - draft.length;

  return (
    <div className="flex flex-1 flex-col lg:min-h-0" data-testid="hannah-chat">
      <h2 className="sr-only" id="hannah-heading">
        Conversation with Hannah (AI demo)
      </h2>
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-[#f1df8d] bg-hero-yellow-tint px-4 py-2.5 sm:px-6 lg:px-8">
        <p className="flex min-w-0 flex-1 items-start gap-2 text-[0.8125rem] font-semibold leading-snug text-hero-navy">
          <AlertIcon className="mt-px size-4 shrink-0" />
          <span>
            {NOTICE}{" "}
            <span className="hidden font-normal text-hero-navy/80 sm:inline">
              AI demo · not part of the case record · not saved.
            </span>
          </span>
        </p>
        <button
          className="inline-flex min-h-9 items-center rounded-full border border-hero-control bg-white px-3.5 text-sm font-bold text-hero-navy transition-colors duration-150 hover:bg-hero-blue-tint disabled:cursor-not-allowed disabled:opacity-60"
          disabled={turns.length === 0 && draft.length === 0 && failure === null}
          onClick={restart}
          type="button"
        >
          Start over
        </button>
      </div>

      <ol
        aria-label="Conversation with Hannah (AI demo)"
        aria-live="polite"
        className="flex flex-col gap-6 px-4 py-6 sm:px-6 lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:overscroll-contain lg:px-8"
        role="log"
      >
        <li className="flex items-start gap-3 sm:gap-4">
          <HannahAvatar />
          <div className="min-w-0 max-w-[42rem] flex-1">
            <Speaker name="Hannah" />
            <div className={`mt-1.5 ${hannahBubble}`}>
              <p>Hi, I&apos;m Hannah.</p>
              <p className="mt-2">
                Tell me about the made-up situation you&apos;re thinking through, and we&apos;ll work through it together,
                one question at a time.
              </p>
            </div>
            <div className="mt-2 rounded-2xl border border-[#d6e4fa] bg-white px-4 py-3 text-sm leading-relaxed text-hero-navy/85">
              <p className="font-semibold text-hero-navy">You can include, for example:</p>
              <ul className="mt-1 list-disc pl-5 marker:text-hero-blue">
                <li>what happened (a fictional example)</li>
                <li>when it happened, and how often</li>
                <li>any relevant context, like earlier conversations</li>
              </ul>
              <p className="mt-2 text-xs text-hero-muted">
                Hannah gives general, exploratory guidance. She can&apos;t see this case&apos;s saved answers, and nothing
                said here changes the case.
              </p>
            </div>
          </div>
        </li>
        {turns.map((turn) =>
          turn.role === "user" ? (
            <li className="flex items-start justify-end gap-3 sm:gap-4" key={turn.id}>
              <div className="flex min-w-0 max-w-[38rem] flex-col items-end">
                <Speaker at={turn.at} end name="You" />
                <p className="sr-only">You:</p>
                <p className="mt-1.5 whitespace-pre-wrap break-words rounded-2xl rounded-tr-md border border-[#c4e5d1] bg-[#e8f6ee] px-4 py-3 text-[0.9375rem] leading-relaxed text-hero-navy">
                  {turn.content}
                </p>
                {turn.failed ? <span className="mt-1 text-xs font-bold text-hero-danger">Not answered</span> : null}
              </div>
              <YouAvatar />
            </li>
          ) : (
            <li className="flex items-start gap-3 sm:gap-4" data-role="assistant" key={turn.id}>
              <HannahAvatar />
              <div className="min-w-0 max-w-[42rem] flex-1">
                <Speaker at={turn.at} name="Hannah" />
                <p className="sr-only">Hannah (AI demo):</p>
                <p className={`mt-1.5 ${hannahBubble}`}>{turn.content}</p>
                <span className="mt-1 inline-block text-xs font-bold text-hero-muted">AI · exploratory, not saved</span>
              </div>
            </li>
          ),
        )}
        {pending ? (
          <li className="flex items-center gap-3 sm:gap-4">
            <HannahAvatar />
            <p
              className="inline-flex items-center gap-2 rounded-2xl rounded-tl-md border border-[#d6e4fa] bg-hero-blue-tint px-4 py-2.5 text-sm font-semibold text-hero-muted"
              role="status"
            >
              <span aria-hidden="true" className="inline-flex gap-1">
                <span className="size-1.5 animate-bounce rounded-full bg-hero-blue motion-reduce:animate-none" />
                <span className="size-1.5 animate-bounce rounded-full bg-hero-blue [animation-delay:150ms] motion-reduce:animate-none" />
                <span className="size-1.5 animate-bounce rounded-full bg-hero-blue [animation-delay:300ms] motion-reduce:animate-none" />
              </span>
              Hannah is thinking…
            </p>
          </li>
        ) : null}
        {/* Scrolled into view after each turn; the margin keeps it clear of the pinned composer on phones. */}
        <li aria-hidden="true" className="h-px scroll-mb-44 lg:scroll-mb-0" ref={endRef} />
      </ol>

      <div className="sticky bottom-0 z-10 shrink-0 border-t border-hero-border bg-white/95 px-4 pb-4 pt-3 backdrop-blur-md sm:px-6 lg:static lg:px-8 lg:pb-5">
        {failure ? (
          <div
            className="mb-3 flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-[#e9b4c0] bg-hero-danger-tint px-4 py-3 text-hero-navy"
            role="alert"
          >
            <div className="flex min-w-0 items-start gap-2">
              <AlertIcon className="mt-0.5 size-4 shrink-0" />
              <div>
                <p className="font-bold">{FAILURE_TEXT[failure].title}</p>
                <p className="text-[0.9375rem] text-hero-navy/85">{FAILURE_TEXT[failure].body}</p>
              </div>
            </div>
            {turns.some((turn) => turn.failed) && failure !== "refused" && failure !== "not_configured" ? (
              <button className={quietButton} disabled={pending} onClick={retry} type="button">
                Retry message
              </button>
            ) : null}
          </div>
        ) : null}

        <form autoComplete="off" onSubmit={send}>
          {/* One focus outline around the whole composer instead of the page's outline on the text box. */}
          <div className="rounded-2xl border border-hero-control bg-white shadow-hero-card transition-colors duration-150 focus-within:border-hero-blue focus-within:outline-3 focus-within:outline-offset-2 focus-within:outline-hero-blue">
            <label className="sr-only" htmlFor="hannah-message">
              Message Hannah
            </label>
            <textarea
              aria-describedby="hannah-hint"
              className="block max-h-44 min-h-[3.25rem] w-full resize-none rounded-2xl border-0 bg-transparent px-4 pb-1 pt-3.5 text-base text-hero-navy outline-none! [field-sizing:content] placeholder:text-hero-muted"
              id="hannah-message"
              maxLength={MAX_MESSAGE_CHARS}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Type your message to Hannah…"
              rows={2}
              value={draft}
            />
            <div className="flex items-center justify-between gap-3 px-3 pb-2.5 pl-4">
              <p className="min-w-0 text-xs text-hero-muted" id="hannah-hint">
                Enter to send · Shift+Enter for a new line
                {left < 200 ? ` · ${left} characters left` : ""}
              </p>
              <button
                className="inline-flex min-h-10 shrink-0 items-center gap-2 rounded-full bg-hero-blue px-4 text-sm font-bold text-white transition-colors duration-150 hover:bg-hero-blue-ink disabled:cursor-not-allowed disabled:opacity-50"
                disabled={pending || draft.trim().length === 0}
                type="submit"
              >
                <SendIcon className="size-4" />
                {pending ? "Sending…" : "Send"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
