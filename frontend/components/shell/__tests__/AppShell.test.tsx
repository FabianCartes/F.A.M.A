import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import AppShell from "../AppShell";

beforeEach(() => {
  window.localStorage.clear();
});

function renderShell() {
  const onNavigate = vi.fn();
  render(
    <AppShell
      onNavigate={onNavigate}
      sidebar={(actions) => (
        <nav aria-label="Navegación principal">
          <button type="button" onClick={actions.closeSidebar}>
            Dashboard
          </button>
          <button
            type="button"
            aria-label="Colapsar panel lateral"
            aria-expanded={!actions.isSidebarCollapsed}
            onClick={actions.toggleSidebarCollapsed}
          >
            Colapsar
          </button>
        </nav>
      )}
    >
      <h1>Contenido principal</h1>
    </AppShell>,
  );
  return {
    onNavigate,
    toggle: screen.getByRole("button", { name: /menú/i }),
    collapse: screen.getByRole("button", { name: "Colapsar panel lateral" }),
  };
}

describe("AppShell collapsible navigation", () => {
  it("keeps the main content reachable", () => {
    renderShell();
    expect(screen.getByText("Contenido principal")).toBeDefined();
  });

  it("renders the navigation the shell is given", () => {
    renderShell();
    expect(screen.getByRole("navigation", { name: "Navegación principal" })).toBeDefined();
  });

  it("starts collapsed on a small screen and says so", () => {
    const { toggle } = renderShell();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("reveals the navigation when the operator activates the toggle", () => {
    const { toggle } = renderShell();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("exposes the toggle as a control that points at the navigation region", () => {
    const { toggle } = renderShell();
    expect(toggle.getAttribute("aria-controls")).toBe("app-sidebar");
    const sidebar = document.getElementById("app-sidebar");
    expect(sidebar).not.toBeNull();
    expect(sidebar?.classList.contains("h-full")).toBe(true);
  });

  it("closes the navigation after the operator picks a destination", () => {
    const { toggle } = renderShell();
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "Dashboard" }));
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("tells the shell owner that navigation happened", () => {
    const { toggle, onNavigate } = renderShell();
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "Dashboard" }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });

  it("closes the navigation when the operator presses Escape", () => {
    const { toggle } = renderShell();
    fireEvent.click(toggle);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("closes the navigation when the operator taps the scrim", () => {
    const { toggle } = renderShell();
    fireEvent.click(toggle);
    fireEvent.click(screen.getByTestId("app-shell-scrim"));
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("closes the navigation as soon as the viewport is widened past the mobile breakpoint", () => {
    const listeners: Array<() => void> = [];
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      addEventListener: (_: string, notify: () => void) => listeners.push(notify),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
      onchange: null,
    })) as unknown as typeof window.matchMedia;

    try {
      const { toggle } = renderShell();
      fireEvent.click(toggle);
      expect(toggle.getAttribute("aria-expanded")).toBe("true");

      act(() => {
        listeners.forEach((notify) => notify());
      });
      expect(toggle.getAttribute("aria-expanded")).toBe("false");

    } finally {
      window.matchMedia = original;
    }
  });

  it("survives an environment without matchMedia", () => {
    const original = window.matchMedia;
    (window as { matchMedia?: unknown }).matchMedia = undefined;

    try {
      const { toggle } = renderShell();
      fireEvent.click(toggle);
      expect(toggle.getAttribute("aria-expanded")).toBe("true");
    } finally {
      window.matchMedia = original;
    }
  });

  it("starts with the panel expanded on desktop", () => {
    const { collapse } = renderShell();
    expect(collapse.getAttribute("aria-expanded")).toBe("true");
  });

  it("collapses the panel to icons when the operator collapses it", () => {
    const { collapse } = renderShell();
    fireEvent.click(collapse);
    expect(collapse.getAttribute("aria-expanded")).toBe("false");
  });

  it("expands the panel again on a second activation", () => {
    const { collapse } = renderShell();
    fireEvent.click(collapse);
    fireEvent.click(collapse);
    expect(collapse.getAttribute("aria-expanded")).toBe("true");
  });

  it("keeps the off-canvas drawer independent of the desktop collapse state", () => {
    const { collapse, toggle } = renderShell();
    fireEvent.click(collapse);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("remembers a panel the operator had already collapsed", () => {
    window.localStorage.setItem("fama:sidebar-collapsed", "true");
    try {
      const { collapse } = renderShell();
      expect(collapse.getAttribute("aria-expanded")).toBe("false");
    } finally {
      window.localStorage.removeItem("fama:sidebar-collapsed");
    }
  });

  it("remembers a panel the operator had already expanded", () => {
    window.localStorage.setItem("fama:sidebar-collapsed", "false");
    try {
      const { collapse } = renderShell();
      expect(collapse.getAttribute("aria-expanded")).toBe("true");
    } finally {
      window.localStorage.removeItem("fama:sidebar-collapsed");
    }
  });

  it("still collapses for the session when storage is unavailable", () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });

    try {
      const { collapse } = renderShell();
      const before = collapse.getAttribute("aria-expanded");
      fireEvent.click(collapse);
      expect(collapse.getAttribute("aria-expanded")).toBe(before === "true" ? "false" : "true");
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });
});
