import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import Home from "../page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/components/shell/AppShell", () => ({ default: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
vi.mock("@/components/Sidebar", () => ({ default: () => null }));
vi.mock("@/components/views/PredictionView", () => ({ default: () => <p>Legacy prediction available</p> }));
vi.mock("@/components/views/DashboardView", () => ({ default: () => null }));
vi.mock("@/components/views/IngestionView", () => ({ default: () => null }));
vi.mock("@/components/views/TrainingView", () => ({ default: () => null }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each([401, 503])("keeps legacy available without a session when /me returns %s", async (status) => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({}, { status })));
  render(<Home />);
  expect(screen.getByText("Legacy prediction available")).toBeDefined();
  expect(await screen.findByRole("link", { name: "Iniciar sesión" })).toBeDefined();
  expect(screen.getByText("Legacy prediction available")).toBeDefined();
});
