"use client";

import { useEffect, useRef, useState } from "react";

import { boundedHistory, type ChatTurn, MAX_MESSAGE_CHARS } from "@/lib/assistant/model";

import { FounderTurn, HeroTurn, Thinking } from "./ask-conversation";
import { AskAlert, AskLanding, Composer, SignInAgain } from "./ask-parts";

/**
 * Ask HeroOS's staging chat-only demo (`HEROOS_CHAT_ONLY_DEMO` on the API,
 * temporary; production refuses it): one continuous conversation with
 * HeroOS's model, and nothing else. The API decides when this is shown (its
 * status says `chatOnly`), never this page.
 *
 * Send posts the founder's words and the recent turns to
 * `/bff/companies/{id}/assistant/chat`; the API checks the reply before it
 * comes back. Nothing opens a case or stores anything: no Case, facts,
 * workflow position, steps, outcome card, Expert Review or History. The
 * conversation lives in this page's memory only, and a reload starts a new one.
 */

type Failure = "session_expired" | "refused" | "invalid" | "rate_limited" | "timeout" | "unavailable";

const FAILURES: Record<Failure, string> = {
  session_expired: "Your session has ended. Sign in again, then ask again.",
  refused: "Only company administrators can ask HeroOS for now.",
  invalid: "HeroOS couldn't accept this text. Remove any unusual characters and try again.",
  rate_limited: "HeroOS has had a lot of questions just now. Please wait a moment and send again: your message is still in the box.",
  timeout: "HeroOS took too long to answer. Please send again: your message is still in the box.",
  unavailable: "HeroOS couldn't answer just now. Please send again: your message is still in the box.",
};

function failureOf(status: number): Failure {
  switch (status) {
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
    default:
      return "unavailable";
  }
}

function replyOf(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const { reply } = body as Record<string, unknown>;
  return typeof reply === "string" && reply.trim().length > 0 ? reply : null;
}

type Turn = ChatTurn & { id: number; at: Date };

export function AskChat({
  companyId,
  returning,
  notice,
  available,
  fetcher,
}: {
  companyId: string;
  returning: boolean;
  /** The API's demo notice, shown as given. */
  notice: string | null;
  /** HeroOS can answer now (the API has a model for it). */
  available: boolean;
  fetcher?: typeof fetch;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<{ text: string; at: Date } | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const inFlight = useRef(false);
  const nextId = useRef(0);
  // After the docked box, so scrolling to it leaves the newest turn above the box, not under it.
  const end = useRef<HTMLDivElement>(null);

  const value = text.trim();
  const canSend = available && value.length > 0 && pending === null;
  const inConversation = turns.length > 0 || pending !== null;

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [turns.length, pending]);

  // The first message swaps the landing and the conversation, and with them the box: keep focus in it.
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
    const at = new Date();
    inFlight.current = true;
    setFailure(null);
    // The message moves into the conversation: shown once, never also in the box.
    setPending({ text: message, at });
    setText("");
    let delivered = false;
    try {
      const response = await (fetcher ?? fetch)(`/bff/companies/${encodeURIComponent(companyId)}/assistant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ message, history: boundedHistory(turns) }),
        cache: "no-store",
        credentials: "same-origin",
        redirect: "error",
        // The API waits up to 45 s on the model, and a free-tier API may be waking up.
        signal: AbortSignal.timeout(58_000),
      });
      const reply = response.status === 200 ? replyOf(await response.json().catch(() => null)) : null;
      if (reply === null) {
        setFailure(response.status === 200 ? "unavailable" : failureOf(response.status));
        return;
      }
      delivered = true;
      const id = nextId.current;
      nextId.current += 2;
      setTurns((all) => [
        ...all,
        { id, role: "user", content: message, at },
        { id: id + 1, role: "assistant", content: reply, at: new Date() },
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
  }

  const composer = (compact: boolean) => (
    <>
      <Composer
        canSend={canSend}
        compact={compact}
        describedBy={failure ? "ask-status" : notice ? "ask-notice" : undefined}
        disabled={!available}
        maxLength={MAX_MESSAGE_CHARS}
        onChange={(next) => {
          setText(next);
          if (failure) setFailure(null);
        }}
        onSend={() => void send()}
        placeholder={
          !available
            ? "HeroOS can't answer right now."
            : pending
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

  if (!inConversation) return <AskLanding returning={returning}>{composer(false)}</AskLanding>;

  return (
    <div className="mx-auto flex w-full max-w-[46rem] flex-1 flex-col px-4 pb-4 pt-3 sm:px-6 sm:pt-7">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-[0.8125rem] font-bold uppercase tracking-[0.1em] text-hero-muted">Ask HeroOS</h1>
        <button
          className="min-h-10 rounded-full px-3 text-[0.8125rem] font-bold text-hero-blue-ink hover:bg-hero-navy/[0.05] disabled:cursor-not-allowed disabled:opacity-60"
          disabled={pending !== null}
          onClick={startOver}
          type="button"
        >
          New conversation
        </button>
      </div>
      <ol aria-label="Conversation with HeroOS" aria-live="polite" aria-relevant="additions" className="mt-4 flex flex-1 flex-col gap-7">
        {turns.map((turn) => (
          <li key={turn.id}>
            {turn.role === "assistant" ? (
              <HeroTurn at={turn.at} id={turn.id} outcome={null} safeNextStep={null} text={turn.content} />
            ) : (
              <FounderTurn at={turn.at} by="you" text={turn.content} />
            )}
          </li>
        ))}
        {pending ? (
          <>
            <li>
              <FounderTurn at={pending.at} by="you" text={pending.text} />
            </li>
            <li className="ws-rise-late">
              <Thinking />
            </li>
          </>
        ) : null}
      </ol>
      <div className="sticky bottom-0 mt-6 bg-gradient-to-t from-hero-bg from-60% to-transparent pb-2 pt-4">
        {composer(true)}
        <p className="mt-2 text-center text-[0.75rem] text-hero-muted">HeroOS doesn&apos;t make employment decisions.</p>
      </div>
      <div aria-hidden="true" ref={end} />
    </div>
  );
}
