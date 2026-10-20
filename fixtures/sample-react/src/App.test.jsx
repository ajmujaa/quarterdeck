import React from "react";
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import App from "./App.jsx";

describe("App", () => {
  it("adds a todo and counts it", () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("New todo"), { target: { value: "milk" } });
    fireEvent.click(screen.getByText("Add"));
    expect(screen.getByText("milk")).toBeTruthy();
    expect(screen.getByText("1 left")).toBeTruthy();
  });
});
