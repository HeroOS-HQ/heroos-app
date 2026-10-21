import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { COMPANY_ID } from "@/test/fixtures";
import { CASE_ID } from "@/test/workflow-fixtures";

import { AskWorkspace } from "./ask-workspace";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function setup(mode: "ready" | "members" | "unavailable" = "ready", ...responses: (Response | Error)[]) {
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
      fetcher={fetcher as unknown as typeof fetch}
      mode={mode}
      navigate={navigate}
      returning={false}
    />,
  );
  return { fetcher, navigate };
}

const box = () => screen.getByRole("textbox", { name: "Explain the situation in your own words" });
const send = () => screen.getByRole("button", { name: "Send" });
const bodyOf = (fetcher: ReturnType<typeof setup>["fetcher"], index = 0) =>
  JSON.parse(String((fetcher.mock.calls[index] as [string, RequestInit])[1].body)) as Record<string, string>;
const WORDS = "[SYNTHETIC] One of my team hasn't come in for two days and isn't answering.";

describe("AskWorkspace (Ask HeroOS)", () => {
  it("asks one question in one box: no workflow, category, stage or title to choose", () => {
    setup();
    expect(screen.getByRole("heading", { level: 1, name: "What can HR do for you today?" })).toBeInTheDocument();
    expect(screen.getByText("Explain the situation in your own words.")).toBeInTheDocument();
    expect(screen.getByText("Welcome.")).toBeInTheDocument();
    expect(box()).toBeEnabled();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(document.body.textContent).not.toMatch(/Disciplinary|category|workflow|title/i);
    // Send stays quiet until there is something to send.
    expect(send()).toBeDisabled();
    fireEvent.change(box(), { target: { value: "   " } });
    expect(send()).toBeDisabled();
  });

  it("opens the case with the founder's words, a neutral title and one key per write, then goes there", async () => {
    const { fetcher, navigate } = setup("ready", reply(200, { caseId: CASE_ID, narrativeSaved: true }));
    fireEvent.change(box(), { target: { value: `  ${WORDS}\n` } });
    fireEvent.click(send());

    // While the case opens: the words, and HeroOS opening a case (never "reviewing": nothing reviews yet).
    expect(await screen.findByRole("status", { name: "HeroOS is opening a case for this" })).toBeInTheDocument();
    expect(screen.getByText(WORDS)).toBeInTheDocument();
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/workspaces/${COMPANY_ID}/cases/${CASE_ID}`));

    const [url, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/ask`);
    expect(init.method).toBe("POST");
    const body = bodyOf(fetcher);
    expect(Object.keys(body).sort()).toEqual(["requestKey", "submissionKey", "text", "title"]);
    expect(body.text).toBe(WORDS);
    expect(body.title).toMatch(/^New case · \d{1,2} [A-Z][a-z]{2}, \d{2}:\d{2}$/);
    // The title never carries the founder's words (which may name an employee).
    expect(body.title).not.toMatch(/team|answering/);
    expect(body.requestKey).toMatch(UUID);
    expect(body.submissionKey).toMatch(UUID);
    expect(body.submissionKey).not.toBe(body.requestKey);
  });

  it("retries the same words with the same keys, so one case opens", async () => {
    const { fetcher } = setup("ready", new TypeError("Failed to fetch"), reply(503, { error: "unavailable" }));
    fireEvent.change(box(), { target: { value: WORDS } });
    fireEvent.click(send());
    expect(await screen.findByRole("alert")).toHaveTextContent("HeroOS couldn't be reached");
    // The words stay in the box.
    expect(box()).toHaveValue(WORDS);
    fireEvent.click(send());
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(bodyOf(fetcher, 1)).toEqual(bodyOf(fetcher, 0));
  });

  it("says plainly when the case opened but the words didn't reach it, and links to the case", async () => {
    const { navigate } = setup("ready", reply(200, { caseId: CASE_ID, narrativeSaved: false }));
    fireEvent.change(box(), { target: { value: WORDS } });
    fireEvent.click(send());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("HeroOS opened the case but couldn't save your description.");
    expect(screen.getByRole("link", { name: "Open the case" })).toHaveAttribute("href", `/workspaces/${COMPANY_ID}/cases/${CASE_ID}`);
    expect(navigate).not.toHaveBeenCalled();
    expect(box()).toHaveValue(WORDS);
  });

  it.each([
    [reply(401, { error: "session_expired" }), "Your session has ended"],
    [reply(403, { error: "refused" }), "Only company administrators can open cases."],
    [reply(422, { error: "invalid", fields: [] }), "HeroOS couldn't accept this text."],
    [reply(409, { error: "conflict" }), "Something changed while the case was opening."],
    [reply(200, { nothing: true }), "HeroOS couldn't be reached."],
  ])("never pretends the case opened after a failure (%#)", async (response, text) => {
    const { navigate } = setup("ready", response);
    fireEvent.change(box(), { target: { value: WORDS } });
    fireEvent.click(send());
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(navigate).not.toHaveBeenCalled();
  });

  it.each([
    ["members", "Only company administrators can open cases for now."],
    ["unavailable", "HeroOS can't open cases in this workspace yet."],
  ] as const)("says why the box can't be used (%s), and sends nothing", (mode, placeholder) => {
    const { fetcher } = setup(mode);
    expect(box()).toBeDisabled();
    expect(box()).toHaveAttribute("placeholder", placeholder);
    expect(send()).toBeDisabled();
    fireEvent.click(send());
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("shows focus on the rounded composer, never as a rectangle on the field", () => {
    setup();
    // The global :focus-visible outline is unlayered CSS: only an important utility turns it off
    // (the real cascade is checked in a browser, e2e A11Y-12).
    expect(box()).toHaveClass("focus-visible:outline-hidden!");
    expect(box().parentElement).toHaveClass("rounded-[1.75rem]", "focus-within:border-hero-blue");
  });

  it("welcomes a founder back once there are cases", () => {
    render(<AskWorkspace companyId={COMPANY_ID} mode="ready" returning />);
    expect(screen.getByText("Welcome back.")).toBeInTheDocument();
  });
});
