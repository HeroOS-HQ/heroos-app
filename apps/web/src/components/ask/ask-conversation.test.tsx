import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { COMPANY_ID } from "@/test/fixtures";

import { AskWorkspace } from "./ask-workspace";

const CONVERSATION_ID = "9b1f3c3e-6a52-4b8f-9d0a-2c1e5f6a7b8c";
const WORDS = "[SYNTHETIC] My employee has been late three times this month. What should I do?";
const REPLY = "Thanks for explaining. Has the expected standard been explained to him?";
const AT = "2026-10-22T10:00:00Z";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const STATUS = {
  lifecycle: null,
  workflow: null,
  attention: { needsInformation: false, jurisdiction: null, expertReview: { active: false, scope: null, actions: [], serviceAvailable: false } },
  checks: "not_applicable",
  latestOutcome: "none",
};
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
/** The BFF's stored turn: the conversation (at ``revision``) and its two visible messages. */
const answer = (text = REPLY, extra: Record<string, unknown> = {}, revision = 1, founder = WORDS) =>
  reply(200, {
    conversation: { id: CONVERSATION_ID, title: null, case: null, createdAt: AT, updatedAt: AT, revision, status: STATUS },
    messages: [
      { sequence: 2 * revision - 1, author: "you", text: founder, safeNextStep: null, conversationState: null, outcome: null, createdAt: AT },
      { sequence: 2 * revision, author: "heroos", text, safeNextStep: null, conversationState: "responded", outcome: null, createdAt: AT, ...extra },
    ],
    replayed: false,
  });

function setup(notice: string | null, ...responses: (Response | Error | Promise<Response>)[]) {
  const queue = [...responses];
  const fetcher = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(async () => {
    const next = queue.shift() ?? new Error("no response queued");
    if (next instanceof Error) throw next;
    return next;
  });
  const navigate = vi.fn();
  render(
    <AskWorkspace
      companyId={COMPANY_ID}
      conversation={{ available: true, reason: null, notice }}
      fetcher={fetcher as unknown as typeof fetch}
      mode="ready"
      navigate={navigate}
      returning={false}
    />,
  );
  return { fetcher, navigate };
}

const box = () => screen.getByRole("textbox", { name: "Explain the situation in your own words" });
const send = () => screen.getByRole("button", { name: "Send" });
const bodyOf = (fetcher: ReturnType<typeof setup>["fetcher"], index = 0) =>
  JSON.parse(String((fetcher.mock.calls[index] as [string, RequestInit])[1].body)) as Record<string, unknown>;

async function ask(words: string) {
  fireEvent.change(box(), { target: { value: words } });
  fireEvent.click(send());
}

