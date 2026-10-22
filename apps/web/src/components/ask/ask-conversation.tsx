"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { AdviserMark, PersonAvatar } from "@/components/app/workspace-chrome";
import { ClockIcon } from "@/components/site/icons";
import {
  type Conversation,
  type ConversationDetail,
  type ConversationMessage,
  gatewayRequest,
  MAX_MESSAGE_CHARS,
  type Outcome,
  parseConversationDetail,
  parseGatewayTurn,
  parseMessagePage,
  type StepKind,
} from "@/lib/ask/conversation";

import { AskAlert, AskLanding, Composer, SignInAgain } from "./ask-parts";
import { ConversationContext } from "./conversation-context";
import { ConversationHistory } from "./conversation-history";
import { AdviserTurn, type Outcome as Tone, OutcomeLabel } from "./response-tone";

/**
 * Ask HeroOS as a conversation (M2-NEW-05). The founder explains the situation
 * in their own words; HeroOS answers from its approved guidance through the
 * controlled gateway (`/bff/companies/{id}/assistant/messages`), asking what
 * it needs next. Nothing to choose: no workflow, pathway, stage, title or
 * jurisdiction. Free text is always the way to answer.
 *
 * The outcome (M2-NEW-06) is the API's deterministic result, never the
 * model's: Guidance, Warning, Block or Expert Review, in JJ's approved tones
 * with words and an icon (never colour alone), a line per requested step and
 * the server's safe next step. A Block holds one step, never the conversation,
 * and Expert Review is a requirement, not a ticket: the box stays free to type
 * in, whatever the outcome. When the checks can't run, a neutral note says so
 * (never an HR outcome).
 *
 * The conversation is stored by the API (M2-NEW-07), so nothing here depends
 * on this page staying open. This page sends only the founder's words, a turn
 * key (reused when the same failed message is sent again, so a lost answer is
 * never asked twice), the conversation id and the revision it last saw. The
 * open conversation is in the address (`?conversation=`): a reload, or a link
 * from its Case, opens it again with its latest messages, and earlier ones a
 * page at a time. History lists the Company's conversations; another
 * administrator's messages say so. When the conversation moved on elsewhere
 * (another tab, another administrator), the page shows the latest and keeps
 * the unsent words in the box. "New conversation" only starts a new one here:
 * nothing is deleted, and nothing is stored until HeroOS answers.
 */

type Failure =
  | "session_expired"
  | "refused"
  | "invalid"
  | "conflict"
  | "rate_limited"
  | "timeout"
  | "unavailable_guidance"
  | "unavailable";

const FAILURES: Record<Failure, string> = {
  session_expired: "Your session has ended. Sign in again, then ask again.",
  refused: "Only company administrators can ask HeroOS for now.",
  invalid: "HeroOS couldn't accept this text. Remove any unusual characters and try again.",
  conflict: "HeroOS couldn't send this message. Start a new conversation: your message is still in the box.",
  rate_limited: "HeroOS has had a lot of questions just now. Please wait a moment and send again: your message is still in the box.",
  timeout: "HeroOS took too long to answer. Please send again: your message is still in the box.",
  unavailable_guidance: "HeroOS's approved guidance isn't available right now. Please try again later: your message is still in the box.",
  unavailable: "HeroOS couldn't answer just now. Please send again: your message is still in the box.",
};

const CHANGED =
  "This conversation was updated in another tab or by another administrator. Here is the latest: your message is still in the box, so read it again before you send.";

const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });
const DAY_TIME = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** "14:05" today, "21 Oct, 14:05" before. */
function when(at: Date, now = new Date()): string {
  return at.toDateString() === now.toDateString() ? TIME.format(at) : DAY_TIME.format(at);
}

// The API's outcome kinds as the approved tones (response-tone.tsx).
const TONES: Record<StepKind, Tone> = { guidance: "guidance", warning: "warning", block: "block", expert_review: "expert" };

/** Opening a conversation (from the address, History or a Case): loading, or why it couldn't. */
type Opening = { kind: "loading" } | { kind: "missing" } | { kind: "failed"; id: string };

