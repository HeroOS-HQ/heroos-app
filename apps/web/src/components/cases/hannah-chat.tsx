"use client";

import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";

import { AlertIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { buttonPrimary } from "@/components/ui/styles";
import {
  type AssistantStatus,
  boundedHistory,
  type ChatTurn,
  isAssistantReply,
  isAssistantStatus,
  MAX_MESSAGE_CHARS,
} from "@/lib/assistant/model";

/**
 * The Hannah AI demo: a conversation with a language model about fictional
 * scenarios, under the guided conversation. It is NOT the case record:
 * nothing here is saved, nothing changes the Case, and the panels around it
 * keep showing only what the API recorded. The turns live in this
 * component's state and are gone on reload. Shown only when the API says this
 * administrator can use it (the demo switch and the tester list).
 */

// The BFF waits up to 45 s for the API (lib/server/heroos-api.ts), within the
// route's 60 s maxDuration; the browser waits a little longer than the BFF.
export const HANNAH_BROWSER_TIMEOUT_MS = 55_000;
export const NOTICE =
  "Hannah AI Demo — Use fictional employee scenarios only. Responses are exploratory and do not authorize disciplinary decisions.";

type Turn = ChatTurn & { id: number; failed?: boolean };
type Load = { state: "loading" } | { state: "hidden" } | { state: "ready"; status: AssistantStatus };
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
    title: "Hannah AI isn't available for your account",
    body: "Reload the page to see the case as it is now.",
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

function HannahAvatar() {
  return (
    <span
      aria-hidden="true"
      className="inline-flex size-9 shrink-0 overflow-hidden rounded-full border border-hero-border bg-hero-blue-tint"
    >
      {/* Plain <img>: next/image adds an inline style attribute the CSP forbids. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        className="size-full object-cover object-top"
        height={900}
        src="/branding/hannah-hero-front.webp"
        width={600}
      />
    </span>
  );
}

export function HannahChat({
  companyId,
  caseId,
  fetcher,
}: {
  companyId: string;
  caseId: string;
  fetcher?: typeof fetch;
}) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const nextId = useRef(1);
  // Bumped by "Start over": a reply to an earlier conversation is dropped.
  const conversation = useRef(0);
  const logRef = useRef<HTMLOListElement>(null);
  const base = `/bff/companies/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}/assistant`;

  useEffect(() => {
    let current = true;
    void (async () => {
      try {
        const response = await (fetcher ?? fetch)(base, {
          headers: { Accept: "application/json" },
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
        });
        const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
        if (!current) return;
        const status = response.status === 200 && body && isAssistantStatus(body.status) ? body.status : null;
        // Off, or not for this person (a member, an older API): the page stays as it was.
        setLoad(status === null || status.reason === "disabled" ? { state: "hidden" } : { state: "ready", status });
      } catch {
        if (current) setLoad({ state: "hidden" });
      }
    })();
    return () => {
      current = false;
    };
  }, [base, fetcher]);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [turns, pending]);

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
    const message: Turn = { id: nextId.current++, role: "user", content };
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

  if (load.state !== "ready") return null;
  const { status } = load;

  return (
    <section
      aria-labelledby="hannah-heading"
      className="mt-6 rounded-3xl border border-dashed border-hero-blue/50 bg-white p-4 shadow-hero-card sm:p-6"
      data-testid="hannah-chat"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <HannahAvatar />
          <div>
            <h3 className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy" id="hannah-heading">
              Talk it through with Hannah
            </h3>
            <p className="text-sm text-hero-muted">AI demo · not part of the case record · not saved</p>
          </div>
        </div>
        {status.available ? (
          <button
            className="inline-flex min-h-11 items-center rounded-full border border-hero-control bg-white px-4 text-sm font-bold text-hero-navy hover:bg-hero-blue-tint disabled:cursor-not-allowed disabled:opacity-60"
            disabled={turns.length === 0 && draft.length === 0 && failure === null}
            onClick={restart}
            type="button"
          >
            Start over
          </button>
        ) : null}
      </div>

      <p className="mt-4 rounded-2xl border border-[#f1df8d] bg-hero-yellow-tint px-4 py-3 text-sm font-semibold leading-relaxed text-hero-navy">
        {NOTICE}
      </p>

      {!status.available ? (
        <Notice
          className="mt-4"
          title={
            status.reason === "not_configured"
              ? FAILURE_TEXT.not_configured.title
              : "Hannah AI isn't enabled for your account"
          }
        >
          {status.reason === "not_configured"
            ? FAILURE_TEXT.not_configured.body
            : "This demo is open to approved testers only in this environment. The guided case workflow works as usual."}
        </Notice>
      ) : (
        <>
          <ol
            aria-label="Conversation with Hannah (AI demo)"
            aria-live="polite"
            className="mt-4 flex max-h-[28rem] flex-col gap-3 overflow-y-auto pr-1"
            ref={logRef}
            role="log"
          >
            {turns.length === 0 ? (
              <li className="flex items-start gap-3">
                <HannahAvatar />
                <p className="max-w-[40rem] rounded-2xl rounded-tl-md border border-dashed border-hero-blue/40 bg-hero-blue-tint/50 px-4 py-3 text-[0.9375rem] leading-relaxed text-hero-navy">
                  Hi, I&apos;m Hannah. Tell me what happened in your made-up scenario, and we&apos;ll work through it
                  together.
                </p>
              </li>
            ) : null}
            {turns.map((turn) =>
              turn.role === "user" ? (
                <li className="flex flex-col items-end gap-1" key={turn.id}>
                  <p className="sr-only">You:</p>
                  <p className="max-w-[36rem] whitespace-pre-wrap break-words rounded-2xl rounded-tr-md border border-[#cfe0f8] bg-hero-blue-tint px-4 py-3 text-[0.9375rem] leading-relaxed text-hero-navy">
                    {turn.content}
                  </p>
                  {turn.failed ? <span className="text-xs font-bold text-hero-danger">Not answered</span> : null}
                </li>
              ) : (
                <li className="flex items-start gap-3" data-role="assistant" key={turn.id}>
                  <HannahAvatar />
                  <div className="min-w-0 max-w-[40rem] flex-1">
                    <p className="sr-only">Hannah (AI demo):</p>
                    <p className="whitespace-pre-wrap break-words rounded-2xl rounded-tl-md border border-dashed border-hero-blue/40 bg-white px-4 py-3 text-[0.9375rem] leading-relaxed text-hero-navy">
                      {turn.content}
                    </p>
                    <span className="mt-1 inline-block text-xs font-bold text-hero-muted">
                      AI · exploratory, not saved
                    </span>
                  </div>
                </li>
              ),
            )}
            {pending ? (
              <li className="flex items-center gap-3">
                <HannahAvatar />
                <p className="text-sm font-semibold text-hero-muted" role="status">
                  Hannah is thinking…
                </p>
              </li>
            ) : null}
          </ol>

          {failure ? (
            <div
              className="mt-4 flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-[#e9b4c0] bg-hero-danger-tint px-4 py-3 text-hero-navy"
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
                <button
                  className="inline-flex min-h-11 items-center rounded-full border border-hero-control bg-white px-4 text-sm font-bold text-hero-navy hover:bg-hero-blue-tint disabled:opacity-60"
                  disabled={pending}
                  onClick={retry}
                  type="button"
                >
                  Retry message
                </button>
              ) : null}
            </div>
          ) : null}

          <form autoComplete="off" className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end" onSubmit={send}>
            <div className="min-w-0 flex-1">
              <label className="sr-only" htmlFor="hannah-message">
                Message Hannah
              </label>
              <textarea
                aria-describedby="hannah-hint"
                className="block max-h-48 min-h-12 w-full resize-y rounded-xl border border-hero-control bg-white px-4 py-3 text-base text-hero-navy placeholder:text-hero-muted focus:border-hero-blue"
                id="hannah-message"
                maxLength={MAX_MESSAGE_CHARS}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Describe a fictional situation…"
                rows={2}
                value={draft}
              />
              <p className="mt-1 text-xs text-hero-muted" id="hannah-hint">
                Enter to send · Shift+Enter for a new line
                {draft.length > MAX_MESSAGE_CHARS - 200 ? ` · ${MAX_MESSAGE_CHARS - draft.length} characters left` : ""}
              </p>
            </div>
            <button
              className={`${buttonPrimary} sm:mb-6`}
              disabled={pending || draft.trim().length === 0}
              type="submit"
            >
              {pending ? "Sending…" : "Send"}
            </button>
          </form>
        </>
      )}
    </section>
  );
}
