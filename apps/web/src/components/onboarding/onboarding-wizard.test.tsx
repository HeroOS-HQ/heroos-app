import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingWizard } from "./onboarding-wizard";

const COMPANY_ID = "d3e0a000-0000-4000-8000-000000000001";

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function setup(responses: (Response | Error)[] = [reply(201, { outcome: "created", companyId: COMPANY_ID })], props = {}) {
  const queue = [...responses];
  const fetcher = vi.fn(async () => {
    const next = queue.shift() ?? reply(500, {});
    if (next instanceof Error) throw next;
    return next;
  });
  const navigate = vi.fn();
  render(<OnboardingWizard fetcher={fetcher as unknown as typeof fetch} navigate={navigate} {...props} />);
  return { fetcher, navigate };
}

const field = (name: RegExp) => screen.getByRole("textbox", { name });
const type = (name: RegExp, value: string) => fireEvent.change(field(name), { target: { value } });
const click = (name: RegExp | string) => fireEvent.click(screen.getByRole("button", { name }));

function completeCompanyStep() {
  type(/^Company name/, "Gamma Trading");
  type(/^Legal business name/, "Gamma Trading FZ-LLC");
  type(/^Number of employees/, "12");
  click("Continue");
}

function chooseLicensing(label: "DIFC" | "Other" | "I'm not sure") {
  fireEvent.click(screen.getByRole("radio", { name: new RegExp(`^${label}`) }));
}

/** What the browser does when the page starts to leave; true = it would ask "Leave site?". */
function browserWouldPrompt() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

beforeEach(() => {
  // jsdom has no layout or scrolling.
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("OnboardingWizard: company details (step 1)", () => {
  it("requires a company name and says so next to the field", async () => {
    setup();
    expect(screen.getByRole("heading", { level: 1, name: "Let's set up your company" })).toBeInTheDocument();
    click("Continue");

    const name = field(/^Company name/);
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription(/Enter your company name\./);
    await waitFor(() => expect(name).toHaveFocus());
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Let's set up your company");
  });

  it("validates optional fields only when given", () => {
    setup();
    type(/^Company name/, "Gamma");
    type(/^Number of employees/, "a dozen");
    click("Continue");
    expect(field(/^Number of employees/)).toHaveAccessibleDescription(/Enter a whole number, such as 12\./);

    type(/^Number of employees/, "");
    click("Continue");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Where is your company licensed?");
  });

  it("on a step change, returns to the top and focuses the new step's heading", () => {
    setup();
    expect(window.scrollTo).not.toHaveBeenCalled();
    completeCompanyStep();
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: "instant" });
    expect(screen.getByRole("heading", { level: 1, name: "Where is your company licensed?" })).toHaveFocus();
  });

  it("marks the required field and uses organization autocomplete", () => {
    setup();
    expect(screen.getByText("(required)")).toBeInTheDocument();
    expect(field(/^Company name/)).toHaveAttribute("autocomplete", "organization");
    expect(field(/^Number of employees/)).toHaveAttribute("inputmode", "numeric");
  });
});

