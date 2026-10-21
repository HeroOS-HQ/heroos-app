"use client";

import { useEffect, useRef, useState } from "react";

import { AdviserMark, PersonAvatar } from "@/components/app/workspace-chrome";
import type { ChatTurn } from "@/lib/assistant/model";
import { gatewayRequest, MAX_MESSAGE_CHARS, parseGatewayReply } from "@/lib/ask/conversation";

import { AskAlert, AskLanding, Composer, SignInAgain } from "./ask-parts";

/**
 * Ask HeroOS as a conversation (M2-NEW-05). The founder explains the situation
 * in their own words; HeroOS answers from its approved guidance through the
 * controlled gateway (`/bff/companies/{id}/assistant/messages`), asking what
 * it needs next. Nothing to choose: no workflow, pathway, stage, title or
 * jurisdiction. Free text is always the way to answer.
 *
 * Deliberately not here: an outcome. HeroOS's turns are shown in one neutral
 * style (no Guidance, Warning, Stop or Expert Review label or colour): those
 * come from the deterministic engine, never from a model (M2-NEW-06). No case
 * is opened, and the conversation lives in this page only: reloading clears it.
 */

type Failure =
  | "session_expired"
  | "refused"
  | "invalid"
  | "rate_limited"
  | "timeout"
  | "unavailable_guidance"
  | "unavailable";

const FAILURES: Record<Failure, string> = {
  session_expired: "Your session has ended. Sign in again, then ask again.",
  refused: "Only company administrators can ask HeroOS for now.",
  invalid: "HeroOS couldn't accept this text. Remove any unusual characters and try again.",
  rate_limited: "HeroOS has had a lot of questions just now. Please wait a moment and send again: your message is still in the box.",
  timeout: "HeroOS took too long to answer. Please send again: your message is still in the box.",
  unavailable_guidance: "HeroOS's approved guidance isn't available right now. Please try again later: your message is still in the box.",
  unavailable: "HeroOS couldn't answer just now. Please send again: your message is still in the box.",
};

const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });

type Turn =
  | { id: number; role: "founder"; text: string; at: Date }
  | { id: number; role: "heroos"; text: string; safeNextStep: string | null; at: Date };

async function failureOf(response: Response): Promise<Failure> {
  switch (response.status) {
    case 401:
      return "session_expired";
    case 403:
      return "refused";
    case 413:
    case 422:
      return "invalid";
    case 429:
      return "rate_limited";
    case 504:
      return "timeout";
    case 503: {
      const body = (await response.json().catch(() => null)) as { error?: unknown } | null;
      return body?.error === "not_configured" || body?.error === "knowledge_unavailable" ? "unavailable_guidance" : "unavailable";
    }
    default:
      return "unavailable";
  }
}

