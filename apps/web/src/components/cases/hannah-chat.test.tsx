import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type AssistantLoad, boundedHistory, MAX_HISTORY_CHARS, MAX_HISTORY_TURNS } from "@/lib/assistant/model";
import { COMPANY_ID } from "@/test/fixtures";
import { apiProgression, CASE_ID, OTHER_CASE_ID, view } from "@/test/workflow-fixtures";

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

const READY: AssistantLoad = { state: "ready", status: { available: true, reason: null, notice: NOTICE } };

function chat(fetcher: ReturnType<typeof fetcherOf>, load: AssistantLoad = READY) {
  const onLoad = vi.fn<(load: AssistantLoad) => void>();
  const onOpenWorkflow = vi.fn<() => void>();
  const utils = render(
    <HannahChat
      caseId={CASE_ID}
      companyId={COMPANY_ID}
      fetcher={fetcher as unknown as typeof fetch}
      load={load}
      onLoad={onLoad}
      onOpenWorkflow={onOpenWorkflow}
    />,
  );
  return { ...utils, onLoad, onOpenWorkflow };
}
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
  it("opens with the demo notice, Hannah's introduction and the composer, asking nothing yet", () => {
    const fetcher = fetcherOf();
    chat(fetcher);
    expect(screen.getByRole("heading", { name: "Conversation with Hannah (AI demo)" })).toBeInTheDocument();
    // Every point of the disclosure is on screen, not behind a click.
    const notice = screen.getByText(NOTICE).closest("p")!;
    expect(notice).toHaveTextContent("AI demo");
    for (const point of [
      "Fictional scenarios only",
      "Exploratory responses",
      "don't authorize disciplinary decisions",
      "Not saved to the official case",
      "can't change",
    ]) {
      expect(notice).toHaveTextContent(point);
    }
    expect(log().getByText("Hi, I'm Hannah.")).toBeInTheDocument();
    expect(log().getByText(/can't see this case's saved answers/)).toBeInTheDocument();
    // The welcome is the page's own text: nothing looks like an answer from Hannah yet.
    expect(log().queryAllByRole("listitem").filter((item) => item.dataset.role === "assistant")).toHaveLength(0);
    expect(within(screen.getByRole("log", { name: /Conversation with Hannah/ })).queryByText(/AI · exploratory/)).toBeNull();
    expect(screen.getByRole("log", { name: /Conversation with Hannah/ }).querySelector("time")).toBeNull();
    expect(box()).toHaveAttribute("maxlength", "2000");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Start over" })).toBeDisabled();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("renders nothing while the demo is hidden", () => {
    const { container } = chat(fetcherOf(), { state: "hidden" });
    expect(container).toBeEmptyDOMElement();
  });

  it("says when the environment has no model provider, with no composer and a way to the workflow", () => {
    const { onOpenWorkflow } = chat(fetcherOf(), {
      state: "ready",
      status: { available: false, reason: "not_configured", notice: NOTICE },
    });
    expect(screen.getByRole("heading", { name: "Hannah AI isn't set up in this environment" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Message Hannah" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open the guided case workflow" }));
    expect(onOpenWorkflow).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["Hannah is available", available(), { state: "ready", status: { available: true, reason: null, notice: NOTICE } }],
    ["the demo was switched off", available("disabled"), { state: "hidden" }],
    ["the person is no longer an administrator", reply(403, { error: "refused" }), { state: "hidden" }],
    ["the API is still failing", reply(503, { error: "unavailable" }), { state: "unreachable" }],
    ["the network is down", new Error("offline"), { state: "unreachable" }],
  ])("says plainly when the status couldn't be read and checks again: %s", async (_, response, expected) => {
    const fetcher = fetcherOf(response);
    const { onLoad } = chat(fetcher, { state: "unreachable" });
    expect(screen.getByRole("heading", { name: "Hannah AI isn't responding right now" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Message Hannah" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(onLoad).toHaveBeenCalledWith(expected));
    if (expected.state === "unreachable") {
      expect(await screen.findByText("Still not responding. Try again in a minute.")).toBeInTheDocument();
    }
    const [url, init] = fetcher.mock.calls[0] as Call;
    expect(url).toBe(base);
    expect(init?.method ?? "GET").toBe("GET");
  });

  it("explains a refusal (e.g. the role changed) without offering a retry", async () => {
    chat(fetcherOf(reply(403, { error: "refused" })));
    type("Hello");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Only company administrators can use Hannah");
    expect(within(alert).queryByRole("button")).toBeNull();
  });

  it("sends a message to the BFF, shows it pending, then Hannah's reply as an AI message", async () => {
    let answer!: (response: Response) => void;
    const fetcher = fetcherOf(new Promise<Response>((resolve) => (answer = resolve)));
    chat(fetcher);
    type("One of our employees has been coming late to work repeatedly.");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Hannah is thinking…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();
    expect(log().getByText("One of our employees has been coming late to work repeatedly.")).toBeInTheDocument();
    expect(box()).toHaveValue("");
    const { url, init, body } = sent(fetcher, 0);
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

  it("keeps a four-turn conversation in order under a one-line introduction, and starts fresh on Start over", async () => {
    const fetcher = fetcherOf(hannah("[SYNTHETIC] First reply."), hannah("[SYNTHETIC] Second reply."));
    chat(fetcher);
    type("[SYNTHETIC] First message");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("[SYNTHETIC] First reply.");
    type("[SYNTHETIC] Second message");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("[SYNTHETIC] Second reply.");

    const items = log().getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Hi, I'm Hannah.");
    expect(items[0]).not.toHaveAttribute("data-role");
    const order = ["[SYNTHETIC] First message", "[SYNTHETIC] First reply.", "[SYNTHETIC] Second message", "[SYNTHETIC] Second reply."].map(
      (text) => items.findIndex((item) => item.textContent?.includes(text)),
    );
    expect(order).toEqual([1, 2, 3, 4]);
    expect(items.filter((item) => item.dataset.role === "assistant")).toHaveLength(2);
    // Only the welcome's chips besides: the long welcome is gone once the conversation has started.
    expect(log().queryByText("You can include")).toBeNull();
    expect(screen.getByText(NOTICE)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Start over" }));
    expect(log().getByText("You can include")).toBeInTheDocument();
    expect(log().queryByText("[SYNTHETIC] First message")).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("remembers the conversation: earlier turns go with the next message", async () => {
    const fetcher = fetcherOf(hannah("Have there been earlier warnings?"), hannah("Thanks, that helps."));
    chat(fetcher);
    type("Sam has been late six times this month.");
    fireEvent.keyDown(box(), { key: "Enter" });
    await screen.findByText("Have there been earlier warnings?");
    type("One verbal warning in May.");
    fireEvent.keyDown(box(), { key: "Enter" });
    await screen.findByText("Thanks, that helps.");
    expect(sent(fetcher, 1).body).toEqual({
      message: "One verbal warning in May.",
      history: [
        { role: "user", content: "Sam has been late six times this month." },
        { role: "assistant", content: "Have there been earlier warnings?" },
      ],
    });
  });

  it("Shift+Enter adds a line instead of sending; nothing is sent twice while waiting", async () => {
    const fetcher = fetcherOf(new Promise<Response>(() => {}));
    chat(fetcher);
    type("First line");
    fireEvent.keyDown(box(), { key: "Enter", shiftKey: true });
    expect(fetcher).toHaveBeenCalledTimes(0);
    fireEvent.keyDown(box(), { key: "Enter" });
    await screen.findByText("Hannah is thinking…");
    type("Another message");
    fireEvent.keyDown(box(), { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Sending…" }));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each([
    [reply(429, { error: "rate_limited" }), "Hannah needs a short break"],
    [reply(504, { error: "timeout" }), "Hannah took too long to answer"],
    [reply(503, { error: "unavailable" }), "Hannah couldn't answer just now"],
    [new Error("network down"), "Hannah couldn't answer just now"],
  ])("recovers from a failure and retries the same message once", async (failure, title) => {
    const fetcher = fetcherOf(failure, hannah("Let's take it step by step."));
    chat(fetcher);
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
    expect(sent(fetcher, 1).body).toEqual({
      message: "An employee shouted at a colleague.",
      history: [],
    });
  });

  it("explains a missing provider key without offering a retry", async () => {
    chat(fetcherOf(reply(503, { error: "not_configured" })));
    type("Hello");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Hannah AI isn't set up in this environment");
    expect(within(alert).queryByRole("button")).toBeNull();
  });

  it("starts over with an empty conversation", async () => {
    const fetcher = fetcherOf(hannah("Tell me more."), hannah("Fresh start."));
    chat(fetcher);
    type("First scenario");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Tell me more.");
    fireEvent.click(screen.getByRole("button", { name: "Start over" }));
    expect(screen.queryByText("First scenario")).toBeNull();
    type("Second scenario");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Fresh start.");
    expect(sent(fetcher, 1).body.history).toEqual([]);
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
  function workspace(assistant: AssistantLoad | undefined, overrides: Parameters<typeof view>[0] = {}) {
    const assistantFetcher = fetcherOf(hannah("Tell me what happened first."));
    render(
      <CaseWorkspace
        assistant={assistant}
        assistantFetcher={assistantFetcher as unknown as typeof fetch}
        cases={[]}
        companyId={COMPANY_ID}
        fetcher={fetcherOf() as unknown as typeof fetch}
        initialView={view(overrides)}
      />,
    );
    return assistantFetcher;
  }
  const tab = (name: RegExp) => screen.getByRole("tab", { name });

  it("opens on the conversation with Hannah and keeps the guided workflow one tab away", async () => {
    const assistantFetcher = workspace(READY);
    expect(screen.getByRole("tablist", { name: "Case views" })).toBeInTheDocument();
    expect(tab(/Chat with Hannah/)).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: /Chat with Hannah/ })).toBeVisible();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("[SYNTHETIC] Attendance concern");
    // The official workflow is there, just not shown.
    expect(screen.queryByRole("navigation", { name: "Question groups" })).toBeNull();
    expect(document.getElementById("case-panel-workflow")).not.toBeVisible();
    // The case details stay beside the conversation.
    const details = within(screen.getByRole("complementary", { name: "Case details" }));
    expect(details.getByRole("heading", { name: "Case status" })).toBeInTheDocument();
    expect(details.getByText("Next step in the guided workflow")).toBeInTheDocument();

    type("A fictional employee keeps arriving late.");
    fireEvent.keyDown(box(), { key: "Enter" });
    await log().findByText("Tell me what happened first.");
    expect(sent(assistantFetcher, 0).url).toBe(`${base}/messages`);

    fireEvent.click(tab(/Guided case workflow/));
    expect(tab(/Guided case workflow/)).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("list", { name: "Conversation" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Question groups" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save answers/ })).toBeInTheDocument();
    expect(screen.getByText(/guided workflow, no AI/)).toBeVisible();

    // Back to Hannah: the conversation is still there (never saved, kept while the page is open).
    fireEvent.click(tab(/Chat with Hannah/));
    expect(log().getByText("A fictional employee keeps arriving late.")).toBeInTheDocument();
    expect(log().getByText("Tell me what happened first.")).toBeInTheDocument();
  });

  it("moves between the views with the arrow keys", () => {
    workspace(READY);
    tab(/Chat with Hannah/).focus();
    fireEvent.keyDown(tab(/Chat with Hannah/), { key: "ArrowRight" });
    expect(tab(/Guided case workflow/)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tab(/Guided case workflow/), { key: "Home" });
    expect(tab(/Chat with Hannah/)).toHaveAttribute("aria-selected", "true");
  });

  it.each([
    ["switched off", { state: "hidden" } as AssistantLoad],
    ["not read (no status from the page)", undefined],
  ])("shows the guided workflow alone when the demo is %s", (_, assistant) => {
    workspace(assistant);
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryByTestId("hannah-chat")).toBeNull();
    expect(screen.getByRole("navigation", { name: "Question groups" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save answers/ })).toBeInTheDocument();
  });

  it.each([
    [
      "has no model provider",
      { state: "ready", status: { available: false, reason: "not_configured", notice: NOTICE } } as AssistantLoad,
      "Hannah AI isn't set up in this environment",
    ],
    ["couldn't be checked", { state: "unreachable" } as AssistantLoad, "Hannah AI isn't responding right now"],
  ])("leads with the guided workflow when Hannah %s, and says why on her tab", (_, assistant, title) => {
    workspace(assistant);
    expect(tab(/Guided case workflow/)).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("navigation", { name: "Question groups" })).toBeInTheDocument();
    fireEvent.click(tab(/Chat with Hannah/));
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Message Hannah" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open the guided case workflow" }));
    expect(tab(/Guided case workflow/)).toHaveAttribute("aria-selected", "true");
  });

  it("opens the guided workflow from the case details", () => {
    workspace(READY);
    const details = within(screen.getByRole("complementary", { name: "Case details" }));
    fireEvent.click(details.getByRole("button", { name: "Open in the guided workflow" }));
    expect(tab(/Guided case workflow/)).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("navigation", { name: "Question groups" })).toBeInTheDocument();

    fireEvent.click(tab(/Chat with Hannah/));
    fireEvent.click(details.getByRole("button", { name: "Documents" }));
    expect(tab(/Guided case workflow/)).toHaveAttribute("aria-selected", "true");
  });

  it("follows a link into the guided workflow from the Hannah view", () => {
    workspace(READY, { company: "uae_federal", revision: 5, progression: apiProgression() });
    expect(tab(/Chat with Hannah/)).toHaveAttribute("aria-selected", "true");
    const link = document.querySelector<HTMLAnchorElement>('a[href="#next-steps"]')!;
    fireEvent.click(link);
    expect(tab(/Guided case workflow/)).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "Next steps" })).toBeVisible();
  });

  it("doesn't offer Hannah to a member (view only)", () => {
    const assistantFetcher = workspace(READY, { canEdit: false });
    expect(assistantFetcher).not.toHaveBeenCalled();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryByTestId("hannah-chat")).toBeNull();
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(OTHER_CASE_ID).not.toBe(CASE_ID);
  });
});
