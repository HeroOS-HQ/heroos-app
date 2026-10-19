import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { boundedHistory, MAX_HISTORY_CHARS, MAX_HISTORY_TURNS } from "@/lib/assistant/model";
import { COMPANY_ID } from "@/test/fixtures";
import { CASE_ID, OTHER_CASE_ID, view } from "@/test/workflow-fixtures";

import { CaseWorkspace } from "./case-workspace";
import { HannahChat, NOTICE } from "./hannah-chat";

const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const available = (reason: string | null = null) =>
  reply(200, {
    status: { available: reason === null, reason, notice: NOTICE },
  });
const hannah = (text: string) =>
  reply(200, {
    reply: {
      reply: text,
      provider: "groq",
      model: "openai/gpt-oss-120b",
      notice: NOTICE,
    },
  });
const base = `/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/assistant`;

type Call = [string, RequestInit | undefined];

function fetcherOf(...responses: (Response | Error | Promise<Response>)[]) {
  const queue = [...responses];
  return vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(async () => {
    const next = queue.shift() ?? new Error("no response queued");
    if (next instanceof Error) throw next;
    return next;
  });
}

const chat = (fetcher: ReturnType<typeof fetcherOf>) =>
  render(<HannahChat caseId={CASE_ID} companyId={COMPANY_ID} fetcher={fetcher as unknown as typeof fetch} />);
