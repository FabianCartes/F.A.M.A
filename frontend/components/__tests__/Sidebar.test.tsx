import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
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

const DESTINATIONS = ["Dashboard", "Gestión de audios", "Entrenamiento", "Predicción"];

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
    expect(screen.getByRole("button", { name: "Gestión de audios" }).getAttribute("aria-current")).toBeNull();
  });

  it("preserves the ingesta navigation key under the new visible label", () => {
    const onSelectTab = vi.fn();
    render(<Sidebar activeTab="ingesta" onSelectTab={onSelectTab} isCollapsed={false} onToggleCollapsed={vi.fn()} />);
    const destination = screen.getByRole('button', { name: 'Gestión de audios' });
    fireEvent.click(destination);
    expect(onSelectTab).toHaveBeenCalledWith('ingesta');
    expect(destination.getAttribute('aria-current')).toBe('page');
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

  it("renders GCP status dot indicator and GPU badge in collapsed mode", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/training/hardware")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ cuda_available: true, temperature_c: 45 }),
        });
      }
      return Promise.resolve({ ok: false });
    });

    renderSidebar(true);
    expect(screen.getByLabelText(/GCP Conectado/i)).toBeDefined();
    const badge = await screen.findByTestId("hardware-badge-collapsed");
    expect(badge.textContent).toBe("GPU");
    expect(badge.className).toContain("text-cyan-400");
  });

  it("renders CPU badge in collapsed mode when CUDA is not available", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/training/hardware")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ cuda_available: false }),
        });
      }
      return Promise.resolve({ ok: false });
    });

    renderSidebar(true);
    const badge = await screen.findByTestId("hardware-badge-collapsed");
    expect(badge.textContent).toBe("CPU");
  });
});