describe("AskConversation (Ask HeroOS with the AI gateway)", () => {
  it("starts on the approved landing: one question, one box, nothing to choose", () => {
    setup(null);
    expect(screen.getByRole("heading", { level: 1, name: "What can HR do for you today?" })).toBeInTheDocument();
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    expect(document.body.textContent).not.toMatch(/Disciplinary|pathway|stage|workflow|jurisdiction|category/i);
    expect(send()).toBeDisabled();
  });

  it("asks HeroOS in the page, then shows the reply and keeps the box free", async () => {
    const { fetcher, navigate } = setup(null, answer());
    await ask(`  ${WORDS}\n`);
    expect(await screen.findByText(REPLY)).toBeInTheDocument();
    expect(screen.getByText(WORDS)).toBeInTheDocument();
    const [url, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/assistant/messages`);
    expect(url).not.toContain("/ask");
    expect(init.method).toBe("POST");
    // A new conversation: its words and a turn key, nothing else.
    const body = bodyOf(fetcher);
    expect(body).toEqual({ message: WORDS, turnKey: body.turnKey, conversationId: null, expectedRevision: 0 });
    expect(String(body.turnKey)).toMatch(UUID);
    expect(navigate).not.toHaveBeenCalled();
    // Free text stays the way to answer.
    expect(box()).toHaveValue("");
    expect(box()).not.toHaveAttribute("readonly");
    // Restrained, truthful footer: no "not saved" claim, no retention or deletion promise.
    expect(screen.getByText("HeroOS doesn't make employment decisions.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/isn.t saved|not saved|deleted|retain|retention/i);
  });

  it("sends only its words, a new turn key, the conversation and the revision it last saw", async () => {
    const { fetcher } = setup(null, answer(), answer("Thanks, that helps.", {}, 2), answer("Noted.", {}, 3));
    await ask(WORDS);
    await screen.findByText(REPLY);
    await ask("Yes, I explained it to him last week.");
    await screen.findByText("Thanks, that helps.");
    const second = bodyOf(fetcher, 1);
    expect(second).toEqual({
      message: "Yes, I explained it to him last week.",
      turnKey: second.turnKey,
      conversationId: CONVERSATION_ID,
      expectedRevision: 1,
    });
    expect(second.turnKey).not.toBe(bodyOf(fetcher, 0).turnKey);
    await ask("He was late again today.");
    await screen.findByText("Noted.");
    expect(bodyOf(fetcher, 2).expectedRevision).toBe(2);
  });

  it("shows the founder's message once while HeroOS answers: in the conversation, not in the box", async () => {
    let release: (response: Response) => void = () => undefined;
    const slow = new Promise<Response>((resolve) => {
      release = resolve;
    });
    setup(null, slow);
    await ask(WORDS);
    expect(await screen.findByRole("status", { name: "HeroOS is answering" })).toBeInTheDocument();
    // Exactly once on the page: the founder's turn. The box is empty and waits.
    expect(screen.getAllByText(WORDS)).toHaveLength(1);
    expect(screen.getByRole("group", { name: "You" })).toHaveTextContent(WORDS);
    expect(box()).toHaveValue("");
    expect(box()).toHaveAttribute("readonly");
    expect(box()).toHaveAttribute("placeholder", "HeroOS is answering…");
    expect(send()).toBeDisabled();
    await act(async () => release(answer()));
    expect(await screen.findByText(REPLY)).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "HeroOS is answering" })).toBeNull();
    // Ready for the next message, and still shown once.
    expect(screen.getAllByText(WORDS)).toHaveLength(1);
    expect(box()).toHaveValue("");
    expect(box()).not.toHaveAttribute("readonly");
    expect(box()).toHaveAttribute("placeholder", "Reply in your own words.");
    await waitFor(() => expect(box()).toHaveFocus());
  });

  it("puts a later message back in the box, and only there, when it fails", async () => {
    let release: (response: Response) => void = () => undefined;
    const slow = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const SECOND = "[SYNTHETIC] Yes, I explained it to him last week.";
    const { fetcher } = setup(null, answer(), slow, answer("Thanks, that helps.", {}, 2, SECOND));
    await ask(WORDS);
    await screen.findByText(REPLY);
    await ask(SECOND);
    expect(screen.getAllByText(SECOND)).toHaveLength(1);
    expect(box()).toHaveValue("");
    await act(async () => release(reply(503, { error: "unavailable" })));
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn.t answer just now/);
    // Not in the conversation (it wasn't answered), back in the box to send again.
    expect(screen.queryByRole("group", { name: "You", description: SECOND })).toBeNull();
    expect(screen.getAllByRole("group", { name: "You" })).toHaveLength(1);
    expect(box()).toHaveValue(SECOND);
    expect(box()).not.toHaveAttribute("readonly");
    fireEvent.click(send());
    expect(await screen.findByText("Thanks, that helps.")).toBeInTheDocument();
    expect(bodyOf(fetcher, 2).message).toBe(SECOND);
    // The same words again: the same turn key, so a lost answer is never asked twice.
    expect(bodyOf(fetcher, 2).turnKey).toBe(bodyOf(fetcher, 1).turnKey);
    expect(screen.getAllByText(SECOND)).toHaveLength(1);
  });

  it.each([
    [reply(503, { error: "unavailable" }), /couldn.t answer just now/],
    [reply(503, { error: "knowledge_unavailable" }), /approved guidance isn.t available/],
    [reply(503, { error: "not_configured" }), /approved guidance isn.t available/],
    [reply(429, { error: "rate_limited" }), /a lot of questions/],
    [reply(504, { error: "timeout" }), /took too long/],
    [reply(422, { error: "invalid", fields: [] }), /couldn.t accept this text/],
    [reply(409, { error: "conflict" }), /couldn.t send this message/],
    [reply(403, { error: "refused" }), /Only company administrators/],
    [reply(200, { reply: "x", conversationState: "block" }), /couldn.t answer just now/],
    [new Error("offline"), /couldn.t answer just now/],
  ])("keeps the typed message after a recoverable failure (%#)", async (failure, copy) => {
    const { fetcher } = setup(null, failure, answer());
    await ask(WORDS);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy);
    expect(box()).toHaveValue(WORDS);
    expect(screen.getAllByText(WORDS)).toHaveLength(1);
    await waitFor(() => expect(box()).toHaveFocus());
    expect(send()).toBeEnabled();
    // Sending again works, with the same words and the same turn key.
    fireEvent.click(send());
    expect(await screen.findByText(REPLY)).toBeInTheDocument();
    expect(bodyOf(fetcher, 1).message).toBe(WORDS);
    expect(bodyOf(fetcher, 1).turnKey).toBe(bodyOf(fetcher, 0).turnKey);
  });

  it("offers sign-in again when the session has ended", async () => {
    setup(null, reply(401, { error: "session_expired" }));
    await ask(WORDS);
    expect(await screen.findByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/auth/login");
  });

  it("shows a safe next step in the same neutral style, and never an outcome", async () => {
    setup(null, answer(REPLY, { safeNextStep: "Write down the dates of each late arrival." }));
    await ask(WORDS);
    expect(await screen.findByText("Safe next step")).toBeInTheDocument();
    expect(screen.getByText("Write down the dates of each late arrival.")).toBeInTheDocument();
    const heroos = screen.getByRole("group", { name: "HeroOS" });
    expect(heroos.textContent).not.toMatch(/Guidance|Warning|Stop|Expert Review|Block/);
    expect(document.querySelector("[class*='tone-']")).toBeNull();
  });

  it("shows the deployment's notice and starts a new conversation on request", async () => {
    const { fetcher } = setup("Preview: use fictional scenarios only.", answer(), answer("Hello again."));
    expect(screen.getByText("Preview: use fictional scenarios only.")).toBeInTheDocument();
    await ask(WORDS);
    await screen.findByText(REPLY);
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    await waitFor(() => expect(screen.queryByText(REPLY)).toBeNull());
    expect(screen.getByRole("heading", { level: 1, name: "What can HR do for you today?" })).toBeInTheDocument();
    // Only this page starts over (nothing is deleted): the next message opens a new one.
    await ask("Another matter.");
    await screen.findByText("Hello again.");
    expect(bodyOf(fetcher, 1)).toMatchObject({ conversationId: null, expectedRevision: 0 });
  });

  it("scrolls to below the docked box, so the newest turn is never left under it", async () => {
    const scrolled: Element[] = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
    try {
      setup(null, answer(REPLY, { safeNextStep: "Write down the dates." }));
      await ask(WORDS);
      await screen.findByText("Write down the dates.");
      const target = scrolled.at(-1);
      expect(target).toBeDefined();
      // After the box and the not-saved note, not inside the conversation list.
      expect(box().compareDocumentPosition(target!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(screen.getByRole("list", { name: "Conversation with HeroOS" }).contains(target!)).toBe(false);
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it("sends with Ctrl+Enter and adds a line with Enter", async () => {
    const { fetcher } = setup(null, answer());
    fireEvent.change(box(), { target: { value: WORDS } });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(fetcher).not.toHaveBeenCalled();
    fireEvent.keyDown(box(), { key: "Enter", ctrlKey: true });
    expect(await screen.findByText(REPLY)).toBeInTheDocument();
  });
});

describe("AskConversation outcomes (M2-NEW-06: decided by the API, never by a model)", () => {
  const outcome = (kind: string, title: string, message: string, items: unknown[] = []) => ({ kind, title, message, items });

  it("shows a Block on the step, with words and its sign, and keeps the conversation going", async () => {
    const card = outcome("block", "Not yet: Written warning", "Don't take this step yet: a written warning can't safely proceed yet.", [
      { kind: "block", text: "Written warning: can't safely proceed yet" },
      { kind: "guidance", text: "Workplace reminder: no HeroOS rule prevents it on what's established so far" },
    ]);
    const { fetcher } = setup(null, answer(REPLY, { outcome: card }), answer("Thanks."));
    await ask(WORDS);
    const turn = await screen.findByRole("article", { name: /HeroOS, Stop/ });
    expect(within(turn).getByText("Not yet: Written warning")).toBeInTheDocument();
    expect(within(turn).getByText(card.message)).toBeInTheDocument();
    expect(within(turn).getByRole("list", { name: "Each step you asked about" })).toBeInTheDocument();
    expect(within(turn).getByText("Guidance")).toBeInTheDocument();
    expect(turn).toHaveClass("tone-stop");
    expect(document.body.textContent).not.toMatch(/HeroOS can.t proceed/);
    // A Block holds one step, never the conversation: the box is free.
    expect(box()).not.toHaveAttribute("readonly");
    expect(box()).not.toBeDisabled();
    await ask("He was told about the standard in writing.");
    expect(await screen.findByText("Thanks.")).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["expert_review", "Expert Review", "tone-expert", "Specialist review is required before dismissal without notice."],
    ["warning", "Warning", "tone-warning", "A caution applies to unpaid suspension."],
    ["guidance", "Guidance", "tone-guidance", "HeroOS's approved guidance applies here."],
  ])("labels %s in words, never colour alone", async (kind, label, tone, message) => {
    setup(null, answer(REPLY, { outcome: outcome(kind, label, message) }));
    await ask(WORDS);
    const turn = await screen.findByRole("article", { name: new RegExp(`HeroOS, ${label}`) });
    expect(turn).toHaveClass(tone);
    expect(within(turn).getByText(label)).toBeInTheDocument();
    if (kind !== "guidance") expect(within(turn).getByText(message)).toBeInTheDocument();
    expect(turn.textContent).not.toMatch(/ticket|submitted|assigned|will respond/i);
    expect(box()).not.toBeDisabled();
  });

  it("says when the checks are unavailable, never as an HR outcome", async () => {
    const card = outcome("unavailable", "Checks unavailable", "HeroOS's deterministic checks aren't available right now.");
    setup(null, answer(REPLY, { outcome: card }));
    await ask(WORDS);
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("Checks unavailable.");
    expect(screen.queryByRole("article")).toBeNull();
    expect(document.body.textContent).not.toMatch(/Expert Review|Warning/);
  });

  it("refuses a reply whose outcome isn't the API's exact card", async () => {
    setup(null, answer(REPLY, { outcome: { ...outcome("block", "Not yet", "x"), rule: "fictional_cap" } }));
    await ask(WORDS);
    expect(await screen.findByRole("alert")).toHaveTextContent("HeroOS couldn't answer just now");
    expect(box()).toHaveValue(WORDS);
  });
});

describe("AskWorkspace without the gateway", () => {
  it("keeps opening a case through the Ask seam", async () => {
    const navigate = vi.fn();
    const fetcher = vi.fn(async () => reply(200, { caseId: "11111111-1111-4111-8111-111111111111", narrativeSaved: true }));
    render(
      <AskWorkspace
        companyId={COMPANY_ID}
        conversation={{ available: false, reason: "disabled", notice: null }}
        fetcher={fetcher as unknown as typeof fetch}
        mode="ready"
        navigate={navigate}
        returning
      />,
    );
    await ask(WORDS);
    await waitFor(() => expect(navigate).toHaveBeenCalled());
    expect((fetcher.mock.calls[0] as unknown as [string])[0]).toBe(`/bff/companies/${COMPANY_ID}/ask`);
  });
});
