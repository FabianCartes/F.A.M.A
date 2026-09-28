import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import Sidebar from "../Sidebar";

vi.mock("@/lib/api/feedbackApi", () => ({
  getFeedbackStats: vi.fn().mockResolvedValue({ pending_curation_count: 3 }),
}));

const originalFetch = global.fetch;

function renderSidebar(isCollapsed: boolean) {
  const onToggleCollapsed = vi.fn();
  render(
    <Sidebar
      activeTab="prediccion"
      onSelectTab={vi.fn()}
      isCollapsed={isCollapsed}
      onToggleCollapsed={onToggleCollapsed}
    />,
  );
  return {
    onToggleCollapsed,
    trigger: screen.getByRole("button", { name: /panel lateral/i }),
  };
}

const DESTINATIONS = ["Dashboard", "Ingesta", "Entrenamiento", "Predicción"];

describe("Sidebar destinations", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false });
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("names every destination when the panel is expanded", () => {
    renderSidebar(false);
    DESTINATIONS.forEach((label) => {
      expect(screen.getByRole("button", { name: label })).toBeDefined();
    });
  });

  it("keeps every destination named when collapsed to icons", () => {
    renderSidebar(true);
    DESTINATIONS.forEach((label) => {
      expect(screen.getByRole("button", { name: label })).toBeDefined();
    });
  });

  it("marks the current destination for assistive technology", () => {
    renderSidebar(false);
    expect(screen.getByRole("button", { name: "Predicción" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(screen.getByRole("button", { name: "Ingesta" }).getAttribute("aria-current")).toBeNull();
  });

  it("reports the panel as expanded through its collapse control", () => {
    const { trigger } = renderSidebar(false);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(trigger.getAttribute("aria-label")).toBe("Colapsar panel lateral");
    expect(trigger.textContent).toContain("Colapsar");
    const path = trigger.querySelector("svg path");
    expect(path?.getAttribute("d")).toBe("M15 19l-7-7 7-7");
  });

  it("reports the panel as collapsed through its collapse control", () => {
    const { trigger } = renderSidebar(true);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(trigger.getAttribute("aria-label")).toBe("Expandir panel lateral");
    expect(trigger.textContent).toContain("Expandir");
    const path = trigger.querySelector("svg path");
    expect(path?.getAttribute("d")).toBe("M9 5l7 7-7 7");
  });

  it("still reports how many items await curation when collapsed to icons", async () => {
    renderSidebar(true);
    expect(await screen.findByText("3")).toBeDefined();
  });
});
