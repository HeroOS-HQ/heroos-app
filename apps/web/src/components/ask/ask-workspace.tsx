"use client";

import { type FormEvent, useRef, useState } from "react";

import { AdviserMark, PersonAvatar } from "@/components/app/workspace-chrome";
import { SendIcon } from "@/components/site/icons";
import { ASK_TEXT_MAX, parseAskStarted, provisionalCaseTitle } from "@/lib/ask/model";

/**
 * Page 1, Ask HeroOS (approved Oct 20 design): one question, one box. The
 * founder explains the situation in their own words; there is no workflow,
 * category, stage or title to choose. Sending opens a real case through the
 * Ask seam (`/bff/companies/{id}/ask`, lib/ask/model.ts) and takes the founder
 * there. Nothing here pretends to be AI: until M2-NEW-05/06 the case follows
 * HeroOS's guided Disciplinary workflow.
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
  fetcher,
  navigate,
}: {
  companyId: string;
  mode: AskMode;
  /** The founder has cases already ("Welcome back"). */
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

  async function send(event?: FormEvent) {
    event?.preventDefault();
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
    <div className="flex flex-1 flex-col px-4 pb-4 sm:items-center sm:justify-center sm:px-6 sm:pb-[12vh]">
      <div className="flex flex-1 flex-col items-center justify-center text-center sm:flex-none">
        <span className="ws-rise">
          <AdviserMark size="hero" />
        </span>
        <p className="ws-rise mt-6 text-[0.9375rem] font-semibold text-hero-muted sm:text-base">
          {returning ? "Welcome back." : "Welcome."}
        </p>
        <h1 className="ws-rise mt-2 text-[2.375rem] font-extrabold leading-[1.04] tracking-[-0.04em] text-hero-navy sm:text-[3.5rem]">
          What can HR do for you today?
        </h1>
        <p className="ws-rise-late mt-4 text-[1.0625rem] text-hero-muted sm:text-xl">Explain the situation in your own words.</p>
      </div>
      <div className="w-full sm:mt-11 sm:max-w-[46rem]">
        <form noValidate onSubmit={(event) => void send(event)}>
          <div
            className={`rounded-[1.75rem] border border-hero-navy/[0.12] bg-white shadow-[0_1px_2px_rgb(14_30_61/0.05),0_28px_60px_-30px_rgb(14_30_61/0.45)] transition-[border-color,box-shadow] duration-200 focus-within:border-hero-blue focus-within:shadow-[0_0_0_4px_rgb(61_107_196/0.12),0_28px_60px_-30px_rgb(14_30_61/0.45)] ${
              mode === "ready" ? "" : "opacity-70"
            }`}
          >
            <label className="sr-only" htmlFor="ask-heroos">
              Explain the situation in your own words
            </label>
            {/* The composer's rounded border shows focus (focus-within); the field draws no
                rectangle of its own. `!`: the global :focus-visible outline is unlayered, so it
                outranks utilities. In forced-colors mode the field keeps an outline. */}
            <textarea
              aria-describedby={status.kind === "idle" ? undefined : "ask-status"}
              className="block min-h-[7rem] w-full resize-none bg-transparent px-6 pt-5 text-[1.0625rem] leading-relaxed text-hero-navy placeholder:text-hero-muted/80 focus-visible:outline-hidden! disabled:cursor-not-allowed sm:min-h-[7.75rem] sm:text-lg"
              disabled={mode !== "ready"}
              id="ask-heroos"
              maxLength={ASK_TEXT_MAX}
              onChange={(event) => {
                setText(event.target.value);
                if (status.kind === "failed") setStatus({ kind: "idle" });
              }}
              onKeyDown={(event) => {
                // Enter adds a line; Ctrl+Enter (⌘+Enter) sends.
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void send();
              }}
              placeholder={PLACEHOLDER[mode]}
              rows={3}
              value={text}
            />
            <div className="flex items-center gap-2 px-3 pb-3">
              <button
                aria-label="Send"
                className={`ml-auto inline-flex size-12 shrink-0 items-center justify-center rounded-full text-white transition-[background-color,transform] duration-150 ${
                  canSend
                    ? "bg-hero-navy shadow-[0_10px_20px_-10px_rgb(14_30_61/0.9)] hover:-translate-y-px hover:bg-[#182c55]"
                    : "cursor-not-allowed bg-[#c5ccd9]"
                }`}
                disabled={!canSend}
                type="submit"
              >
                <SendIcon className="size-5" />
              </button>
            </div>
          </div>
        </form>
        {status.kind === "failed" || status.kind === "partial" ? (
          <div
            className="ws-rise mt-3 rounded-2xl border border-[#f1c2c6] bg-[#fff3f3] px-4 py-3 text-left text-[0.9375rem] text-hero-navy"
            id="ask-status"
            role="alert"
          >
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
                {status.reason === "session_expired" ? (
                  <>
                    {" "}
                    <a className="font-bold text-hero-blue-ink underline" href="/auth/login">
                      Sign in again
                    </a>
                  </>
                ) : null}
              </>
            )}
          </div>
        ) : null}
      </div>
    </div>
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
