import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { COMPANY_ID } from "@/test/fixtures";

import { AskWorkspace } from "./ask-workspace";

const CONTINUATION = "eyJ2IjoxLCJ0IjpbM10sIngiOjE3OTI2MjEzNTl9.xNc7X0hBpSOKTehKXpgdlw";
const NEXT = "eyJ2IjoxLCJ0IjpbXSwieCI6MTc5MjYyMTM1OX0.AAAAAAAAAAAAAAAAAAAAAA";
const WORDS = "[SYNTHETIC] My employee has been late three times this month. What should I do?";
const REPLY = "Thanks for explaining. Has the expected standard been explained to him?";
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const answer = (text = REPLY, extra: Record<string, unknown> = {}) =>
  reply(200, { reply: text, safeNextStep: null, conversationState: "responded", continuation: CONTINUATION, ...extra });

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

  it("asks HeroOS without opening a case, then shows the reply and keeps the box free", async () => {
    const { fetcher, navigate } = setup(null, answer());
    await ask(`  ${WORDS}\n`);
    expect(await screen.findByText(REPLY)).toBeInTheDocument();
    expect(screen.getByText(WORDS)).toBeInTheDocument();
    const [url, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/assistant/messages`);
    expect(url).not.toContain("/ask");
    expect(init.method).toBe("POST");
    expect(bodyOf(fetcher)).toEqual({ message: WORDS, history: [], continuation: null });
    expect(navigate).not.toHaveBeenCalled();
    // Free text stays the way to answer.
    expect(box()).toHaveValue("");
    expect(box()).not.toHaveAttribute("readonly");
    expect(screen.getByText(/This conversation isn.t saved/)).toBeInTheDocument();
  });

  it("sends the recent conversation and the last continuation with the next message", async () => {
    const { fetcher } = setup(null, answer(), answer("Thanks, that helps.", { continuation: NEXT }));
    await ask(WORDS);
    await screen.findByText(REPLY);
    await ask("Yes, I explained it to him last week.");
    await screen.findByText("Thanks, that helps.");
    expect(bodyOf(fetcher, 1)).toEqual({
      message: "Yes, I explained it to him last week.",
      history: [
        { role: "user", content: WORDS },
        { role: "assistant", content: REPLY },
      ],
      continuation: CONTINUATION,
    });
  });

  it("shows HeroOS answering while it waits, with the words held in the box", async () => {
    let release: (response: Response) => void = () => undefined;
    const slow = new Promise<Response>((resolve) => {
      release = resolve;
    });
    setup(null, slow);
    await ask(WORDS);
    expect(await screen.findByRole("status", { name: "HeroOS is answering" })).toBeInTheDocument();
    expect(send()).toBeDisabled();
    expect(box()).toHaveAttribute("readonly");
    await act(async () => release(answer()));
    expect(await screen.findByText(REPLY)).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "HeroOS is answering" })).toBeNull();
  });

  it.each([
    [reply(503, { error: "unavailable" }), /couldn.t answer just now/],
    [reply(503, { error: "knowledge_unavailable" }), /approved guidance isn.t available/],
    [reply(503, { error: "not_configured" }), /approved guidance isn.t available/],
    [reply(429, { error: "rate_limited" }), /a lot of questions/],
    [reply(504, { error: "timeout" }), /took too long/],
    [reply(422, { error: "invalid", fields: [] }), /couldn.t accept this text/],
    [reply(403, { error: "refused" }), /Only company administrators/],
    [reply(200, { reply: "x", conversationState: "block" }), /couldn.t answer just now/],
    [new Error("offline"), /couldn.t answer just now/],
  ])("keeps the typed message after a recoverable failure (%#)", async (failure, copy) => {
    const { fetcher } = setup(null, failure, answer());
    await ask(WORDS);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy);
    expect(box()).toHaveValue(WORDS);
    expect(send()).toBeEnabled();
    // Sending again works, with the same words.
    fireEvent.click(send());
    expect(await screen.findByText(REPLY)).toBeInTheDocument();
    expect(bodyOf(fetcher, 1).message).toBe(WORDS);
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

  it("shows the deployment's notice and starts over on request", async () => {
    setup("Preview: use fictional scenarios only.", answer());
    expect(screen.getByText("Preview: use fictional scenarios only.")).toBeInTheDocument();
    await ask(WORDS);
    await screen.findByText(REPLY);
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    await waitFor(() => expect(screen.queryByText(REPLY)).toBeNull());
    expect(screen.getByRole("heading", { level: 1, name: "What can HR do for you today?" })).toBeInTheDocument();
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
