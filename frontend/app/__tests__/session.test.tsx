import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import Home from "../page";
import SessionBoundary from "@/components/auth/SessionBoundary";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));

describe("protected home", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("checks the session before mounting views or making data/ML requests", async () => {
    const request = vi.fn<(url: string, options?: RequestInit) => Promise<Response>>(() => new Promise<Response>(() => {}));
    vi.stubGlobal("fetch", request);
    render(<Home />);
    await waitFor(() => expect(request).toHaveBeenCalled());
    expect(request.mock.calls.map((call) => String(call[0]))).toEqual(["/api/auth/me"]);
    expect(screen.queryByRole("button", { name: /Ejecutar inferencia/ })).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Comprobando sesión");
  });

  it("redirects anonymous users without fetching application data", async () => {
    const request = vi.fn(async () => new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", request);
    render(<Home />);
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("clears the application when a data request reports an expired session", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/auth/me") ? new Response(JSON.stringify({
      id: 2, email: "researcher@example.test", nombre_completo: "Investigadora", rol: "investigador", activo: true,
    })) : new Response(null, { status: 401 })));
    render(<Home />);
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByRole("button", { name: "Cerrar sesión" })).toBeNull();
  });

  it("waits for server logout confirmation and does not cancel training", async () => {
    let finishLogout!: (response: Response) => void;
    const request = vi.fn(async (url: string) => {
      if (url.endsWith("/auth/me")) return new Response(JSON.stringify({
        id: 2, email: "researcher@example.test", nombre_completo: "Investigadora", rol: "investigador", activo: true,
      }));
      if (url.endsWith("/auth/logout")) return new Promise<Response>((resolve) => { finishLogout = resolve; });
      return new Response(JSON.stringify({ models: [], triad_status: [] }));
    });
    vi.stubGlobal("fetch", request);
    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name: "Cerrar sesión" }));
    expect(navigation.replace).not.toHaveBeenCalled();
    await waitFor(() => expect(finishLogout).toBeDefined());
    finishLogout(new Response(null, { status: 204 }));
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
    expect(request.mock.calls.some(([url]) => url.includes("/training/stop"))).toBe(false);
  });

  it("does not mistake a forbidden dataset for a missing session", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/auth/me") ? new Response(JSON.stringify({
      id: 2, email: "researcher@example.test", nombre_completo: "Investigadora", rol: "investigador", activo: true,
    })) : new Response(null, { status: 403 })));
    render(<Home />);
    expect(await screen.findByRole("button", { name: "Cerrar sesión" })).toBeDefined();
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("ignores an old request's late 401 after a new session verification", async () => {
    let oldRequest!: (response: Response) => void;
    let models = 0;
    const request = vi.fn(async (url: string) => {
      if (url.endsWith("/auth/me")) return new Response(JSON.stringify({
        id: 2, email: "researcher@example.test", nombre_completo: "Investigadora", rol: "investigador", activo: true,
      }));
      if (url.endsWith("/api/models") && ++models === 1) return new Promise<Response>((resolve) => { oldRequest = resolve; });
      return new Response(JSON.stringify({ models: [], triad_status: [] }));
    });
    vi.stubGlobal("fetch", request);
    render(<Home />);
    await screen.findByRole("button", { name: "Cerrar sesión" });
    fireEvent.focus(window);
    await waitFor(() => expect(request.mock.calls.filter(([url]) => url.endsWith("/auth/me"))).toHaveLength(2));
    await screen.findByRole("button", { name: "Cerrar sesión" });
    oldRequest(new Response(null, { status: 401 }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Cerrar sesión" })).toBeDefined());
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("preserves current work during a focus recheck and discards it only if the verified identity changes", async () => {
    let finishCheck!: (response: Response) => void;
    let calls = 0;
    const user = { id: 2, email: "researcher@example.test", nombre_completo: "Investigadora", rol: "investigador", activo: true };
    vi.stubGlobal("fetch", vi.fn(async () => ++calls === 1 ? new Response(JSON.stringify(user)) :
      new Promise<Response>((resolve) => { finishCheck = resolve; })));
    render(<SessionBoundary><input aria-label="Trabajo en curso" /></SessionBoundary>);
    const draft = await screen.findByLabelText("Trabajo en curso");
    fireEvent.change(draft, { target: { value: "Trabajo no enviado" } });
    fireEvent.focus(window);
    expect(screen.getByLabelText("Trabajo en curso")).toBe(draft);
    expect((draft as HTMLInputElement).value).toBe("Trabajo no enviado");
    await waitFor(() => expect(finishCheck).toBeDefined());
    finishCheck(new Response(JSON.stringify({ ...user, id: 3, nombre_completo: "Otra persona" })));
    await waitFor(() => expect(screen.getByLabelText("Trabajo en curso")).not.toBe(draft));
    expect((screen.getByLabelText("Trabajo en curso") as HTMLInputElement).value).toBe("");
  });
});
