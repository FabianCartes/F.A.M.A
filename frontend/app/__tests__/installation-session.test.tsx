import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import SessionBoundary from "@/components/auth/SessionBoundary";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
beforeEach(() => vi.clearAllMocks());

it("opens setup when access is blocked by an unfinished installation", async () => {
  const request = vi.fn(async (url: string) => url.endsWith("/auth/me") ? new Response(null, { status: 503 }) :
    new Response(JSON.stringify({ status: "required" })));
  vi.stubGlobal("fetch", request);
  render(<SessionBoundary><p>Recursos privados</p></SessionBoundary>);
  await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/installation"));
  expect(screen.queryByText("Recursos privados")).toBeNull();
  expect(request.mock.calls.map(([url]) => url)).toEqual(["/api/auth/me", "/api/installation/status"]);
});

it("keeps a completed installation closed during a service outage", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/auth/me") ? new Response(null, { status: 503 }) :
    new Response(JSON.stringify({ status: "completed" }))));
  render(<SessionBoundary><p>Recursos privados</p></SessionBoundary>);
  expect(await screen.findByRole("alert")).toBeDefined();
  expect(navigation.replace).not.toHaveBeenCalled();
});
