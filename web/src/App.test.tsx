import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import App from "./App";

test("見出しが出る", () => {
  render(<App />);
  expect(
    screen.getByRole("heading", { name: "Get started" }),
  ).toBeInTheDocument();
});
