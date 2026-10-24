import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { COMPANY_ID } from "@/test/fixtures";

import { AskWorkspace } from "./ask-workspace";

/**
 * M2-NEW-07: stored Ask HeroOS conversations in the browser: reopening one
 * (address, History, its Case), earlier messages a page at a time, another
 * administrator's words, the status's separate dimensions, a conversation that
 * moved on elsewhere, and a new conversation that stores nothing.
 */

const ID = "9b1f3c3e-6a52-4b8f-9d0a-2c1e5f6a7b8c";
const OTHER = "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f";
const CASE_ID = "7e8f9a0b-1c2d-4e3f-8a5b-6c7d8e9f0a1b";
const AT = "2026-10-22T10:00:00Z";
const LATER = "2026-10-22T10:05:00Z";

type Status = Record<string, unknown>;
const status = (overrides: Status = {}, attention: Status = {}): Status => ({
  lifecycle: "in_progress",
  workflow: { key: "disciplinary", title: "Disciplinary" },
  attention: {
    needsInformation: false,
    jurisdiction: null,
    expertReview: { active: false, scope: null, actions: [], serviceAvailable: false },
    ...attention,
  },
  checks: "ready",
  latestOutcome: "guidance",
  ...overrides,
});

const conversation = (revision: number, extra: Status = {}) => ({
  id: ID,
  title: "Disciplinary case · 22 Oct",
  case: { id: CASE_ID, title: "Disciplinary case · 22 Oct" },
  createdAt: AT,
  updatedAt: AT,
  revision,
  status: status(),
  ...extra,
});

const founder = (sequence: number, text: string, author = "you") => ({
  sequence, author, text, safeNextStep: null, conversationState: null, outcome: null, createdAt: AT,
}); // prettier-ignore
const heroos = (sequence: number, text: string, outcome: unknown = null) => ({
  sequence, author: "heroos", text, safeNextStep: null, conversationState: "responded", outcome, createdAt: AT,
}); // prettier-ignore

const json = (code: number, body: unknown) => new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });

function setup(
  responses: (Response | Error)[],
  { conversationId = null, available = true }: { conversationId?: string | null; available?: boolean } = {},
) {
  const queue = [...responses];
  const fetcher = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(async () => {
    const next = queue.shift() ?? new Error("no response queued");
    if (next instanceof Error) throw next;
    return next;
  });
  // The inline Case steps read the Case's view (M2-NEW-08; case-steps.test.tsx): apart from these calls.
  const routed = (input: string, init?: RequestInit) =>
    input.endsWith("/workflow") ? Promise.resolve(json(404, { error: "not_found" })) : fetcher(input, init);
  render(
    <AskWorkspace
      companyId={COMPANY_ID}
      conversation={available ? { available: true, reason: null, notice: null } : null}
      conversationId={conversationId}
      fetcher={routed as unknown as typeof fetch}
      mode="ready"
      returning
    />,
  );
  return fetcher;
}

const urls = (fetcher: ReturnType<typeof setup>) => fetcher.mock.calls.map(([url]) => url);
const box = () => screen.getByRole("textbox", { name: "Explain the situation in your own words" });
const BASE = `/bff/companies/${COMPANY_ID}/assistant`;

afterEach(() => window.history.replaceState(null, "", "/"));

