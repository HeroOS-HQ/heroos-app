"use client";

import { useRef, useState } from "react";

import { AdviserMark, PersonAvatar } from "@/components/app/workspace-chrome";
import type { GatewayStatus } from "@/lib/ask/conversation";
import { ASK_TEXT_MAX, parseAskStarted, provisionalCaseTitle } from "@/lib/ask/model";

import { AskConversation } from "./ask-conversation";
import { AskAlert, AskLanding, Composer, SignInAgain } from "./ask-parts";

/**
 * Page 1, Ask HeroOS (approved Oct 20 design): one question, one box. The
 * founder explains the situation in their own words; there is no workflow,
 * category, stage or title to choose.
 *
 * Two ways it answers, decided by the API, never by this page:
 *
 * - **HeroOS's AI conversation** (M2-NEW-05, `conversation`): when the API says
 *   its controlled gateway can answer for this administrator, Send starts a
 *   conversation with HeroOS (`ask-conversation.tsx`). No case is opened.
 * - **Otherwise** (the gateway is switched off, not configured or has no
 *   approved knowledge): Send opens a real case through the Ask seam
 *   (`/bff/companies/{id}/ask`, lib/ask/model.ts) and takes the founder there.
 *   Nothing pretends to be AI: the case follows HeroOS's guided Disciplinary
 *   workflow.
 */

/** Who may ask: administrators open cases; for everyone else the box says why it can't. */
export type AskMode = "ready" | "members" | "unavailable";

type Failure = "session_expired" | "refused" | "invalid" | "conflict" | "unavailable";
type Status =
  | { kind: "idle" }
  | { kind: "opening"; text: string; at: Date }
  | { kind: "failed"; reason: Failure }
  /** The case opened, but the founder's words didn't reach it. */
  | { kind: "partial"; caseHref: string };

const FAILURES: Record<Failure, string> = {
  session_expired: "Your session has ended. Sign in again, then ask again.",
  refused: "Only company administrators can open cases.",
  invalid: "HeroOS couldn't accept this text. Remove any unusual characters and try again.",
  conflict: "Something changed while the case was opening. Please try again.",
  unavailable: "HeroOS couldn't be reached. Please try again: your question won't be sent twice.",
};

const PLACEHOLDER: Record<AskMode, string> = {
  ready: "For example: one of my team hasn't come in for two days and isn't answering.",
  members: "Only company administrators can open cases for now.",
  unavailable: "HeroOS can't open cases in this workspace yet.",
};

const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });

function failureOf(status: number): Failure {
  switch (status) {
    case 401:
      return "session_expired";
    case 403:
      return "refused";
    case 409:
      return "conflict";
    case 413:
    case 422:
      return "invalid";
    default:
      return "unavailable";
  }
}

export function AskWorkspace({
  companyId,
  mode,
  returning,
  conversation = null,
  fetcher,
  navigate,
}: {
  companyId: string;
  mode: AskMode;
  /** The founder has cases already ("Welcome back"). */
  returning: boolean;
  /** HeroOS's AI gateway, when the API says it can answer here (M2-NEW-05). */
  conversation?: GatewayStatus | null;
  fetcher?: typeof fetch;
  navigate?: (href: string) => void;
}) {
  if (mode === "ready" && conversation?.available) {
    return <AskConversation companyId={companyId} fetcher={fetcher} notice={conversation.notice} returning={returning} />;
  }
  return <AskCaseOpening companyId={companyId} fetcher={fetcher} mode={mode} navigate={navigate} returning={returning} />;
}

