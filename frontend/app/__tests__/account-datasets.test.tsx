import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import Home from "../page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

const researcher = { id: 2, email: "researcher@example.test", nombre_completo: "Investigadora Prueba", rol: "investigador", activo: true };
const administrator = { ...researcher, id: 1, nombre_completo: "Administradora", rol: "administrador" };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
const dataset = (id: number, name: string, assigned: boolean, request_status: "pending" | "approved" | "rejected" | null) =>
  ({ dataset_id: id, name, purpose: "Finalidad", audio_count: 3, size_bytes: 10, assigned, request_status });

beforeEach(() => { vi.clearAllMocks(); });

it("shows a researcher the datasets they hold or requested, read-only", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return json(researcher);
    if (url.includes("/api/datasets/catalogue?")) return json({ total: 3, limit: 20, offset: 0, datasets: [
      dataset(10, "AvesChilenas", true, null), dataset(11, "Motores", false, "pending"), dataset(12, "Sin relación", false, null),
    ] });
    return json({ models: [], triad_status: [] });
  }));
  render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Mi cuenta" }));
  const mine = await screen.findByRole("region", { name: "Mis datasets" });
  expect(await within(mine).findByText("AvesChilenas")).toBeDefined();
  expect(within(mine).getByText("Asignado")).toBeDefined();
  expect(within(mine).getByText("Motores")).toBeDefined();
  expect(within(mine).getByText("Solicitud pendiente")).toBeDefined();
  expect(within(mine).queryByText("Sin relación")).toBeNull();
  expect(within(mine).queryByRole("button")).toBeNull();
});

it("tells an administrator their access comes from the role without querying the catalogue", async () => {
  const request = vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    return json({ models: [], triad_status: [] });
  });
  vi.stubGlobal("fetch", request);
  render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Mi cuenta" }));
  const mine = await screen.findByRole("region", { name: "Mis datasets" });
  expect(within(mine).getByText(/Acceso global por rol/)).toBeDefined();
  expect(request.mock.calls.some(([url]) => String(url).includes("/datasets/catalogue"))).toBe(false);
});
