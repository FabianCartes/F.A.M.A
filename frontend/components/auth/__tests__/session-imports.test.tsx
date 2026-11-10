import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import Boundary from "../SessionBoundary";
import SidebarSession from "@/components/SidebarSession";
function SessionBoundary({ children }: { children: React.ReactNode }) {
  return <Boundary><SidebarSession isCollapsed={false} onToggleCollapsed={() => {}} />{children}</Boundary>;
}
import DatasetExportDialog from "@/components/ingestion/DatasetExportDialog";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
const user = { id: 1, email: "owner@example.test", nombre_completo: "Synthetic owner", rol: "investigador", activo: true };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("enables private import with a confirmed cookie and no Bearer in non-development mode", async () => {
  const request = vi.fn(async (path: string, options?: RequestInit) => {
    expect(new Headers(options?.headers).get("Authorization")).toBeNull();
    if (path.endsWith("/api/auth/me")) return Response.json(user);
    if (path.endsWith("/access")) return Response.json({ development_mode: false });
    if (path.endsWith("/limits")) return Response.json({ received_bytes: 1024, expanded_bytes: 4096,
      entries: 10, depth: 12, path_bytes: 240, audio_bytes: 1024, audio_seconds: 600,
      validation_seconds: 60, free_bytes: 1, ttl_seconds: 86400, concurrent_imports: 4 });
    if (new URL(path, "http://synthetic.test").pathname.endsWith("/api/ingestion/imports")) return Response.json({ imports: [], total: 0, next_cursor: null, snapshot: "empty" });
    throw new Error("Unexpected request " + path);
  });
  vi.stubGlobal("fetch", request);
  render(<SessionBoundary><DatasetImportPanel /></SessionBoundary>);
  await screen.findByText(user.nombre_completo);
  fireEvent.click(screen.getByRole("button", { name: "Importar dataset" }));
  const dialog = await screen.findByRole("dialog");
  const start = within(dialog).getByRole("button", { name: "Importar dataset" }) as HTMLButtonElement;
  await waitFor(() => expect(start.disabled).toBe(false));
  fireEvent.click(start);
  expect(await screen.findByLabelText("Archivo ZIP")).toBeDefined();
  expect(request.mock.calls.some(([path]) => path.endsWith("/limits"))).toBe(true);
});


it("loads export collections using the same confirmed cookie outside development mode", async () => {
  const request = vi.fn(async (path: string) => {
    if (path.endsWith("/api/auth/me")) return Response.json(user);
    if (path.endsWith("/access")) return Response.json({ development_mode: false });
    if (path.endsWith("/datasets")) return Response.json({ datasets: [], total: 0, next_cursor: null, snapshot: "empty" });
    throw new Error("Unexpected request " + path);
  });
  vi.stubGlobal("fetch", request);
  render(<SessionBoundary><DatasetExportDialog /></SessionBoundary>);
  await screen.findByText(user.nombre_completo);
  fireEvent.click(screen.getByRole("button", { name: "Descargar versión como ZIP" }));
  expect(await screen.findByRole("button", { name: "Primera página de datasets" })).toBeDefined();
  expect(request.mock.calls.some(([path]) => path.endsWith("/datasets"))).toBe(true);
});
