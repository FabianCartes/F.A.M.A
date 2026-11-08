import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import Sidebar from "../Sidebar";
import SessionBoundary from "../auth/SessionBoundary";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/lib/api/feedbackApi", () => ({ getFeedbackStats: vi.fn().mockResolvedValue({ pending_curation_count: 3 }) }));
const user = { id: 1, email: "synthetic@example.test", nombre_completo: "Synthetic researcher with a long name", rol: "investigador", activo: true };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function Workspace({ collapsed = false }) {
  const [isCollapsed, setCollapsed] = useState(collapsed);
  return <Sidebar activeTab="dashboard" onSelectTab={vi.fn()} isCollapsed={isCollapsed} onToggleCollapsed={() => setCollapsed(!isCollapsed)} />;
}
it("places the single named session and honest role in the sidebar above GCP and logs out", async () => {
  const request = vi.fn(async (url: string) => url.endsWith("/logout") ? new Response(null, { status: 204 }) : Response.json(user));
  vi.stubGlobal("fetch", request);
  const { container } = render(<SessionBoundary><Workspace /></SessionBoundary>);
  const name = await screen.findByText(user.nombre_completo);
  const sidebar = screen.getByRole("complementary");
  expect(sidebar.contains(name)).toBe(true);
  expect(within(sidebar).getByText(user.rol)).toBeDefined();
  expect(name.getAttribute("title")).toBe(user.nombre_completo);
  expect(name.compareDocumentPosition(within(sidebar).getByText("GCP")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getAllByRole("button", { name: "Cerrar sesión" })).toHaveLength(1);
  expect(container.querySelector(".session-toolbar")).toBeNull();
  expect(sidebar.textContent).not.toContain(user.email);
  fireEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
  expect(screen.queryByRole("complementary")).toBeNull();
  expect(request.mock.calls.some(([url]) => url.endsWith("/logout"))).toBe(true);
});
it("expands the collapsed user icon without logging out, retaining mobile details", async () => {
  const request = vi.fn(async () => Response.json(user));
  vi.stubGlobal("fetch", request);
  render(<SessionBoundary><Workspace collapsed /></SessionBoundary>);
  const expand = await screen.findByRole("button", { name: "Mostrar sesión de usuario" });
  expect(expand.title).toBe("Mostrar sesión de usuario");
  expect(expand.getAttribute("aria-expanded")).toBe("false");
  expect(expand.querySelector("svg")).not.toBeNull();
  expect(expand.className).toContain("hidden md:flex");
  expect(screen.getByText(user.nombre_completo).closest("[data-session-details]")?.className).toContain("md:hidden");
  fireEvent.click(expand);
  expect(screen.queryByRole("button", { name: "Mostrar sesión de usuario" })).toBeNull();
  expect(screen.getByRole("button", { name: "Cerrar sesión" })).toBeDefined();
  expect(request).toHaveBeenCalledTimes(2); // session confirmation and existing hardware request only
});
it("does not invent a session outside the authenticated provider", () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
  render(<Workspace />);
  expect(screen.queryByRole("region", { name: "Sesión actual" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Cerrar sesión" })).toBeNull();
});
