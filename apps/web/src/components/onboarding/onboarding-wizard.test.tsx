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

/** Welcome is a presentation: "Get Started" opens Company Basics. */
function start() {
  click(/^Get Started/);
}

/** Company Basics filled in; lands on About Your Company. */
function completeCompanyStep() {
  start();
  type(/^Company name/, "Gamma Trading");
  type(/^Legal business name/, "Gamma Trading FZ-LLC");
  type(/^Number of employees/, "12");
  click(/^Continue$/);
}

/** About Your Company left empty (all optional); lands on Jurisdiction. */
function toJurisdiction() {
  completeCompanyStep();
  click(/^Continue$/);
}

const progressLabels = () =>
  within(screen.getByRole("list", { name: "Setup progress" }))
    .getAllByRole("listitem")
    .map((item) => `${item.getAttribute("aria-current") === "step" ? "> " : ""}${item.textContent}`);

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

describe("OnboardingWizard: welcome (stage 1 of 6)", () => {
  it("welcomes the founder, previews the setup and sends nothing", () => {
    const { fetcher } = setup();
    expect(screen.getByRole("heading", { level: 1, name: "Welcome to HeroOS" })).toBeInTheDocument();
    const steps = screen.getByRole("list", { name: "Setup steps" });
    expect(within(steps).getAllByRole("heading").map((heading) => heading.textContent)).toEqual([
      "Step 1: Company Basics",
      "Step 2: Jurisdiction",
      "Step 3: Company Blueprint Review",
      "Step 4: Workspace Ready",
    ]);
    // The previews are not links or buttons: no skipping ahead.
    expect(within(steps).queryAllByRole("link")).toHaveLength(0);
    expect(within(steps).queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByRole("heading", { level: 2, name: "What happens next" })).toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("never offers to save unfinished details: leaving is honest about it", () => {
    setup();
    expect(document.body.textContent).not.toMatch(/Finish later|Save and finish|resume/i);
    expect(screen.getByText(/isn't saved until you create your workspace/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Leave setup" })).toHaveAttribute("href", "/workspaces");
  });

  it("Get Started opens Company Basics without a request, focusing its heading", () => {
    const { fetcher } = setup();
    expect(window.scrollTo).not.toHaveBeenCalled();
    start();
    expect(screen.getByRole("heading", { level: 1, name: "Tell us about your company" })).toHaveFocus();
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: "instant" });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("Back from Company Basics returns to Welcome and keeps what was typed", () => {
    setup();
    start();
    type(/^Company name/, "Gamma Trading");
    click("Back");
    expect(screen.getByRole("heading", { level: 1, name: "Welcome to HeroOS" })).toHaveFocus();
    start();
    expect(field(/^Company name/)).toHaveValue("Gamma Trading");
  });
});

describe("OnboardingWizard: six-stage progress", () => {
  it("marks earlier stages completed and the current one, never Complete before the server answered", () => {
    setup();
    // Welcome mirrors its review screen: the step cards preview the journey instead.
    expect(screen.queryByRole("list", { name: "Setup progress" })).toBeNull();
    start();
    expect(progressLabels()).toEqual([
      "Welcome (completed)",
      "> 2Company Basics",
      "3About Your Company",
      "4Jurisdiction",
      "5Review",
      "6Complete",
    ]);
    type(/^Company name/, "Gamma Trading");
    click(/^Continue$/);
    expect(progressLabels()[2]).toBe("> 3About Your Company");
    click(/^Continue$/);
    expect(progressLabels()[3]).toBe("> 4Jurisdiction");
    chooseLicensing("DIFC");
    click(/^Continue to Review/);
    expect(progressLabels()).toEqual([
      "Welcome (completed)",
      "Company Basics (completed)",
      "About Your Company (completed)",
      "Jurisdiction (completed)",
      "> 5Review",
      "6Complete",
    ]);
    expect(screen.getAllByText("Step 5 of 6").length).toBeGreaterThan(0);
  });
});

describe("OnboardingWizard: company basics (stage 2)", () => {
  it("requires a company name and says so next to the field", async () => {
    setup();
    start();
    expect(screen.getByRole("heading", { level: 1, name: "Tell us about your company" })).toBeInTheDocument();
    click(/^Continue$/);

    const name = field(/^Company name/);
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription(/Enter your company name\./);
    await waitFor(() => expect(name).toHaveFocus());
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Tell us about your company");
  });

  it("validates optional fields only when given", () => {
    setup();
    start();
    type(/^Company name/, "Gamma");
    type(/^Number of employees/, "a dozen");
    click(/^Continue$/);
    expect(field(/^Number of employees/)).toHaveAccessibleDescription(/Enter a whole number, such as 12\./);

    type(/^Number of employees/, "");
    click(/^Continue$/);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("About your company");
  });

  it("validates the optional text fields' limits and characters", () => {
    setup();
    start();
    type(/^Company name/, "Gamma");
    type(/^Legal business name/, "x".repeat(201));
    type(/^Industry/, "Retail\u2028Wholesale");
    click(/^Continue$/);
    expect(field(/^Legal business name/)).toHaveAccessibleDescription(/Use 200 characters or fewer\./);
    expect(field(/^Industry/)).toHaveAccessibleDescription(/Remove line breaks, tabs or other special characters\./);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Tell us about your company");
  });

  it("on a step change, returns to the top and focuses the new step's heading", () => {
    setup();
    completeCompanyStep();
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: "instant" });
    expect(screen.getByRole("heading", { level: 1, name: "About your company" })).toHaveFocus();
  });

  it("marks the one required field, the optional ones, and keeps the input hints", () => {
    setup();
    start();
    expect(screen.getAllByText("Required")).toHaveLength(1);
    expect(screen.getAllByText("Optional")).toHaveLength(3);
    expect(field(/^Company name/)).toHaveAttribute("aria-required", "true");
    expect(field(/^Company name/)).toHaveAttribute("autocomplete", "organization");
    expect(field(/^Number of employees/)).toHaveAttribute("inputmode", "numeric");
    // Only the registration contract's fields: nothing HeroOS wouldn't save.
    expect(screen.getAllByRole("textbox")).toHaveLength(4);
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});

describe("OnboardingWizard: about your company (stage 3)", () => {
  it("asks for the website, a summary and whether HR policies exist, all optional", () => {
    setup();
    completeCompanyStep();
    expect(screen.getByRole("heading", { level: 1, name: "About your company" })).toHaveFocus();
    expect(screen.getAllByText("Optional")).toHaveLength(3);
    expect(screen.queryByText("Required")).toBeNull();
    expect(field(/^Company website/)).toHaveAccessibleDescription("HeroOS keeps the address only. It doesn't visit or read your website.");
    expect(field(/^Company summary/)).toHaveAccessibleDescription(
      "Briefly describe what your company does and how your team is structured. You can paste or adapt content from your website or About page.",
    );
    const policies = screen.getByRole("group", { name: /Does your company already have HR policies\?/ });
    expect(within(policies).getAllByRole("radio").map((radio) => (radio as HTMLInputElement).value)).toEqual(["yes", "no", "not_sure"]);
    // No uploads, HR support or people questions here: those belong to the Blueprint.
    expect(document.querySelector("input[type=file]")).toBeNull();
    expect(screen.getAllByRole("textbox")).toHaveLength(2);
    click(/^Continue$/);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Your jurisdiction");
  });

  it("refuses an unsafe or malformed website next to the field, with the Blueprint's rules", async () => {
    setup();
    completeCompanyStep();
    type(/^Company website/, "javascript:alert(1)");
    click(/^Continue$/);
    expect(field(/^Company website/)).toHaveAccessibleDescription(/Use a web address that starts with https:\/\/ or http:\/\//);
    await waitFor(() => expect(field(/^Company website/)).toHaveFocus());
    type(/^Company website/, "localhost");
    click(/^Continue$/);
    expect(field(/^Company website/)).toHaveAccessibleDescription(/Enter your website's address, such as www\.example\.com\./);
    type(/^Company website/, "gamma.example");
    click(/^Continue$/);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Your jurisdiction");
  });

  it("limits the summary to the Blueprint's 2,000 characters", () => {
    setup();
    completeCompanyStep();
    type(/^Company summary/, "x".repeat(2001));
    click(/^Continue$/);
    expect(field(/^Company summary/)).toHaveAccessibleDescription(/Use 2,000 characters or fewer\./);
  });
});

describe("OnboardingWizard: jurisdiction (stage 4)", () => {
  it("offers exactly DIFC, Other and I'm not sure, with no follow-up questions", () => {
    setup();
    toJurisdiction();

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

  it("offers no licence number, upload, issuing-area list or multi-jurisdiction question, and suggests no law", () => {
    setup();
    toJurisdiction();
    expect(document.querySelector("input[type=file]")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByText(/licence number|upload/i)).toBeNull();
    for (const choice of ["DIFC", "Other", "I'm not sure"] as const) {
      chooseLicensing(choice);
      expect(document.body.textContent).not.toMatch(/MOHRE|UAE Federal|suggest|will detect|we've identified/i);
    }
    expect(screen.getByText("Jurisdiction is confirmed separately")).toBeInTheDocument();
  });

  it("requires a choice", () => {
    setup();
    toJurisdiction();
    click(/^Continue to Review/);
    expect(screen.getByRole("group", { name: "Where is your company licensed?" })).toHaveAccessibleDescription(
      /Choose where your company is licensed/,
    );
  });

  it("asks for the issuing authority only for Other, and clears it when the choice changes", () => {
    setup();
    toJurisdiction();
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
    toJurisdiction();
    click("Back");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("About your company");
    click("Back");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Tell us about your company");
    expect(field(/^Company name/)).toHaveValue("Gamma Trading");
    expect(field(/^Number of employees/)).toHaveValue("12");
  });
});

describe("OnboardingWizard: review and create (stage 5)", () => {
  function toReview(licensing: "DIFC" | "Other" | "I'm not sure" = "Other", authority = "Example Free Zone Authority") {
    toJurisdiction();
    chooseLicensing(licensing);
    if (licensing === "Other") type(/^Which authority issued your licence\?/, authority);
    click(/^Continue to Review/);
  }

  it("shows the entered values, no jurisdiction, and edit links back to each step", () => {
    setup();
    toReview();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Review your company information");
    const details = screen.getByRole("region", { name: "Company information" });
    expect(within(details).getByText("Gamma Trading")).toBeInTheDocument();
    expect(within(details).getByText("Gamma Trading FZ-LLC")).toBeInTheDocument();
    expect(within(details).getByText("12")).toBeInTheDocument();
    const licensing = screen.getByRole("region", { name: "Jurisdiction" });
    expect(within(licensing).getByText("Other licensing authority")).toBeInTheDocument();
    expect(within(licensing).getByText("Example Free Zone Authority")).toBeInTheDocument();
    expect(screen.getByText("Jurisdiction: not yet confirmed")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/MOHRE|UAE Federal|verified|compliant|eligible/);

    fireEvent.click(within(licensing).getByRole("button", { name: /Edit/ }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Your jurisdiction");
    expect(screen.getByRole("radio", { name: /^Other/ })).toBeChecked();
    expect(field(/^Which authority issued your licence\?/)).toHaveValue("Example Free Zone Authority");
  });

  it("shows what will be sent, with not-provided gaps, and asks for no certification", () => {
    setup();
    start();
    type(/^Company name/, "  Gamma Trading  ");
    click(/^Continue$/);
    click(/^Continue$/);
    chooseLicensing("I'm not sure");
    click(/^Continue to Review/);
    const details = screen.getByRole("region", { name: "Company information" });
    // Trimmed, exactly as buildRegistrationPayload sends it.
    expect(within(details).getByText("Gamma Trading")).toBeInTheDocument();
    expect(within(details).getAllByText("Not provided")).toHaveLength(3);
    expect(within(screen.getByRole("region", { name: "Jurisdiction" })).getByText("Not sure yet")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "About your company" })).getAllByText("Not provided")).toHaveLength(3);
    // The founder starts as the primary contact; the full Blueprint isn't claimed complete.
    expect(screen.getByRole("region", { name: "Primary contact" })).toHaveTextContent(/You, as the person creating this workspace/);
    expect(document.body.textContent).not.toMatch(/Blueprint (is )?complete/i);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /Confirm company details/ })).toBeNull();
  });

  it("Edit on company information returns to Company Basics with the draft intact", () => {
    setup();
    toReview();
    fireEvent.click(within(screen.getByRole("region", { name: "Company information" })).getByRole("button", { name: /Edit/ }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Tell us about your company");
    expect(field(/^Company name/)).toHaveValue("Gamma Trading");
    expect(field(/^Legal business name/)).toHaveValue("Gamma Trading FZ-LLC");
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

  it("shows and sends the company context exactly as HeroOS will store it", async () => {
    const { fetcher } = setup();
    completeCompanyStep();
    type(/^Company website/, " WWW.Gamma.example/ ");
    type(/^Company summary/, "Two shops in Dubai.\r\n\r\nEight\u00a0staff. ");
    fireEvent.click(screen.getByRole("radio", { name: /^No, not yet/ }));
    click(/^Continue$/);
    chooseLicensing("DIFC");
    click(/^Continue to Review/);

    const context = within(screen.getByRole("region", { name: "About your company" }));
    expect(context.getByText("https://www.gamma.example")).toBeInTheDocument();
    expect(context.getByText("No HR policies yet")).toBeInTheDocument();
    const summary = context.getByText(/Two shops in Dubai\./);
    expect(summary.textContent).toBe("Two shops in Dubai.\n\nEight staff.");
    fireEvent.click(context.getByRole("button", { name: /Edit/ }));
    expect(field(/^Company website/)).toHaveValue(" WWW.Gamma.example/ ");
    click(/^Continue$/);
    click(/^Continue to Review/);
    click("Create my workspace");

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const [, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      company_name: "Gamma Trading",
      blueprint: {
        legal_name: "Gamma Trading FZ-LLC",
        employee_count: 12,
        website_url: "https://www.gamma.example",
        company_summary: "Two shops in Dubai.\n\nEight staff.",
        policies_exist: "no",
        licensing: { location: "difc" },
      },
    });
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
    expect(screen.queryByRole("link", { name: "Leave setup" })).toBeNull();
    for (const edit of screen.getAllByRole("button", { name: /^Edit/ })) expect(edit).toBeDisabled();

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
    expect(screen.getByRole("region", { name: "Company information" })).toHaveTextContent("Gamma Trading");
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
    expect(screen.getByRole("region", { name: "Company information" })).toHaveTextContent(
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
    type(/^Company summary/, "A private summary.");
    click(/^Continue$/);
    chooseLicensing("Other");
    type(/^Which authority issued your licence\?/, "Example Free Zone Authority");
    expect(local).not.toHaveBeenCalled();
  });

  it("points an account that already has a workspace to it, without blocking a new company", () => {
    setup(undefined, { existingWorkspaces: [{ companyId: COMPANY_ID, name: "Alpha Example" }] });
    expect(screen.getByText("You already have a HeroOS workspace")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to my workspace" })).toHaveAttribute("href", "/workspaces");
    start();
    expect(screen.getByText("You already have a HeroOS workspace")).toBeInTheDocument();
    expect(field(/^Company name/)).toBeEnabled();
  });
});