async function failureOf(response: Response): Promise<Failure> {
  switch (response.status) {
    case 401:
      return "session_expired";
    case 403:
      return "refused";
    case 413:
    case 422:
      return "invalid";
    case 409:
      return "conflict";
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

/** The stored messages with ``more`` added, oldest first, each sequence once. */
function merged(current: ConversationMessage[], more: ConversationMessage[]): ConversationMessage[] {
  const bySequence = new Map(current.map((m) => [m.sequence, m]));
  for (const message of more) bySequence.set(message.sequence, message);
  return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
}

/** The open conversation in the address (replaced, never a new history entry). */
function showInAddress(id: string | null) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (id === null) url.searchParams.delete("conversation");
  else url.searchParams.set("conversation", id);
  if (url.href !== window.location.href) window.history.replaceState(null, "", url);
}

const READ = { headers: { Accept: "application/json" }, cache: "no-store", credentials: "same-origin", redirect: "error" } as const;

export function AskConversation({
  companyId,
  returning,
  notice,
  available = true,
  initialConversationId = null,
  fetcher,
}: {
  companyId: string;
  returning: boolean;
  /** The API's notice for this deployment (for example: development content), shown as given. */
  notice: string | null;
  /** HeroOS can answer now; when it can't, stored conversations can still be read. */
  available?: boolean;
  /** The conversation to open first (from the address). */
  initialConversationId?: string | null;
  fetcher?: typeof fetch;
}) {
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [current, setCurrent] = useState<Conversation | null>(null);
  // The sequence to read earlier messages before (none when the first is shown).
  const [earlier, setEarlier] = useState<number | null>(null);
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const [opening, setOpening] = useState<Opening | null>(initialConversationId ? { kind: "loading" } : null);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<{ text: string; at: Date } | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [changed, setChanged] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  // The last unanswered message and its turn key: sending the same words again reuses the key.
  const retry = useRef<{ text: string; key: string } | null>(null);
  const inFlight = useRef(false);
  // The conversation the page is opening now (a later choice wins over an earlier one).
  const wanted = useRef<string | null>(initialConversationId);
  const historyButton = useRef<HTMLButtonElement>(null);
  // After the docked box, so scrolling to it leaves the newest turn above the box, not under it.
  const end = useRef<HTMLDivElement>(null);

  const value = text.trim();
  const busy = pending !== null || opening?.kind === "loading";
  const canSend = available && value.length > 0 && !busy;
  const newest = messages.at(-1)?.sequence ?? 0;

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [newest, pending]);

  // Sending the first message (or a first message failing) swaps the landing and the
  // conversation, and with them the box: keep keyboard focus in it.
  const inConversation = current !== null || messages.length > 0 || pending !== null || opening?.kind === "loading";
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    document.getElementById("ask-heroos")?.focus();
  }, [inConversation]);

  /** A stored conversation's status and latest messages, as the API has them now. */
  const fetchDetail = useCallback(
    async (id: string): Promise<{ status: number; detail: ConversationDetail | null }> => {
      try {
        const response = await (fetcher ?? fetch)(`/bff/companies/${encodeURIComponent(companyId)}/assistant/conversations/${encodeURIComponent(id)}`, {
          ...READ,
          signal: AbortSignal.timeout(30_000),
        });
        const detail = response.status === 200 ? parseConversationDetail(await response.json().catch(() => null)) : null;
        return { status: response.status, detail };
      } catch {
        return { status: 0, detail: null };
      }
    },
    [companyId, fetcher],
  );

  /** Shows what was read for `id`, unless another conversation was chosen meanwhile. */
  const apply = useCallback((id: string, { status, detail }: { status: number; detail: ConversationDetail | null }) => {
    if (wanted.current !== id) return false;
    if (detail === null) {
      if (status === 401) setFailure("session_expired");
      setOpening(status === 404 ? { kind: "missing" } : { kind: "failed", id });
      if (status === 404) showInAddress(null);
      return false;
    }
    setCurrent(detail.conversation);
    setMessages(detail.messages);
    setEarlier(detail.nextBefore);
    setOpening(null);
    showInAddress(detail.conversation.id);
    return true;
  }, []);

  /** Opens a stored conversation (History, a retry, or after it moved on elsewhere). */
  async function open(id: string): Promise<boolean> {
    wanted.current = id;
    setOpening({ kind: "loading" });
    return apply(id, await fetchDetail(id));
  }

  useEffect(() => {
    // The conversation in the address when the page opened (its loading state is the initial one).
    const id = initialConversationId;
    if (id) void fetchDetail(id).then((result) => apply(id, result));
  }, [initialConversationId, fetchDetail, apply]);

  async function send() {
    if (!canSend || inFlight.current) return;
    const message = value;
    const key = retry.current?.text === message ? retry.current.key : crypto.randomUUID();
    retry.current = { text: message, key };
    const at = new Date();
    inFlight.current = true;
    setFailure(null);
    setChanged(false);
    // The message moves into the conversation: shown once, never also in the box.
    setPending({ text: message, at });
    setText("");
    let delivered = false;
    try {
      const response = await (fetcher ?? fetch)(`/bff/companies/${encodeURIComponent(companyId)}/assistant/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(gatewayRequest(message, key, current?.id ?? null, current?.revision ?? 0)),
        cache: "no-store",
        credentials: "same-origin",
        redirect: "error",
        // Up to four model requests behind it, and a free-tier API may be waking up.
        signal: AbortSignal.timeout(58_000),
      });
      const reply = response.status === 200 ? parseGatewayTurn(await response.json().catch(() => null)) : null;
      if (reply === null) {
        if (response.status === 409 && current !== null) {
          // Moved on elsewhere: show the latest, never overwrite it; the words stay in the box.
          if (await open(current.id)) setChanged(true);
          else setFailure("unavailable");
          return;
        }
        setFailure(response.status === 200 ? "unavailable" : await failureOf(response));
        return;
      }
      retry.current = null;
      delivered = true;
      wanted.current = reply.conversation.id;
      setCurrent(reply.conversation);
      setMessages((stored) => merged(stored, reply.messages));
      showInAddress(reply.conversation.id);
    } catch {
      setFailure("unavailable");
    } finally {
      inFlight.current = false;
      setPending(null);
      // Anything but a reply: the words go back in the box, to send again or edit.
      if (!delivered) setText(message);
    }
  }

  async function showEarlier() {
    if (current === null || earlier === null || loadingEarlier) return;
    setLoadingEarlier(true);
    try {
      const response = await (fetcher ?? fetch)(
        `/bff/companies/${encodeURIComponent(companyId)}/assistant/conversations/${encodeURIComponent(current.id)}/messages?before=${earlier}`,
        { ...READ, signal: AbortSignal.timeout(30_000) },
      );
      const page = response.status === 200 ? parseMessagePage(await response.json().catch(() => null)) : null;
      if (page === null) {
        setFailure(response.status === 401 ? "session_expired" : "unavailable");
        return;
      }
      setMessages((stored) => merged(stored, page.messages));
      setEarlier(page.nextBefore);
    } catch {
      setFailure("unavailable");
    } finally {
      setLoadingEarlier(false);
    }
  }

  function startOver() {
    // A new conversation here; the previous one stays stored. Nothing is stored until HeroOS answers.
    wanted.current = null;
    setHistoryOpen(false);
    setCurrent(null);
    setMessages([]);
    setEarlier(null);
    setOpening(null);
    setFailure(null);
    setChanged(false);
    retry.current = null;
    showInAddress(null);
  }

  function choose(id: string) {
    setHistoryOpen(false);
    if (id === current?.id) return;
    setFailure(null);
    setChanged(false);
    retry.current = null;
    void open(id);
  }

  const historyControl = (
    <button
      aria-expanded={historyOpen}
      aria-haspopup="dialog"
      className="inline-flex min-h-10 items-center gap-1.5 rounded-full px-3 text-[0.8125rem] font-bold text-hero-blue-ink hover:bg-hero-navy/[0.05] disabled:cursor-not-allowed disabled:opacity-60"
      disabled={pending !== null}
      onClick={() => setHistoryOpen(true)}
      ref={historyButton}
      type="button"
    >
      <ClockIcon className="size-4" />
      History
    </button>
  );

  // Above the whole page, header included: inside the main region it would sit under the
  // sticky header and the footer (workspace-chrome's own stacking contexts).
  const history = historyOpen ? createPortal(
    <ConversationHistory
      companyId={companyId}
      currentId={current?.id ?? null}
      fetcher={fetcher}
      onChoose={choose}
      onClose={() => setHistoryOpen(false)}
      onNew={startOver}
      returnTo={historyButton}
    />,
    document.body,
  ) : null;

  const composer = (compact: boolean) => (
    <>
      <Composer
        canSend={canSend}
        compact={compact}
        describedBy={failure || changed ? "ask-status" : notice ? "ask-notice" : undefined}
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
        readOnly={busy}
        value={text}
      />
      {failure ? (
        <AskAlert>
          {FAILURES[failure]}
          {failure === "session_expired" ? <SignInAgain /> : null}
        </AskAlert>
      ) : changed ? (
        <p className="ws-rise mt-3 rounded-2xl border border-hero-border bg-white px-4 py-3 text-left text-[0.9375rem] text-hero-navy" id="ask-status" role="status">
          {CHANGED}
        </p>
      ) : null}
      {notice ? (
        <p className="mt-3 text-center text-[0.8125rem] text-hero-muted" id="ask-notice">
          {notice}
        </p>
      ) : null}
    </>
  );

  if (!inConversation) {
    return (
      <>
        <AskLanding returning={returning}>
          {opening?.kind === "missing" ? (
            <AskAlert>HeroOS couldn&apos;t find that conversation. Open History to see your company&apos;s conversations.</AskAlert>
          ) : opening?.kind === "failed" ? (
            <AskAlert>
              HeroOS couldn&apos;t open that conversation just now.{" "}
              <button className="font-bold text-hero-blue-ink underline" onClick={() => void open(opening.id)} type="button">
                Try again
              </button>
            </AskAlert>
          ) : null}
          <div className={opening?.kind === "missing" || opening?.kind === "failed" ? "mt-4" : undefined}>{composer(false)}</div>
          <div className="mt-3 flex justify-center">{historyControl}</div>
        </AskLanding>
        {history}
      </>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-[46rem] flex-1 flex-col px-4 pb-4 pt-3 sm:px-6 sm:pt-7">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-[0.8125rem] font-bold uppercase tracking-[0.1em] text-hero-muted">Ask HeroOS</h1>
        <div className="flex items-center gap-1">
          {historyControl}
          <button
            className="min-h-10 rounded-full px-3 text-[0.8125rem] font-bold text-hero-blue-ink hover:bg-hero-navy/[0.05] disabled:cursor-not-allowed disabled:opacity-60"
            disabled={pending !== null}
            onClick={startOver}
            type="button"
          >
            New conversation
          </button>
        </div>
      </div>
      {current ? <ConversationContext companyId={companyId} conversation={current} /> : null}
      {earlier !== null ? (
        <div className="mt-4 flex justify-center">
          <button
            className="min-h-10 rounded-full border border-hero-border bg-white px-4 text-[0.8125rem] font-bold text-hero-blue-ink hover:bg-hero-navy/[0.03] disabled:opacity-60"
            disabled={loadingEarlier}
            onClick={() => void showEarlier()}
            type="button"
          >
            {loadingEarlier ? "Loading earlier messages…" : "Load earlier messages"}
          </button>
        </div>
      ) : null}
      {opening?.kind === "loading" ? (
        <p className="mt-6 text-[0.9375rem] text-hero-muted" role="status">
          Opening the conversation…
        </p>
      ) : opening?.kind === "missing" ? (
        <div className="mt-4">
          <AskAlert>HeroOS couldn&apos;t find that conversation. Open History to see your company&apos;s conversations.</AskAlert>
        </div>
      ) : opening?.kind === "failed" ? (
        <div className="mt-4">
          <AskAlert>
            HeroOS couldn&apos;t open that conversation just now.{" "}
            <button className="font-bold text-hero-blue-ink underline" onClick={() => void open(opening.id)} type="button">
              Try again
            </button>
          </AskAlert>
        </div>
      ) : null}
      <ol aria-label="Conversation with HeroOS" aria-live="polite" aria-relevant="additions" className="mt-4 flex flex-1 flex-col gap-7">
        {messages.map((message) => (
          <li key={message.sequence}>
            {message.author === "heroos" ? (
              <HeroTurn
                at={new Date(message.createdAt)}
                id={message.sequence}
                outcome={message.outcome}
                safeNextStep={message.safeNextStep}
                text={message.text}
              />
            ) : (
              <FounderTurn at={new Date(message.createdAt)} by={message.author} text={message.text} />
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
      {history}
    </div>
  );
}

function FounderTurn({ text, at, by }: { text: string; at: Date; by: "you" | "another_administrator" }) {
  // Relative to the viewer: their own words are "You"; a colleague's never are.
  const name = by === "you" ? "You" : "Another administrator";
  return (
    <div aria-label={name} role="group">
      <div className="flex items-center gap-3">
        <PersonAvatar />
        <p className="flex items-baseline gap-2 text-[0.875rem]">
          <span className="font-bold text-hero-navy">{name}</span>
          <time className="text-xs tabular-nums text-hero-muted">{when(at)}</time>
        </p>
      </div>
      <p className="mt-2 whitespace-pre-wrap break-words rounded-2xl border border-hero-navy/[0.08] bg-white px-4 py-3 text-base leading-[1.65] text-hero-navy shadow-[0_1px_2px_rgb(14_30_61/0.04)] sm:ml-11">
        {text}
      </p>
    </div>
  );
}

function SafeNextStep({ text }: { text: string }) {
  return (
    <div className="rounded-2xl border border-hero-navy/[0.1] bg-white px-4 py-3">
      <p className="text-[0.75rem] font-bold uppercase tracking-[0.1em] text-hero-muted">Safe next step</p>
      <p className="mt-1 whitespace-pre-wrap break-words">{text}</p>
    </div>
  );
}

/**
 * One of HeroOS's replies. With a deterministic outcome: the approved outcome turn
 * (its label, the server's own words, a line per requested step, the reply, the safe
 * next step). Without one: the neutral style, and a note when the checks can't run.
 */
function HeroTurn({
  id,
  text,
  safeNextStep,
  outcome,
  at,
}: {
  id: number;
  text: string;
  safeNextStep: string | null;
  outcome: Outcome | null;
  at: Date;
}) {
  if (outcome !== null && outcome.kind !== "unavailable") {
    return (
      <AdviserTurn
        id={`ask-${id}`}
        outcome={TONES[outcome.kind]}
        time={<time className="tabular-nums">{when(at)}</time>}
        // A panel headline only where it says more than its label (e.g. "Not yet: Written warning").
        title={outcome.kind === "block" ? outcome.title : undefined}
      >
        {outcome.kind === "guidance" ? null : <p className="font-semibold">{outcome.message}</p>}
        {outcome.items.length > 0 ? (
          <ul aria-label="Each step you asked about" className="space-y-2">
            {outcome.items.map((item) => (
              <li className="flex items-start gap-2 text-[0.9375rem]" key={item.text}>
                <span className="shrink-0">
                  <OutcomeLabel outcome={TONES[item.kind]} />
                </span>
                <span className="min-w-0 flex-1 pt-0.5">{item.text}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="whitespace-pre-wrap break-words">{text}</p>
        {safeNextStep ? <SafeNextStep text={safeNextStep} /> : null}
      </AdviserTurn>
    );
  }
  return (
    <div aria-label="HeroOS" role="group">
      <div className="flex items-center gap-3">
        <AdviserMark />
        <p className="flex items-baseline gap-2 text-[0.875rem]">
          <span className="font-extrabold text-hero-navy">HeroOS</span>
          <time className="text-xs tabular-nums text-hero-muted">{when(at)}</time>
        </p>
      </div>
      <div className="mt-2 space-y-3 border-l-2 border-hero-navy/[0.12] pl-4 text-base leading-[1.65] text-hero-navy sm:ml-[0.9375rem] sm:pl-[1.6875rem]">
        {outcome?.kind === "unavailable" ? (
          <p className="text-[0.875rem] text-hero-muted" role="note">
            <span className="font-bold text-hero-navy">{outcome.title}.</span> {outcome.message}
          </p>
        ) : null}
        <p className="whitespace-pre-wrap break-words">{text}</p>
        {safeNextStep ? <SafeNextStep text={safeNextStep} /> : null}
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