/** Ask without the AI gateway: Send opens a real case (M2-NEW-02). */
function AskCaseOpening({
  companyId,
  mode,
  returning,
  fetcher,
  navigate,
}: {
  companyId: string;
  mode: AskMode;
  returning: boolean;
  fetcher?: typeof fetch;
  navigate?: (href: string) => void;
}) {
  const [text, setText] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  // One title and pair of keys per question: a retry of the same words after a lost response opens one case.
  const attempt = useRef<{ text: string; title: string; requestKey: string; submissionKey: string } | null>(null);
  const inFlight = useRef(false);

  const base = `/workspaces/${encodeURIComponent(companyId)}`;
  const value = text.trim();
  const canSend = mode === "ready" && value.length > 0 && status.kind !== "opening";

  async function send() {
    if (!canSend || inFlight.current) return;
    if (attempt.current?.text !== value) {
      attempt.current = {
        text: value,
        title: provisionalCaseTitle(new Date()),
        requestKey: crypto.randomUUID(),
        submissionKey: crypto.randomUUID(),
      };
    }
    const { title, requestKey, submissionKey } = attempt.current;
    inFlight.current = true;
    setStatus({ kind: "opening", text: value, at: new Date() });
    try {
      const response = await (fetcher ?? fetch)(`/bff/companies/${encodeURIComponent(companyId)}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ text: value, title, requestKey, submissionKey }),
        cache: "no-store",
        credentials: "same-origin",
        redirect: "error",
        // Three API calls behind it, and a free-tier API may be waking up.
        signal: AbortSignal.timeout(60_000),
      });
      const started = response.status === 200 ? parseAskStarted(await response.json().catch(() => null)) : null;
      if (started) {
        const caseHref = `${base}/cases/${encodeURIComponent(started.caseId)}`;
        if (started.narrativeSaved) {
          (navigate ?? ((href: string) => window.location.assign(href)))(caseHref);
          return;
        }
        setStatus({ kind: "partial", caseHref });
      } else {
        setStatus({ kind: "failed", reason: response.status === 200 ? "unavailable" : failureOf(response.status) });
      }
    } catch {
      setStatus({ kind: "failed", reason: "unavailable" });
    } finally {
      inFlight.current = false;
    }
  }

  if (status.kind === "opening") return <Opening at={status.at} text={status.text} />;

  return (
    <AskLanding returning={returning}>
      <Composer
        canSend={canSend}
        describedBy={status.kind === "idle" ? undefined : "ask-status"}
        disabled={mode !== "ready"}
        maxLength={ASK_TEXT_MAX}
        onChange={(value) => {
          setText(value);
          if (status.kind === "failed") setStatus({ kind: "idle" });
        }}
        onSend={() => void send()}
        placeholder={PLACEHOLDER[mode]}
        value={text}
      />
      {status.kind === "failed" || status.kind === "partial" ? (
        <AskAlert>
          {status.kind === "partial" ? (
            <>
              HeroOS opened the case but couldn&apos;t save your description.{" "}
              <a className="font-bold text-hero-blue-ink underline" href={status.caseHref}>
                Open the case
              </a>{" "}
              and add it there; your text is still in the box above.
            </>
          ) : (
            <>
              {FAILURES[status.reason]}
              {status.reason === "session_expired" ? <SignInAgain /> : null}
            </>
          )}
        </AskAlert>
      ) : null}
    </AskLanding>
  );
}

/** Between Send and the case: the founder's words, and HeroOS opening the case (no visible reasoning). */
function Opening({ text, at }: { text: string; at: Date }) {
  return (
    <div className="mx-auto w-full max-w-[46rem] px-4 pb-8 pt-3 sm:px-6 sm:pt-7">
      <h1 className="sr-only">Opening your case</h1>
      <ol aria-label="Opening your case" className="flex flex-col gap-7">
        <li>
          <article aria-label="You">
            <div className="flex items-center gap-3">
              <PersonAvatar />
              <p className="flex items-baseline gap-2 text-[0.875rem]">
                <span className="font-bold text-hero-navy">You</span>
                <time className="text-xs tabular-nums text-hero-muted">{TIME.format(at)}</time>
              </p>
            </div>
            <p className="mt-2 whitespace-pre-wrap break-words rounded-2xl border border-hero-navy/[0.08] bg-white px-4 py-3 text-base leading-[1.65] text-hero-navy shadow-[0_1px_2px_rgb(14_30_61/0.04)] sm:ml-11">
              {text}
            </p>
          </article>
        </li>
        <li className="ws-rise-late">
          <article aria-label="HeroOS is opening a case for this" role="status">
            <div className="flex items-center gap-3">
              <AdviserMark breathe />
              <p className="text-[0.875rem]">
                <span className="font-extrabold text-hero-navy">HeroOS</span>{" "}
                <span className="font-medium text-hero-muted">is opening a case for this</span>
                <span aria-hidden="true" className="ml-2 inline-flex gap-1 align-middle">
                  <span className="ws-dot size-1.5 rounded-full bg-hero-blue" />
                  <span className="ws-dot size-1.5 rounded-full bg-hero-blue" />
                  <span className="ws-dot size-1.5 rounded-full bg-hero-blue" />
                </span>
              </p>
            </div>
            <div aria-hidden="true" className="mt-3 space-y-2.5 border-l-2 border-[#d9e3f6] pl-4 sm:ml-[0.9375rem] sm:pl-[1.6875rem]">
              <span className="ws-shimmer block h-3 w-[85%] rounded-full" />
              <span className="ws-shimmer block h-3 w-[60%] rounded-full" />
            </div>
          </article>
        </li>
      </ol>
    </div>
  );
}
