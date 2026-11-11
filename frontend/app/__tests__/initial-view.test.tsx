import { expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import Home from "../page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

const researcher = { id: 2, email: "researcher@example.test", nombre_completo: "Investigadora", rol: "investigador", activo: true };

it("opens the dashboard first when entering or reloading the app", async () => {
  const request = vi.fn(async (url: string) => new Response(JSON.stringify(
    url.endsWith("/auth/me") ? researcher : { models: [], triad_status: [] })));
  vi.stubGlobal("fetch", request);
  render(<Home />);
  await waitFor(() => expect(request.mock.calls.some(([url]) => String(url).endsWith("/api/dashboard/stats"))).toBe(true));
  expect(screen.getByRole("button", { name: "Dashboard" }).getAttribute("aria-current")).toBe("page");
  expect(request.mock.calls.some(([url]) => String(url).includes("/api/models"))).toBe(false);
});
