import { afterAll, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.hoisted(() => { vi.stubEnv("NEXT_PUBLIC_API_URL", "https://foreign.example.test"); });
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

import Home from "../page";
afterAll(() => vi.unstubAllEnvs());

it("does not transmit credentials or mount views with a cross-origin API configuration", async () => {
  const request = vi.fn(); vi.stubGlobal("fetch", request);
  render(<Home />);
  expect(await screen.findByRole("alert")).toBeDefined();
  expect(request).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: /Ejecutar inferencia/ })).toBeNull();
});