describe("OnboardingWizard: licensing (step 2)", () => {
  it("offers exactly DIFC, Other and I'm not sure, with no follow-up questions", () => {
    setup();
    completeCompanyStep();

    const group = screen.getByRole("group", { name: "Where is your company licensed?" });
    expect(within(group).getAllByRole("radio").map((radio) => (radio as HTMLInputElement).value)).toEqual([
      "difc",
      "other",
      "not_sure",
    ]);
    chooseLicensing("I'm not sure");
    // No quiz: no further inputs or questions appear for "not sure".
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
    expect(screen.queryAllByRole("radio")).toHaveLength(3);
    expect(screen.getByText(/That's okay\. Your licensing details can be confirmed later\./)).toBeInTheDocument();
  });

  it("requires a choice", () => {
    setup();
    completeCompanyStep();
    click("Continue");
    expect(screen.getByRole("group", { name: "Where is your company licensed?" })).toHaveAccessibleDescription(
      /Choose where your company is licensed/,
    );
  });

  it("asks for the issuing authority only for Other, and clears it when the choice changes", () => {
    setup();
    completeCompanyStep();
    chooseLicensing("Other");
    type(/^Which authority issued your licence\?/, "Example Free Zone Authority");

    chooseLicensing("DIFC");
    expect(screen.queryByRole("textbox", { name: /Which authority/ })).toBeNull();
    expect(screen.getByText(/licensed in the DIFC\. Which employment rules apply is confirmed separately/)).toBeInTheDocument();

    chooseLicensing("Other");
    expect(field(/^Which authority issued your licence\?/)).toHaveValue("");
  });

  it("keeps the draft when going back and forward", () => {
    setup();
    completeCompanyStep();
    click("Back");
    expect(field(/^Company name/)).toHaveValue("Gamma Trading");
    expect(field(/^Number of employees/)).toHaveValue("12");
  });
});

describe("OnboardingWizard: review and create (step 3)", () => {
  function toReview(licensing: "DIFC" | "Other" | "I'm not sure" = "Other", authority = "Example Free Zone Authority") {
    completeCompanyStep();
    chooseLicensing(licensing);
    if (licensing === "Other") type(/^Which authority issued your licence\?/, authority);
    click("Continue");
  }

  it("shows the entered values, no jurisdiction, and edit links back to each step", () => {
    setup();
    toReview();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Review your company details");
    const details = screen.getByRole("region", { name: "Company details" });
    expect(within(details).getByText("Gamma Trading")).toBeInTheDocument();
    expect(within(details).getByText("Gamma Trading FZ-LLC")).toBeInTheDocument();
    expect(within(details).getByText("12")).toBeInTheDocument();
    const licensing = screen.getByRole("region", { name: "Licensing" });
    expect(within(licensing).getByText("Other licensing authority")).toBeInTheDocument();
    expect(within(licensing).getByText("Example Free Zone Authority")).toBeInTheDocument();
    expect(screen.getByText("Jurisdiction: not yet confirmed")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/MOHRE|UAE Federal|verified|compliant|eligible/);

    fireEvent.click(within(licensing).getByRole("button", { name: /Edit/ }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Where is your company licensed?");
    expect(screen.getByRole("radio", { name: /^Other/ })).toBeChecked();
  });

  it("creates the workspace once, with exactly the M1-10C payload, then opens the ready page", async () => {
    const { fetcher, navigate } = setup();
    toReview();
    click("Create my workspace");

    await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/workspaces/${COMPANY_ID}/ready?outcome=created`));
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/bff/registrations");
    expect(init.headers).not.toHaveProperty("Authorization");
    expect(JSON.parse(String(init.body))).toEqual({
      company_name: "Gamma Trading",
      blueprint: {
        legal_name: "Gamma Trading FZ-LLC",
        employee_count: 12,
        licensing: { location: "other", authority: "Example Free Zone Authority" },
      },
    });
    expect(screen.getByRole("button", { name: /Opening your workspace/ })).toBeDisabled();
  });

  it("sends 'not sure' as its own answer, never Other with a placeholder", async () => {
    const { fetcher } = setup();
    toReview("I'm not sure");
    click("Create my workspace");
    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    const [, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body)).blueprint.licensing).toEqual({ location: "not_sure" });
  });

  it("asks before leaving with unsaved details, and still does after a failed attempt", async () => {
    setup([reply(503, { error: "unavailable" })]);
    expect(browserWouldPrompt()).toBe(false);
    toReview("DIFC");
    expect(browserWouldPrompt()).toBe(true);
    click("Create my workspace");
    await screen.findByRole("alert");
    expect(browserWouldPrompt()).toBe(true);
  });

  it("leaves for the ready page without the unsaved-details prompt (it could cancel the way there)", async () => {
    // The browser fires beforeunload as soon as the page starts to leave, before
    // React re-renders: a "Leave site?" answered with Cancel left the page
    // locked on "Opening your workspace…" with the workspace already created.
    const prompted: boolean[] = [];
    const navigate = vi.fn(() => prompted.push(browserWouldPrompt()));
    setup(undefined, { navigate });
    toReview("DIFC");
    click("Create my workspace");

    await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/workspaces/${COMPANY_ID}/ready?outcome=created`));
    expect(prompted).toEqual([false]);
    expect(browserWouldPrompt()).toBe(false);
  });

  it("if the page doesn't leave, links to the workspace instead of staying locked", async () => {
    const { fetcher, navigate } = setup([reply(200, { outcome: "existing", companyId: COMPANY_ID })]);
    toReview("DIFC");
    click("Create my workspace");

    await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("link", { name: "open it here" })).toHaveAttribute(
      "href",
      `/workspaces/${COMPANY_ID}/ready?outcome=existing`,
    );
    // Still one registration: the way on is the link, never a second request.
    expect(screen.getByRole("button", { name: /Opening your workspace/ })).toBeDisabled();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("goes to the ready page with outcome=existing when the account already registered", async () => {
    const { navigate } = setup([reply(200, { outcome: "existing", companyId: COMPANY_ID })]);
    toReview("DIFC");
    click("Create my workspace");
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/workspaces/${COMPANY_ID}/ready?outcome=existing`));
  });

  it("cannot send two registrations from repeated clicks", async () => {
    let resolve: (response: Response) => void = () => {};
    const fetcher = vi.fn(() => new Promise<Response>((done) => (resolve = done)));
    const navigate = vi.fn();
    render(<OnboardingWizard fetcher={fetcher as unknown as typeof fetch} navigate={navigate} />);
    toReview("DIFC");

    const button = screen.getByRole("button", { name: "Create my workspace" });
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: /Creating your workspace/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Back/ })).toBeDisabled();

    await act(async () => resolve(reply(201, { outcome: "created", companyId: COMPANY_ID })));
    await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each([
    [reply(401, { error: "session_expired" }), "Your session has ended"],
    [reply(403, { error: "refused" }), "We couldn't create a workspace for this account"],
    [reply(404, { error: "registration_unavailable" }), "Workspace setup isn't available yet"],
    [reply(503, { error: "unavailable" }), "We couldn't confirm that your workspace was created"],
    [new TypeError("Failed to fetch"), "We couldn't confirm that your workspace was created"],
    [reply(201, { outcome: "created" }), "We couldn't confirm that your workspace was created"],
  ])("shows an honest message and never a success (%#)", async (response, title) => {
    const { navigate } = setup([response]);
    toReview("DIFC");
    click("Create my workspace");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(title);
    expect(navigate).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toMatch(/workspace is ready|Opening your workspace/);
    // The draft is kept for another attempt.
    expect(screen.getByRole("region", { name: "Company details" })).toHaveTextContent("Gamma Trading");
    expect(screen.getByRole("button", { name: "Create my workspace" })).toBeEnabled();
  });

  it("after an uncertain outcome, trying again is offered and the backend's answer decides", async () => {
    const { fetcher, navigate } = setup([
      new TypeError("Failed to fetch"),
      reply(200, { outcome: "existing", companyId: COMPANY_ID }),
    ]);
    toReview("DIFC");
    click("Create my workspace");
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("link", { name: "Check my workspaces" })).toHaveAttribute("href", "/workspaces");

    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/workspaces/${COMPANY_ID}/ready?outcome=existing`));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("marks the fields the server refused", async () => {
    setup([reply(422, { error: "invalid", fields: ["companyName"] })]);
    toReview("DIFC");
    click("Create my workspace");
    expect(await screen.findByRole("alert")).toHaveTextContent("Some details need attention");
    expect(screen.getByRole("region", { name: "Company details" })).toHaveTextContent(
      "HeroOS couldn't accept this value",
    );
    fireEvent.click(screen.getByRole("button", { name: "Review company details" }));
    expect(field(/^Company name/)).toHaveAccessibleDescription(/HeroOS couldn't accept this value/);
  });

  it("a session-ended failure offers sign-in again", async () => {
    setup([reply(401, { error: "session_expired" })]);
    toReview("DIFC");
    click("Create my workspace");
    expect(within(await screen.findByRole("alert")).getByRole("link", { name: "Sign in again" })).toHaveAttribute(
      "href",
      "/auth/login",
    );
  });
});

describe("OnboardingWizard: privacy and context", () => {
  it("never writes the draft to browser storage", () => {
    const local = vi.spyOn(Storage.prototype, "setItem");
    setup();
    completeCompanyStep();
    chooseLicensing("Other");
    type(/^Which authority issued your licence\?/, "Example Free Zone Authority");
    expect(local).not.toHaveBeenCalled();
  });

  it("points an account that already has a workspace to it, without blocking a new company", () => {
    setup(undefined, { existingWorkspaces: [{ companyId: COMPANY_ID, name: "Alpha Example" }] });
    expect(screen.getByText("You already have a HeroOS workspace")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to my workspace" })).toHaveAttribute("href", "/workspaces");
    expect(field(/^Company name/)).toBeEnabled();
  });
});