export function AskConversation({
  companyId,
  returning,
  notice,
  fetcher,
}: {
  companyId: string;
  returning: boolean;
  /** The API's notice for this deployment (for example: development content), shown as given. */
  notice: string | null;
  fetcher?: typeof fetch;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<{ text: string; at: Date } | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  // What HeroOS last asked about, signed by the API; sent back unchanged.
  const continuation = useRef<string | null>(null);
  const nextId = useRef(0);
  const inFlight = useRef(false);
  // After the docked box, so scrolling to it leaves the newest turn above the box, not under it.
  const end = useRef<HTMLDivElement>(null);

  const value = text.trim();
  const canSend = value.length > 0 && pending === null;

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [turns.length, pending]);

  // Sending the first message (or a first message failing) swaps the landing and the
  // conversation, and with them the box: keep keyboard focus in it.
  const inConversation = turns.length > 0 || pending !== null;
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    document.getElementById("ask-heroos")?.focus();
  }, [inConversation]);

  async function send() {
    if (!canSend || inFlight.current) return;
    const message = value;
    const history: ChatTurn[] = turns.map((turn) => ({
      role: turn.role === "founder" ? "user" : "assistant",
      content: turn.text,
    }));
    const at = new Date();
    inFlight.current = true;
    setFailure(null);
    // The message moves into the conversation: shown once, never also in the box.
    setPending({ text: message, at });
    setText("");
    let delivered = false;
    try {
      const response = await (fetcher ?? fetch)(`/bff/companies/${encodeURIComponent(companyId)}/assistant/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(gatewayRequest(message, history, continuation.current)),
        cache: "no-store",
        credentials: "same-origin",
        redirect: "error",
        // Up to four model requests behind it, and a free-tier API may be waking up.
        signal: AbortSignal.timeout(58_000),
      });
      const reply = response.status === 200 ? parseGatewayReply(await response.json().catch(() => null)) : null;
      if (reply === null) {
        setFailure(response.status === 200 ? "unavailable" : await failureOf(response));
        return;
      }
      continuation.current = reply.continuation;
      delivered = true;
      setTurns((current) => [
        ...current,
        { id: nextId.current++, role: "founder", text: message, at },
        { id: nextId.current++, role: "heroos", text: reply.reply, safeNextStep: reply.safeNextStep, at: new Date() },
      ]);
    } catch {
      setFailure("unavailable");
    } finally {
      inFlight.current = false;
      setPending(null);
      // Anything but a reply: the words go back in the box, to send again or edit.
      if (!delivered) setText(message);
    }
  }

  function startOver() {
    setTurns([]);
    setFailure(null);
    continuation.current = null;
  }

  const composer = (compact: boolean) => (
    <>
      <Composer
        canSend={canSend}
        compact={compact}
        describedBy={failure ? "ask-status" : notice ? "ask-notice" : undefined}
        maxLength={MAX_MESSAGE_CHARS}
        onChange={(next) => {
          setText(next);
          if (failure) setFailure(null);
        }}
        onSend={() => void send()}
        placeholder={
          pending
            ? "HeroOS is answering…"
            : compact
              ? "Reply in your own words."
              : "For example: one of my team hasn't come in for two days and isn't answering."
        }
        // While HeroOS answers, the box is empty and waits (a failed message comes back into it).
        readOnly={pending !== null}
        value={text}
      />
      {failure ? (
        <AskAlert>
          {FAILURES[failure]}
          {failure === "session_expired" ? <SignInAgain /> : null}
        </AskAlert>
      ) : null}
      {notice ? (
        <p className="mt-3 text-center text-[0.8125rem] text-hero-muted" id="ask-notice">
          {notice}
        </p>
      ) : null}
    </>
  );

  if (!inConversation) {
    return <AskLanding returning={returning}>{composer(false)}</AskLanding>;
  }

  return (
    <div className="mx-auto flex w-full max-w-[46rem] flex-1 flex-col px-4 pb-4 pt-3 sm:px-6 sm:pt-7">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-[0.8125rem] font-bold uppercase tracking-[0.1em] text-hero-muted">Ask HeroOS</h1>
        <button
          className="rounded-full px-3 py-1.5 text-[0.8125rem] font-bold text-hero-blue-ink hover:bg-hero-navy/[0.05] disabled:cursor-not-allowed disabled:opacity-60"
          disabled={pending !== null}
          onClick={startOver}
          type="button"
        >
          New conversation
        </button>
      </div>
      <ol aria-label="Conversation with HeroOS" aria-live="polite" aria-relevant="additions" className="mt-4 flex flex-1 flex-col gap-7">
        {turns.map((turn) =>
          turn.role === "founder" ? (
            <li key={turn.id}>
              <FounderTurn at={turn.at} text={turn.text} />
            </li>
          ) : (
            <li key={turn.id}>
              <HeroTurn at={turn.at} safeNextStep={turn.safeNextStep} text={turn.text} />
            </li>
          ),
        )}
        {pending ? (
          <>
            <li>
              <FounderTurn at={pending.at} text={pending.text} />
            </li>
            <li className="ws-rise-late">
              <Thinking />
            </li>
          </>
        ) : null}
      </ol>
      <div className="sticky bottom-0 mt-6 bg-gradient-to-t from-hero-bg from-60% to-transparent pb-2 pt-4">
        {composer(true)}
        <p className="mt-2 text-center text-[0.75rem] text-hero-muted">
          This conversation isn&apos;t saved: reloading the page clears it. HeroOS doesn&apos;t make employment decisions.
        </p>
      </div>
      <div aria-hidden="true" ref={end} />
    </div>
  );
}

function FounderTurn({ text, at }: { text: string; at: Date }) {
  return (
    <div aria-label="You" role="group">
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
    </div>
  );
}

/** One of HeroOS's replies: always the same neutral style (no outcome is decided here). */
function HeroTurn({ text, safeNextStep, at }: { text: string; safeNextStep: string | null; at: Date }) {
  return (
    <div aria-label="HeroOS" role="group">
      <div className="flex items-center gap-3">
        <AdviserMark />
        <p className="flex items-baseline gap-2 text-[0.875rem]">
          <span className="font-extrabold text-hero-navy">HeroOS</span>
          <time className="text-xs tabular-nums text-hero-muted">{TIME.format(at)}</time>
        </p>
      </div>
      <div className="mt-2 space-y-3 border-l-2 border-hero-navy/[0.12] pl-4 text-base leading-[1.65] text-hero-navy sm:ml-[0.9375rem] sm:pl-[1.6875rem]">
        <p className="whitespace-pre-wrap break-words">{text}</p>
        {safeNextStep ? (
          <div className="rounded-2xl border border-hero-navy/[0.1] bg-white px-4 py-3">
            <p className="text-[0.75rem] font-bold uppercase tracking-[0.1em] text-hero-muted">Safe next step</p>
            <p className="mt-1 whitespace-pre-wrap break-words">{safeNextStep}</p>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** While HeroOS answers: the mark and three dots (no visible reasoning). */
function Thinking() {
  return (
    <div aria-label="HeroOS is answering" role="status">
      <div className="flex items-center gap-3">
        <AdviserMark breathe />
        <p className="text-[0.875rem]">
          <span className="font-extrabold text-hero-navy">HeroOS</span>{" "}
          <span className="font-medium text-hero-muted">is thinking this through</span>
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
    </div>
  );
}
