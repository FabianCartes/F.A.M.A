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

  const narrowScreen = (width: number) => Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  const triggerAt = (left: number, top: number) => {
    const trigger = screen.getByRole("button", { name: /ver ayuda: test-feature/i });
    trigger.getBoundingClientRect = vi.fn().mockReturnValue({ left, top, width: 14, height: 14, right: left + 14, bottom: top + 14 });
    return trigger;
  };

  it.each([[4], [180], [340]])("stays inside a 360 px phone screen when the trigger is at x=%i", (left) => {
    narrowScreen(360);
    render(<InfoTooltip {...defaultProps} />);
    fireEvent.mouseEnter(triggerAt(left, 300));
    const tooltip = screen.getByRole("tooltip");
    const x = parseFloat(tooltip.style.left), width = parseFloat(tooltip.style.width);
    expect(tooltip.style.position).toBe("fixed");
    expect(width).toBeLessThanOrEqual(344);
    expect(x).toBeGreaterThanOrEqual(8);
    expect(x + width).toBeLessThanOrEqual(352);
  });

  it("escapes clipping containers such as scrollable modal tables", () => {
    narrowScreen(1024);
    render(<div data-testid="clipper" style={{ overflow: "auto" }}><InfoTooltip {...defaultProps} /></div>);
    fireEvent.mouseEnter(triggerAt(500, 300));
    const tooltip = screen.getByRole("tooltip");
    expect(screen.getByTestId("clipper").contains(tooltip)).toBe(false);
    expect(tooltip.parentElement).toBe(document.body);
  });

  it("opens with a tap and closes with a tap outside or Escape", () => {
    render(<InfoTooltip {...defaultProps} />);
    const trigger = screen.getByRole("button", { name: /ver ayuda: test-feature/i });
    fireEvent.click(trigger);
    expect(screen.getByRole("tooltip")).toBeDefined();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
