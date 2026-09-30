import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import InfoTooltip from "../InfoTooltip";

describe("InfoTooltip Component", () => {
  const defaultProps = {
    id: "test-feature",
    title: "Sample Feature",
    impact: "Controls the temporal resolution of features.",
    usage: "Use lower values for rapid transients, higher for tonal signals.",
    keyPoints: ["Point 1: 512 frames default", "Point 2: Affects GPU memory"],
  };

  it("renders trigger button with question mark and is accessible", () => {
    render(<InfoTooltip {...defaultProps} />);

    const trigger = screen.getByRole("button", { name: /ver ayuda: test-feature/i });
    expect(trigger).toBeDefined();
    expect(trigger.textContent).toContain("?");
  });

  it("does not display tooltip content initially", () => {
    render(<InfoTooltip {...defaultProps} />);

    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(screen.queryByText(defaultProps.impact)).toBeNull();
  });

  it("shows tooltip on mouse enter and hides on mouse leave", () => {
    render(<InfoTooltip {...defaultProps} />);

    const trigger = screen.getByRole("button", { name: /ver ayuda: test-feature/i });

    // Hover in
    fireEvent.mouseEnter(trigger);

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toBeDefined();
    expect(screen.getByText(defaultProps.title)).toBeDefined();
    expect(screen.getByText(defaultProps.impact)).toBeDefined();
    expect(screen.getByText(defaultProps.usage)).toBeDefined();
    expect(screen.getByText("Point 1: 512 frames default")).toBeDefined();

    // Hover out
    fireEvent.mouseLeave(trigger);

    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("shows tooltip on focus and hides on blur for keyboard accessibility", () => {
    render(<InfoTooltip {...defaultProps} />);

    const trigger = screen.getByRole("button", { name: /ver ayuda: test-feature/i });

    // Focus
    fireEvent.focus(trigger);
    expect(screen.getByRole("tooltip")).toBeDefined();

    // Blur
    fireEvent.blur(trigger);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("supports explicit position='bottom' and align='left'", () => {
    render(<InfoTooltip {...defaultProps} position="bottom" align="left" />);

    const trigger = screen.getByRole("button", { name: /ver ayuda: test-feature/i });
    fireEvent.mouseEnter(trigger);

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip.className).toContain("top-full");
    expect(tooltip.className).toContain("-left-2");
  });

  it("supports explicit position='top' and align='right'", () => {
    render(<InfoTooltip {...defaultProps} position="top" align="right" />);

    const trigger = screen.getByRole("button", { name: /ver ayuda: test-feature/i });
    fireEvent.mouseEnter(trigger);

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip.className).toContain("bottom-full");
    expect(tooltip.className).toContain("-right-2");
  });

  it("automatically aligns to 'left' when close to the left boundary (e.g. sidebar area)", () => {
    render(<InfoTooltip {...defaultProps} />);
    const trigger = screen.getByRole("button", { name: /ver ayuda: test-feature/i });
    trigger.getBoundingClientRect = vi.fn().mockReturnValue({
      left: 100,
      top: 300,
      width: 14,
      height: 14,
      right: 114,
      bottom: 314,
    });

    fireEvent.mouseEnter(trigger);

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip.className).toContain("-left-2");
  });
});
