import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ENVIRONMENT_NOTICE } from "./demo-notice";
import { LandingPage } from "./landing-page";
import { SiteHeader } from "./site-header";

describe("LandingPage", () => {
  it("keeps JJ's headline and the synthetic-data notice", () => {
    render(<LandingPage />);

    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Your HR Department without an HR Department");
    expect(screen.getByText(ENVIRONMENT_NOTICE)).toBeInTheDocument();
  });

  it("shows JJ's approved mark and wordmark in the header and footer, and no extra hero sentence", () => {
    const { container } = render(<LandingPage />);

    for (const area of ["header", "footer"]) {
      const images = [...container.querySelectorAll(`${area} img`)];
      expect(images.map((image) => image.getAttribute("src"))).toEqual([
        "/branding/heroos-mark-transparent.svg",
        "/branding/heroos-wordmark-transparent.svg",
      ]);
      for (const image of images) expect(image).toHaveAttribute("alt", "");
    }
    expect(screen.getByRole("link", { name: "HeroOS home" })).toHaveTextContent("HeroOS");
    expect(screen.queryByText(/Practical guidance/)).toBeNull();
  });

  it("sends every sign-in call to action to the login route as a plain link", () => {
    render(<LandingPage />);

    const links = screen.getAllByRole("link", { name: /^Sign in/ });
    expect(links.length).toBeGreaterThanOrEqual(3);
    for (const link of links) expect(link).toHaveAttribute("href", "/auth/login");
  });

  it("sends every Get started call to action to hosted sign-up as a plain link", () => {
    render(<LandingPage />);

    const links = screen.getAllByRole("link", { name: /^Get started/ });
    expect(links.length).toBeGreaterThanOrEqual(3);
    for (const link of links) expect(link).toHaveAttribute("href", "/auth/signup");
  });

  it("links only to sections that exist on the page", () => {
    const { container } = render(<LandingPage />);

    const anchors = [...container.querySelectorAll("a[href^='#']")].map((a) => a.getAttribute("href")!.slice(1));
    for (const id of new Set(anchors)) expect(container.querySelector(`#${id}`)).not.toBeNull();
  });

  it("shows the current year in the copyright line", () => {
    render(<LandingPage />);

    expect(screen.getByText(`© ${new Date().getFullYear()} HeroOS. All rights reserved.`)).toBeInTheDocument();
  });

  it("renders a fixed notice when one is given", () => {
    render(<LandingPage notice={{ text: "Sign-in was cancelled.", role: "alert" }} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Sign-in was cancelled.");
    expect(within(screen.getByRole("alert")).queryByRole("button")).not.toBeInTheDocument();
  });

  it("offers sign-in again and a POST sign-out after an unverified-e-mail denial", () => {
    render(<LandingPage notice={{ text: "Please verify your email address first.", role: "alert", accountActions: true }} />);

    const notice = screen.getByRole("alert");
    expect(within(notice).getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/auth/login");
    const different = within(notice).getByRole("button", { name: "Use a different account" });
    const form = different.closest("form");
    expect(form).toHaveAttribute("action", "/auth/logout");
    expect(form).toHaveAttribute("method", "post");
  });

  it("lists the three implemented capabilities and nothing else", () => {
    render(<LandingPage />);

    const section = screen.getByRole("region", { name: "Built on a secure foundation" });
    expect(within(section).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Secure sign-in",
      "Separate company workspaces",
      "Case visibility",
    ]);
  });
});

describe("WorkflowJourney", () => {
  it("selects a step on click and updates the description panel", () => {
    render(<LandingPage />);

    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(4);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");

    fireEvent.click(tabs[2]);

    expect(tabs[2]).toHaveAttribute("aria-selected", "true");
    expect(tabs[0]).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Step 3 of 4");
  });

  it("supports arrow, Home and End keys and states that it is not a live feature", () => {
    render(<LandingPage />);

    const tabs = screen.getAllByRole("tab");
    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveFocus();

    fireEvent.keyDown(tabs[1], { key: "End" });
    expect(tabs[3]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tabs[3], { key: "ArrowRight" });
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");

    expect(screen.getByRole("tabpanel")).toHaveTextContent("Guided steps are not available yet.");
  });
});

describe("SiteHeader", () => {
  it("opens and closes the mobile menu, closing on selection and Escape", () => {
    render(<SiteHeader variant="landing" />);

    const toggle = screen.getByRole("button", { name: "Open menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);
    const menu = screen.getByRole("navigation", { name: "Mobile" });
    fireEvent.click(within(menu).getByRole("link", { name: "Platform" }));
    expect(screen.queryByRole("navigation", { name: "Mobile" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("navigation", { name: "Mobile" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveFocus();
  });

  it("offers sign-in inside the mobile menu, where the header has room only for Get started", () => {
    render(<SiteHeader variant="landing" />);

    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    const menu = screen.getByRole("navigation", { name: "Mobile" });
    expect(within(menu).getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/auth/login");
  });

  it("shows no navigation or sign-in link in the workspace variant", () => {
    render(<SiteHeader variant="workspace" />);

    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
