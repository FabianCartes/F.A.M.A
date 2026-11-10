import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import SessionBoundary from "../SessionBoundary";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));

const user = { id: 2, email: "researcher@example.test", nombre_completo: "Investigadora", rol: "investigador", activo: true };
const json = (data: unknown, status = 200, headers = {}) => new Response(JSON.stringify(data), { status, headers });

describe("login web", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null); });

  it("presents an accessible login without public registration or role selection", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({}, 401)));
    render(<SessionBoundary mode="login">{null}</SessionBoundary>);
    expect(await screen.findByLabelText("Correo electrónico")).toBeDefined();
    expect(screen.getByLabelText("Contraseña").getAttribute("autocomplete")).toBe("current-password");
    expect(screen.getByRole("button", { name: "Iniciar sesión" })).toBeDefined();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("link", { name: /registr/i })).toBeNull();
  });

  it("confirms the cookie after login and only then navigates home", async () => {
    let signedIn = false;
    const request = vi.fn<(url: string, options?: RequestInit) => Promise<Response>>(async (url) => {
      if (url.endsWith("/login")) { signedIn = true; return json({ user }); }
      return signedIn ? json(user) : json({}, 401);
    });
    vi.stubGlobal("fetch", request);
    render(<SessionBoundary mode="login">{null}</SessionBoundary>);
    fireEvent.change(await screen.findByLabelText("Correo electrónico"), { target: { value: user.email } });
    fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: "SyntheticPassword2026!" } });
    fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" }));
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/"));
    const submission = request.mock.calls.find(([url]) => url.endsWith("/login"))!;
    expect(submission[1]?.credentials).toBe("same-origin");
    expect(JSON.parse(String(submission[1]?.body))).toEqual({ email: user.email, password: "SyntheticPassword2026!" });
  });

  it.each([[401, /incorrectos/i], [503, /administrador/i], [429, /Demasiados intentos/i]])("handles HTTP %s without exposing backend messages or retaining passwords", async (status, message) => {
    const request = vi.fn(async (url: string) => url.endsWith("/login") ? json({ detail: "private SQL or credential" }, status as number, { "Retry-After": "2" }) : json({}, 401));
    vi.stubGlobal("fetch", request);
    render(<SessionBoundary mode="login" />);
    fireEvent.change(await screen.findByLabelText("Correo electrónico"), { target: { value: user.email } });
    fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: "SyntheticPassword2026!" } });
    fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(message as RegExp);
    expect(alert.textContent).not.toContain("private SQL");
    expect((screen.getByLabelText("Contraseña") as HTMLInputElement).value).toBe("");
    expect((screen.getByRole("button", { name: "Iniciar sesión" }) as HTMLButtonElement).disabled).toBe(status === 429);
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("keeps the access surface visible but does not offer credentials if session verification fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({}, 503)));
    render(<SessionBoundary mode="login" />);
    expect(await screen.findByRole("alert")).toBeDefined();
    expect(screen.getByRole("region", { name: "Acceso a F.A.M.A." })).toBeDefined();
    expect(screen.queryByLabelText("Contraseña")).toBeNull();
  });

  it("honours Retry-After without automatically resubmitting credentials", async () => {
    const request = vi.fn(async (url: string) => url.endsWith("/login") ? json({}, 429, { "Retry-After": "2" }) : json({}, 401));
    vi.stubGlobal("fetch", request);
    render(<SessionBoundary mode="login" />);
    fireEvent.change(await screen.findByLabelText("Correo electrónico"), { target: { value: user.email } });
    fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: "SyntheticPassword2026!" } });
    vi.useFakeTimers();
    try {
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" })); });
      expect((screen.getByRole("button", { name: "Iniciar sesión" }) as HTMLButtonElement).disabled).toBe(true);
      await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
      expect((screen.getByRole("button", { name: "Iniciar sesión" }) as HTMLButtonElement).disabled).toBe(false);
      expect(request.mock.calls.filter(([url]) => url.endsWith("/login"))).toHaveLength(1);
    } finally { vi.useRealTimers(); }
  });

  it("does not adopt a different account if the cookie confirmation disagrees with login", async () => {
    let attempted = false;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/login")) { attempted = true; return json({ user }); }
      return attempted ? json({ ...user, id: 3 }) : json({}, 401);
    }));
    render(<SessionBoundary mode="login" />);
    fireEvent.change(await screen.findByLabelText("Correo electrónico"), { target: { value: user.email } });
    fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: "SyntheticPassword2026!" } });
    fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" }));
    expect(await screen.findByRole("alert")).toBeDefined();
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("uses elapsed time for Retry-After when a background tab resumes", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/login") ? json({}, 429, { "Retry-After": "2" }) : json({}, 401)));
    render(<SessionBoundary mode="login" />);
    fireEvent.change(await screen.findByLabelText("Correo electrónico"), { target: { value: user.email } });
    fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: "SyntheticPassword2026!" } });
    vi.useFakeTimers();
    try {
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Iniciar sesión" })); });
      vi.setSystemTime(Date.now() + 10000);
      act(() => { fireEvent(document, new Event("visibilitychange")); });
      expect((screen.getByRole("button", { name: "Iniciar sesión" }) as HTMLButtonElement).disabled).toBe(false);
    } finally { vi.useRealTimers(); }
  });
});
