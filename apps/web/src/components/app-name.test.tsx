import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppName } from "./app-name";

describe("AppName", () => {
  it("renders the HeroOS application name", () => {
    render(<AppName />);

    expect(screen.getByText("HeroOS")).toBeInTheDocument();
  });
});