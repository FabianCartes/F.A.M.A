import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import Home from "../page";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
vi.mock("@/components/shell/AppShell", () => ({ default: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
vi.mock("@/components/Sidebar", () => ({ default: () => null }));
vi.mock("@/components/views/PredictionView", () => ({ default: () => <p>Legacy prediction available</p> }));
vi.mock("@/components/views/DashboardView", () => ({ default: () => null }));
vi.mock("@/components/views/IngestionView", () => ({ default: () => null }));
vi.mock("@/components/views/TrainingView", () => ({ default: () => null }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("keeps the workspace unmounted and redirects a confirmed anonymous session to login", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({}, { status: 401 })));
  render(<Home />);
  expect(screen.queryByText("Legacy prediction available")).toBeNull();
  await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
  expect(screen.queryByText("Legacy prediction available")).toBeNull();
});

it("keeps a failed check closed with a warning and retry instead of assuming anonymous access", async () => {
  let status = 503;
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({}, { status })));
  render(<Home />);
  expect(screen.queryByText("Legacy prediction available")).toBeNull();
  expect(await screen.findByRole("alert")).toBeDefined();
  expect(screen.getByRole("region", { name: "Acceso a F.A.M.A." })).toBeDefined();
  expect(navigation.replace).not.toHaveBeenCalled();
  status = 401;
  fireEvent.click(screen.getByRole("button", { name: "Reintentar comprobación" }));
  await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
  expect(screen.queryByText("Legacy prediction available")).toBeNull();
});