describe("a stored Ask HeroOS conversation", () => {
  it("reopens from the address with its latest messages, and earlier ones on request", async () => {
    window.history.replaceState(null, "", `/workspaces/${COMPANY_ID}?conversation=${ID}`);
    const fetcher = setup(
      [
        json(200, {
          conversation: conversation(3),
          messages: [founder(5, "[SYNTHETIC] He was late again today."), heroos(6, "[SYNTHETIC] Thanks. Keep a note of the date.")],
          nextBefore: 5,
        }),
        json(200, { messages: [founder(1, "[SYNTHETIC] One employee is late."), heroos(2, "[SYNTHETIC] How often?")], nextBefore: 3 }),
      ],
      { conversationId: ID },
    );
    expect(await screen.findByText("[SYNTHETIC] Thanks. Keep a note of the date.")).toBeInTheDocument();
    expect(urls(fetcher)[0]).toBe(`${BASE}/conversations/${ID}`);
    // Never the whole lifetime at once: older messages are a page at a time.
    expect(screen.queryByText("[SYNTHETIC] One employee is late.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Load earlier messages" }));
    expect(await screen.findByText("[SYNTHETIC] One employee is late.")).toBeInTheDocument();
    expect(urls(fetcher)[1]).toBe(`${BASE}/conversations/${ID}/messages?before=5`);
    // Oldest first, and the button stays while there are earlier messages.
    const list = screen.getByRole("list", { name: "Conversation with HeroOS" });
    expect(within(list).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      expect.stringContaining("One employee is late."),
      expect.stringContaining("How often?"),
      expect.stringContaining("He was late again today."),
      expect.stringContaining("Keep a note of the date."),
    ]);
    expect(screen.getByRole("button", { name: "Load earlier messages" })).toBeInTheDocument();
  });

  it("continues the reopened conversation at its revision, with nothing but the words", async () => {
    const fetcher = setup(
      [
        json(200, { conversation: conversation(3), messages: [founder(5, "[SYNTHETIC] Earlier."), heroos(6, "[SYNTHETIC] Noted.")], nextBefore: null }),
        json(200, {
          conversation: conversation(4),
          messages: [founder(7, "[SYNTHETIC] He apologised."), heroos(8, "[SYNTHETIC] Thanks for telling me.")],
          replayed: false,
        }),
      ],
      { conversationId: ID },
    );
    await screen.findByText("[SYNTHETIC] Noted.");
    fireEvent.change(box(), { target: { value: "[SYNTHETIC] He apologised." } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("[SYNTHETIC] Thanks for telling me.")).toBeInTheDocument();
    const body = JSON.parse(String((fetcher.mock.calls[1] as [string, RequestInit])[1].body)) as Record<string, unknown>;
    expect(body).toEqual({ message: "[SYNTHETIC] He apologised.", turnKey: body.turnKey, conversationId: ID, expectedRevision: 3 });
  });

  it("names another administrator's words, never as the viewer's own", async () => {
    setup(
      [
        json(200, {
          conversation: conversation(2),
          messages: [
            founder(1, "[SYNTHETIC] Written by a colleague.", "another_administrator"),
            heroos(2, "[SYNTHETIC] Reply one."),
            founder(3, "[SYNTHETIC] Written by me."),
            heroos(4, "[SYNTHETIC] Reply two."),
          ],
          nextBefore: null,
        }),
      ],
      { conversationId: ID },
    );
    await screen.findByText("[SYNTHETIC] Reply two.");
    expect(screen.getByRole("group", { name: "Another administrator" })).toHaveTextContent("Written by a colleague.");
    expect(screen.getByRole("group", { name: "You" })).toHaveTextContent("Written by me.");
    expect(document.body.textContent).not.toMatch(/@|auth0|cognito/i);
  });

  it("shows the Case and each status dimension apart: never one badge for all", async () => {
    setup(
      [
        json(200, {
          conversation: conversation(2, {
            status: status(
              { checks: "unavailable", latestOutcome: "expert_review" },
              {
                needsInformation: true,
                jurisdiction: "needs_confirmation",
                expertReview: { active: true, scope: "action", actions: ["Dismissal without notice"], serviceAvailable: false },
              },
            ),
          }),
          messages: [founder(3, "[SYNTHETIC] Can I dismiss him?"), heroos(4, "[SYNTHETIC] Not yet.")],
          nextBefore: null,
        }),
      ],
      { conversationId: ID },
    );
    // Chat-first Case: the light Case header over its chat.
    const about = await screen.findByRole("banner", { name: "This case" });
    expect(within(about).getByRole("heading", { level: 1 })).toHaveTextContent("Disciplinary case · 22 Oct");
    // The lifecycle is the Case's own: an action's Expert Review never pauses it.
    expect(within(about).getByText("In progress")).toBeInTheDocument();
    expect(within(about).getByRole("link", { name: "Case details" })).toHaveAttribute("href", `/workspaces/${COMPANY_ID}/cases/${CASE_ID}`);
    // Only what needs attention, each dimension apart (what HeroOS still needs, it asks in the chat).
    const attention = within(about).getByRole("list", { name: "Needs attention" });
    expect(within(attention).getByText("Expert review required before dismissal without notice")).toBeInTheDocument();
    expect(within(attention).getByText("Jurisdiction to confirm")).toBeInTheDocument();
    // Checks that can't run are a technical note, never the Case's status.
    expect(within(about).getByRole("note")).toHaveTextContent("checks are temporarily unavailable");
    expect(about.textContent).not.toMatch(/Paused|Checks unavailable ·/);
    // Expert Review is a requirement, never a ticket.
    expect(document.body.textContent).not.toMatch(/submitted|notified|ticket|awaiting|we.ll reply|sent to/i);
  });

  it("lists recent conversations in History by safe titles only, a page at a time, and reopens one", async () => {
    const list = (items: unknown[], nextBefore: string | null) => json(200, { items, nextBefore });
    const item = (id: string, withCase: boolean, title: string | null) => ({
      id,
      title,
      case: withCase ? { id: CASE_ID, title: "Disciplinary case · 22 Oct" } : null,
      createdAt: AT,
      updatedAt: LATER,
    });
    const cursor = `1729591200000000.${"a".repeat(32)}`;
    const fetcher = setup([
      list([item(ID, true, "Disciplinary case · 22 Oct")], cursor),
      list([item(OTHER, false, null)], null),
      json(200, {
        conversation: { ...conversation(1), id: OTHER, title: null, case: null, status: status({ lifecycle: null, workflow: null, checks: "not_applicable", latestOutcome: "none" }) },
        messages: [founder(1, "[SYNTHETIC] Help me debug JavaScript."), heroos(2, "[SYNTHETIC] That's outside what HeroOS helps with.")],
        nextBefore: null,
      }),
    ]);
    // The landing stays the question; History is a quiet control below it.
    expect(screen.getByRole("heading", { level: 1, name: "What can HR do for you today?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "History" }));
    const drawer = await screen.findByRole("dialog", { name: "History" });
    expect(await within(drawer).findByText("Disciplinary case · 22 Oct")).toBeInTheDocument();
    expect(urls(fetcher)[0]).toBe(`${BASE}/conversations`);
    fireEvent.click(within(drawer).getByRole("button", { name: "Show older cases" }));
    expect(await within(drawer).findByText("Conversation")).toBeInTheDocument();
    expect(urls(fetcher)[1]).toBe(`${BASE}/conversations?before=${encodeURIComponent(cursor)}`);
    expect(within(drawer).queryByRole("button", { name: "Show older cases" })).toBeNull();
    // Titles and times, never a message preview.
    expect(drawer.textContent).not.toMatch(/SYNTHETIC|debug|JavaScript/);
    fireEvent.click(within(drawer).getByRole("button", { name: /^Conversation/ }));
    expect(await screen.findByText("[SYNTHETIC] That's outside what HeroOS helps with.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(window.location.search).toBe(`?conversation=${OTHER}`);
    // No Case record yet and nothing to attend to: a bare header, no attention list or details.
    const header = screen.getByRole("banner", { name: "This case" });
    expect(within(header).getByRole("heading", { level: 1 })).toHaveTextContent("New case");
    expect(within(header).queryByRole("list", { name: "Needs attention" })).toBeNull();
    expect(within(header).queryByRole("link", { name: "Case details" })).toBeNull();
  });

  it("shows the latest when the conversation moved on elsewhere, keeping the unsent words", async () => {
    const fetcher = setup(
      [
        json(200, { conversation: conversation(1), messages: [founder(1, "[SYNTHETIC] First."), heroos(2, "[SYNTHETIC] Reply.")], nextBefore: null }),
        json(409, { error: "conflict" }),
        json(200, {
          conversation: conversation(2),
          messages: [
            founder(1, "[SYNTHETIC] First."),
            heroos(2, "[SYNTHETIC] Reply."),
            founder(3, "[SYNTHETIC] From the other tab.", "another_administrator"),
            heroos(4, "[SYNTHETIC] Answer to the other tab."),
          ],
          nextBefore: null,
        }),
        json(200, { conversation: conversation(3), messages: [founder(5, "[SYNTHETIC] My words."), heroos(6, "[SYNTHETIC] Thanks.")], replayed: false }),
      ],
      { conversationId: ID },
    );
    await screen.findByText("[SYNTHETIC] Reply.");
    fireEvent.change(box(), { target: { value: "[SYNTHETIC] My words." } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("[SYNTHETIC] Answer to the other tab.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("updated in another tab or by another administrator");
    expect(screen.getByRole("status").textContent).not.toMatch(/optimistic|concurrency|revision|409/i);
    expect(box()).toHaveValue("[SYNTHETIC] My words.");
    // Never overwritten, never sent twice by itself: the founder sends again, at the latest revision.
    expect(fetcher).toHaveBeenCalledTimes(3);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("[SYNTHETIC] Thanks.")).toBeInTheDocument();
    const body = JSON.parse(String((fetcher.mock.calls[3] as [string, RequestInit])[1].body)) as Record<string, unknown>;
    expect(body.expectedRevision).toBe(2);
  });

  it("starts a new chat without storing anything or leaving the old one", async () => {
    window.history.replaceState(null, "", `/workspaces/${COMPANY_ID}?conversation=${ID}`);
    const fetcher = setup(
      [json(200, { conversation: conversation(1), messages: [founder(1, "[SYNTHETIC] Old."), heroos(2, "[SYNTHETIC] Old reply.")], nextBefore: null })],
      { conversationId: ID },
    );
    await screen.findByText("[SYNTHETIC] Old reply.");
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(await screen.findByRole("heading", { level: 1, name: "What can HR do for you today?" })).toBeInTheDocument();
    expect(window.location.search).toBe("");
    // Only the read: nothing created, nothing deleted.
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("says when a conversation can't be found, and drops it from the address", async () => {
    window.history.replaceState(null, "", `/workspaces/${COMPANY_ID}?conversation=${ID}`);
    setup([json(404, { error: "not_found" })], { conversationId: ID });
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't find that conversation");
    expect(window.location.search).toBe("");
    expect(box()).toBeEnabled();
  });

  it("can still be read while HeroOS can't answer", async () => {
    setup([json(200, { conversation: conversation(1), messages: [founder(1, "[SYNTHETIC] Q."), heroos(2, "[SYNTHETIC] A.")], nextBefore: null })], {
      conversationId: ID,
      available: false,
    });
    expect(await screen.findByText("[SYNTHETIC] A.")).toBeInTheDocument();
    expect(box()).toBeDisabled();
    expect(box()).toHaveAttribute("placeholder", "HeroOS can't answer right now.");
  });

  it("keeps a failed first message out of the conversation, back in the box", async () => {
    const fetcher = setup([json(503, { error: "unavailable" })]);
    fireEvent.change(box(), { target: { value: "[SYNTHETIC] Unanswered." } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Send" })));
    await waitFor(() => expect(box()).toHaveValue("[SYNTHETIC] Unanswered."));
    expect(screen.queryByRole("group", { name: "You" })).toBeNull();
    expect(window.location.search).toBe("");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
