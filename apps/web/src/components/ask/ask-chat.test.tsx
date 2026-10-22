import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GatewayStatus } from "@/lib/ask/conversation";
import { GREETING_REPLY } from "@/lib/ask/model";
import { COMPANY_ID } from "@/test/fixtures";

import { AskWorkspace } from "./ask-workspace";

/** Ask HeroOS while the API's staging chat-only demo is on: one plain conversation, never a case. */

const NOTICE = "Demo — use fictional employee scenarios only.";
const CHAT_ONLY: GatewayStatus = { available: true, reason: null, notice: NOTICE, chatOnly: true };
const SITUATION = "[SYNTHETIC] One of my employees hasn't shown up for work for three days and isn't responding.";
const QUESTION = "I'm sorry you're dealing with that. Has the employee contacted you or anyone else at the company?";

const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function setup(status: GatewayStatus = CHAT_ONLY, responses: (Response | Error)[] = [], conversationId: string | null = null) {
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
      conversation={status}
      conversationId={conversationId}
      fetcher={fetcher as unknown as typeof fetch}
      mode="ready"
      navigate={navigate}
      returning={false}
    />,
  );
  return { fetcher, navigate };
}

const box = () => screen.getByRole("textbox", { name: "Explain the situation in your own words" });
const ask = (text: string) => {
  fireEvent.change(box(), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
};
const callOf = (fetcher: ReturnType<typeof setup>["fetcher"], index: number) => {
  const [url, init] = fetcher.mock.calls[index] as [string, RequestInit];
  return { url, body: JSON.parse(String(init.body)) as unknown };
};

describe("AskWorkspace with the chat-only demo", () => {
  it("sends a greeting to the model and shows its answer: no case, no workflow, no status card", async () => {
    const { fetcher, navigate } = setup(CHAT_ONLY, [reply(200, { reply: "Hi! What can I help you with today?" })]);
    // The landing and the visible demo notice.
    expect(screen.getByRole("heading", { level: 1, name: "What can HR do for you today?" })).toBeInTheDocument();
    expect(screen.getByText(NOTICE)).toBeInTheDocument();

    ask("Hi Hannah");
    expect(await screen.findByText("Hi! What can I help you with today?")).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(callOf(fetcher, 0)).toEqual({
      url: `/bff/companies/${COMPANY_ID}/assistant/chat`,
      body: { message: "Hi Hannah", history: [] },
    });
    expect(navigate).not.toHaveBeenCalled();
    // The model answered, not the page's fixed greeting; nothing about a case or its workflow.
    expect(screen.queryByText(GREETING_REPLY)).toBeNull();
    expect(document.body.textContent).not.toMatch(/Loading case|Open case|Case status|History|pathway|Guidance|Warning|Expert Review/i);
    expect(screen.getByText(NOTICE)).toBeInTheDocument();
  });

  it("continues the conversation: the follow-up carries the earlier turns, and nothing opens a case", async () => {
    const { fetcher, navigate } = setup(CHAT_ONLY, [reply(200, { reply: QUESTION }), reply(200, { reply: "Thanks. When did you last try to reach him?" })]);
    ask(SITUATION);
    expect(await screen.findByText(QUESTION)).toBeInTheDocument();
    ask("No, nobody has heard from him.");
    expect(await screen.findByText("Thanks. When did you last try to reach him?")).toBeInTheDocument();

    expect(callOf(fetcher, 1).body).toEqual({
      message: "No, nobody has heard from him.",
      history: [
        { role: "user", content: SITUATION },
        { role: "assistant", content: QUESTION },
      ],
    });
    // Only the chat route: never the case-opening seam or the stored-conversation turn.
    for (const [url] of fetcher.mock.calls) expect(url).toBe(`/bff/companies/${COMPANY_ID}/assistant/chat`);
    expect(navigate).not.toHaveBeenCalled();
    const conversation = screen.getByRole("list", { name: "Conversation with HeroOS" });
    expect(within(conversation).getAllByRole("group", { name: "HeroOS" })).toHaveLength(2);
  });

  it("puts the words back in the box when HeroOS can't answer", async () => {
    setup(CHAT_ONLY, [reply(429, { error: "rate_limited" })]);
    ask(SITUATION);
    expect(await screen.findByRole("alert")).toHaveTextContent("HeroOS has had a lot of questions just now");
    await waitFor(() => expect(box()).toHaveValue(SITUATION));
  });

  it("says HeroOS can't answer rather than opening a case when the demo has no model", () => {
    const { fetcher } = setup({ available: false, reason: "not_configured", notice: NOTICE, chatOnly: true });
    expect(box()).toBeDisabled();
    expect(box()).toHaveAttribute("placeholder", "HeroOS can't answer right now.");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("never loads a stored conversation from the address", () => {
    const { fetcher } = setup(CHAT_ONLY, [], "11111111-2222-4333-8444-555555555555");
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.queryByText("Opening the conversation…")).toBeNull();
    expect(box()).toBeEnabled();
  });
});