const box = () => screen.getByRole("textbox", { name: "Message Hannah" });
const type = (text: string) => fireEvent.change(box(), { target: { value: text } });
const log = () => within(screen.getByRole("log", { name: /Conversation with Hannah/ }));
const sent = (fetcher: ReturnType<typeof fetcherOf>, index: number) => {
  const [url, init] = fetcher.mock.calls[index] as Call;
  return {
    url,
    init: init!,
    body: JSON.parse(init!.body as string) as {
      message: string;
      history: unknown[];
    },
  };
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("HannahChat (Hannah AI demo)", () => {
  it("renders the demo notice and composer only when the API says this person can use it", async () => {
    const fetcher = fetcherOf(available());
    chat(fetcher);
    expect(
      await screen.findByRole("heading", {
        name: "Talk it through with Hannah",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(NOTICE)).toBeInTheDocument();
    expect(screen.getByText(/AI demo · not part of the case record/)).toBeInTheDocument();
    expect(box()).toBeInTheDocument();
    const [url, init] = fetcher.mock.calls[0] as Call;
    expect(url).toBe(base);
    expect(init?.method ?? "GET").toBe("GET");
  });

  it.each([
    ["the demo is off", available("disabled")],
    ["the person is a member", reply(403, { error: "refused" })],
    ["the API is older", reply(404, { error: "not_found" })],
    ["the status can't be read", new Error("offline")],
  ])("stays out of the page when %s", async (_, response) => {
    const fetcher = fetcherOf(response);
    const { container } = chat(fetcher);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    await act(async () => {});
    expect(container).toBeEmptyDOMElement();
  });

  it("says when the environment has no model provider, with no composer", async () => {
    chat(fetcherOf(available("not_configured")));
    expect(await screen.findByText("Hannah AI isn't set up in this environment")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Message Hannah" })).toBeNull();
  });

  it("hides itself for an unknown reason from a newer or older API", async () => {
    const fetcher = fetcherOf(available("not_a_tester"));
    const { container } = chat(fetcher);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    await act(async () => {});
    expect(container).toBeEmptyDOMElement();
  });

  it("explains a refusal (e.g. the role changed) without offering a retry", async () => {
    chat(fetcherOf(available(), reply(403, { error: "refused" })));
    await screen.findByRole("textbox", { name: "Message Hannah" });
    type("Hello");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Only company administrators can use Hannah");
    expect(within(alert).queryByRole("button")).toBeNull();
  });

  it("sends a message to the BFF, shows it pending, then Hannah's reply as an AI message", async () => {
    let answer!: (response: Response) => void;
    const fetcher = fetcherOf(available(), new Promise<Response>((resolve) => (answer = resolve)));
    chat(fetcher);
    await screen.findByRole("textbox", { name: "Message Hannah" });
    type("One of our employees has been coming late to work repeatedly.");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Hannah is thinking…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();
    expect(log().getByText("One of our employees has been coming late to work repeatedly.")).toBeInTheDocument();
    expect(box()).toHaveValue("");
    const { url, init, body } = sent(fetcher, 1);
    expect(url).toBe(`${base}/messages`);
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(body).toEqual({
      message: "One of our employees has been coming late to work repeatedly.",
      history: [],
    });

    await act(async () => answer(hannah("Okay, let's understand what's been happening. Have you spoken with them?")));
    const message = await screen.findByText(/Have you spoken with them\?/);
    expect(message.closest("li")).toHaveAttribute("data-role", "assistant");
    expect(within(message.closest("li")!).getByText("AI · exploratory, not saved")).toBeInTheDocument();
    expect(screen.queryByText("Hannah is thinking…")).toBeNull();
  });

  it("remembers the conversation: earlier turns go with the next message", async () => {
    const fetcher = fetcherOf(available(), hannah("Have there been earlier warnings?"), hannah("Thanks, that helps."));
    chat(fetcher);
    await screen.findByRole("textbox", { name: "Message Hannah" });
    type("Sam has been late six times this month.");
    fireEvent.keyDown(box(), { key: "Enter" });
    await screen.findByText("Have there been earlier warnings?");
    type("One verbal warning in May.");
    fireEvent.keyDown(box(), { key: "Enter" });
    await screen.findByText("Thanks, that helps.");
    expect(sent(fetcher, 2).body).toEqual({
      message: "One verbal warning in May.",
      history: [
        { role: "user", content: "Sam has been late six times this month." },
        { role: "assistant", content: "Have there been earlier warnings?" },
      ],
    });
  });

  it("Shift+Enter adds a line instead of sending; nothing is sent twice while waiting", async () => {
    const fetcher = fetcherOf(available(), new Promise<Response>(() => {}));
    chat(fetcher);
    await screen.findByRole("textbox", { name: "Message Hannah" });
    type("First line");
    fireEvent.keyDown(box(), { key: "Enter", shiftKey: true });
    expect(fetcher).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(box(), { key: "Enter" });
    await screen.findByText("Hannah is thinking…");
    type("Another message");
    fireEvent.keyDown(box(), { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Sending…" }));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it.each([
    [reply(429, { error: "rate_limited" }), "Hannah needs a short break"],
    [reply(504, { error: "timeout" }), "Hannah took too long to answer"],
    [reply(503, { error: "unavailable" }), "Hannah couldn't answer just now"],
    [new Error("network down"), "Hannah couldn't answer just now"],
  ])("recovers from a failure and retries the same message once", async (failure, title) => {
    const fetcher = fetcherOf(available(), failure, hannah("Let's take it step by step."));
    chat(fetcher);
    await screen.findByRole("textbox", { name: "Message Hannah" });
    type("An employee shouted at a colleague.");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(title);
    expect(screen.queryByText("Hannah is thinking…")).toBeNull();
    expect(screen.getByText("Not answered")).toBeInTheDocument();

    fireEvent.click(within(alert).getByRole("button", { name: "Retry message" }));
    await screen.findByText("Let's take it step by step.");
    expect(screen.queryByRole("alert")).toBeNull();
    // Shown once, sent again unchanged (not added to its own history).
    expect(log().getAllByText("An employee shouted at a colleague.")).toHaveLength(1);
    expect(sent(fetcher, 2).body).toEqual({
      message: "An employee shouted at a colleague.",
      history: [],
    });
  });

  it("explains a missing provider key without offering a retry", async () => {
    chat(fetcherOf(available(), reply(503, { error: "not_configured" })));
    await screen.findByRole("textbox", { name: "Message Hannah" });
    type("Hello");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Hannah AI isn't set up in this environment");
    expect(within(alert).queryByRole("button")).toBeNull();
  });

  it("starts over with an empty conversation", async () => {
    const fetcher = fetcherOf(available(), hannah("Tell me more."), hannah("Fresh start."));
    chat(fetcher);
    await screen.findByRole("textbox", { name: "Message Hannah" });
    type("First scenario");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Tell me more.");
    fireEvent.click(screen.getByRole("button", { name: "Start over" }));
    expect(screen.queryByText("First scenario")).toBeNull();
    type("Second scenario");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Fresh start.");
    expect(sent(fetcher, 2).body.history).toEqual([]);
  });
});

describe("boundedHistory", () => {
  it("keeps only the newest turns within the limits, starting with the employer", () => {
    const turns = Array.from({ length: 30 }, (_, i) => ({
      role: i % 2 === 0 ? ("user" as const) : ("assistant" as const),
      content: `turn ${i} ${"x".repeat(900)}`,
    }));
    const kept = boundedHistory(turns);
    expect(kept.length).toBeLessThanOrEqual(MAX_HISTORY_TURNS);
    expect(kept.reduce((sum, turn) => sum + turn.content.length, 0)).toBeLessThanOrEqual(MAX_HISTORY_CHARS);
    expect(kept[0].role).toBe("user");
    expect(kept.at(-1)?.content).toMatch(/^turn 29 /);
    expect(boundedHistory([{ role: "assistant", content: "x".repeat(9000) }])).toEqual([]);
  });
});

describe("CaseWorkspace with the Hannah AI demo", () => {
  it("adds the chat under the guided conversation and keeps the workflow controls", async () => {
    const assistantFetcher = fetcherOf(available());
    render(
      <CaseWorkspace
        assistantFetcher={assistantFetcher as unknown as typeof fetch}
        cases={[]}
        companyId={COMPANY_ID}
        fetcher={fetcherOf() as unknown as typeof fetch}
        initialView={view()}
      />,
    );
    expect(
      await screen.findByRole("heading", {
        name: "Talk it through with Hannah",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Conversation" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Question groups" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save answers/ })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Case details" })).toBeInTheDocument();
    expect(OTHER_CASE_ID).not.toBe(CASE_ID);
  });

  it("doesn't ask about Hannah for a member (view only)", () => {
    const assistantFetcher = fetcherOf(available());
    render(
      <CaseWorkspace
        assistantFetcher={assistantFetcher as unknown as typeof fetch}
        cases={[]}
        companyId={COMPANY_ID}
        initialView={view({ canEdit: false })}
      />,
    );
    expect(assistantFetcher).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Talk it through with Hannah" })).toBeNull();
  });
});
