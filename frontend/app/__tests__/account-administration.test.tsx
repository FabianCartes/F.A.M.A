import { beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import Home from "../page";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));

const researcher = { id: 2, email: "researcher@example.test", nombre_completo: "Investigadora", rol: "investigador", activo: true };
const administrator = { ...researcher, id: 1, nombre_completo: "Administradora", rol: "administrador" };
const json = (data: unknown, status = 200, headers = {}) => new Response(JSON.stringify(data), { status, headers });
beforeEach(() => { vi.clearAllMocks(); });

it("keeps the selected person's identity clear while switching tasks without losing profile edits", async () => {
  const request = vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [researcher], total: 1, limit: 20, offset: 0 });
    if (url.includes("/access/users/2/datasets?")) return json({ user_id: 2, datasets: [{ dataset_id: 10, name: "AvesChilenas", assigned: false }], total: 1, limit: 20, offset: 0 });
    return json({ models: [], triad_status: [] });
  });
  vi.stubGlobal("fetch", request); render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Investigadora" }));
  const detail = screen.getByRole("region", { name: "Administrar a Investigadora" });
  expect(within(detail).getByText(researcher.email)).toBeDefined();
  fireEvent.change(within(detail).getByLabelText("Nombre completo"), { target: { value: "Nombre pendiente" } });
  fireEvent.click(within(detail).getByRole("button", { name: "Acceso a datasets" }));
  expect(await within(detail).findByRole("button", { name: "Conceder acceso a AvesChilenas" })).toBeDefined();
  expect(within(detail).queryByRole("form", { name: "Editar cuenta" })).toBeNull();
  fireEvent.click(within(detail).getByRole("button", { name: "Perfil y estado" }));
  expect((within(detail).getByLabelText("Nombre completo") as HTMLInputElement).value).toBe("Nombre pendiente");
  expect(request.mock.calls.some(([url]) => url.endsWith("/api/users/2"))).toBe(false);
  fireEvent.click(within(detail).getByRole("button", { name: "Cerrar detalle" }));
  expect(screen.queryByRole("region", { name: "Administrar a Investigadora" })).toBeNull();
});

it("discards pending profile and access changes without modifying the account", async () => {
  const request = vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [researcher], total: 1, limit: 20, offset: 0 });
    return json({ models: [], triad_status: [] });
  });
  vi.stubGlobal("fetch", request); render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Investigadora" }));
  const form = screen.getByRole("form", { name: "Editar cuenta" });
  expect((within(form).getByRole("button", { name: "Guardar cambios" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(within(form).getByLabelText("Rol"), { target: { value: "administrador" } });
  fireEvent.click(within(form).getByLabelText("Cuenta activa"));
  expect(within(form).getByText(/Al guardar, se cerrarán sus sesiones/)).toBeDefined();
  fireEvent.click(within(form).getByRole("button", { name: "Descartar cambios" }));
  expect((within(form).getByLabelText("Rol") as HTMLSelectElement).value).toBe("investigador");
  expect((within(form).getByLabelText("Cuenta activa") as HTMLInputElement).checked).toBe(true);
  expect(request.mock.calls.some(([url]) => url.endsWith("/api/users/2"))).toBe(false);
});

it("explains global administrator access without offering misleading individual grant controls", async () => {
  const request = vi.fn<(url: string, options?: RequestInit) => Promise<Response>>(async (url) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [administrator], total: 1, limit: 20, offset: 0 });
    if (url.includes("/access/users/1/datasets?")) return json({ user_id: 1, datasets: [{ dataset_id: 10, name: "AvesChilenas", assigned: false }, { dataset_id: 11, name: "Motores", assigned: true }], total: 2, limit: 20, offset: 0 });
    return json({ models: [], triad_status: [] });
  });
  vi.stubGlobal("fetch", request); render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Administradora" }));
  fireEvent.click(screen.getByRole("button", { name: "Acceso a datasets" }));
  const resources = await screen.findByRole("region", { name: "Asignaciones de datasets" });
  expect(await within(resources).findByText("Motores")).toBeDefined();
  expect(within(resources).getByText("Acceso global por rol")).toBeDefined();
  expect(within(resources).queryByRole("button", { name: /Conceder acceso|Revocar acceso/ })).toBeNull();
  expect(request.mock.calls.some(([, options]) => options?.method === "PUT" || options?.method === "DELETE")).toBe(false);
});

it("lets a researcher change their own password and closes the revoked session", async () => {
  let signedIn = true;
  const request = vi.fn<(url: string, options?: RequestInit) => Promise<Response>>(async (url) => {
    if (url.endsWith("/auth/me")) return signedIn ? json(researcher) : json({}, 401);
    if (url.endsWith("/auth/change-password")) { signedIn = false; return new Response(null, { status: 204 }); }
    return json({ models: [], triad_status: [] });
  });
  vi.stubGlobal("fetch", request);
  render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Mi cuenta" }));
  expect(screen.queryByRole("button", { name: "Administración" })).toBeNull();
  fireEvent.change(screen.getByLabelText("Contraseña actual"), { target: { value: "CurrentPassword2026!" } });
  fireEvent.change(screen.getByLabelText("Nueva contraseña"), { target: { value: "NewPassword2026!" } });
  fireEvent.change(screen.getByLabelText("Confirmar nueva contraseña"), { target: { value: "NewPassword2026!" } });
  fireEvent.click(screen.getByRole("button", { name: "Cambiar contraseña" }));
  await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
  const submission = request.mock.calls.find(([url]) => url.endsWith("/auth/change-password"))!;
  expect(JSON.parse(String(submission[1]?.body))).toEqual({ current_password: "CurrentPassword2026!", new_password: "NewPassword2026!" });
  expect(submission[1]).toMatchObject({ credentials: "same-origin", cache: "no-store", redirect: "error" });
  expect(request.mock.calls.some(([url]) => url.includes("/api/users"))).toBe(false);
});

it("lets an administrator list and create accounts without retaining the initial password", async () => {
  const people = [administrator, researcher];
  const request = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: people, total: people.length, limit: 20, offset: 0 });
    if (url.endsWith("/auth/register")) {
      const submitted = JSON.parse(String(options?.body));
      const person = { ...submitted, id: 3, activo: true };
      people.push(person);
      return json(person, 201);
    }
    return json({ models: [], triad_status: [] });
  });
  vi.stubGlobal("fetch", request);
  render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  expect(await screen.findByRole("button", { name: "Administrar a Investigadora" })).toBeDefined();
  const form = screen.getByRole("form", { name: "Crear cuenta" });
  fireEvent.change(within(form).getByLabelText("Nombre completo"), { target: { value: "Nueva persona" } });
  fireEvent.change(within(form).getByLabelText("Correo electrónico"), { target: { value: "new@example.test" } });
  fireEvent.change(within(form).getByLabelText("Contraseña inicial"), { target: { value: "InitialPassword2026!" } });
  fireEvent.click(within(form).getByRole("button", { name: "Crear cuenta" }));
  expect(await screen.findByRole("button", { name: "Administrar a Nueva persona" })).toBeDefined();
  const submission = request.mock.calls.find(([url]) => url.endsWith("/auth/register"))!;
  expect(JSON.parse(String(submission[1]?.body))).toEqual({ nombre_completo: "Nueva persona", email: "new@example.test", password: "InitialPassword2026!", rol: "investigador" });
  expect((within(form).getByLabelText("Contraseña inicial") as HTMLInputElement).value).toBe("");
});

it("edits an existing account through the backend and refreshes its confirmed state", async () => {
  let person = { ...researcher };
  const request = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [person], total: 1, limit: 20, offset: 0 });
    if (url.endsWith("/api/users/2") && options?.method === "PATCH") {
      person = { ...person, ...JSON.parse(String(options.body)) }; return json(person);
    }
    return json({ models: [], triad_status: [] });
  });
  vi.stubGlobal("fetch", request); render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Investigadora" }));
  const form = await screen.findByRole("form", { name: "Editar cuenta" });
  fireEvent.change(within(form).getByLabelText("Nombre completo"), { target: { value: "Nombre actualizado" } });
  fireEvent.change(within(form).getByLabelText("Rol"), { target: { value: "administrador" } });
  fireEvent.click(within(form).getByLabelText("Cuenta activa"));
  fireEvent.click(within(form).getByRole("button", { name: "Guardar cambios" }));
  expect(await screen.findByRole("button", { name: "Administrar a Nombre actualizado" })).toBeDefined();
  expect(within(screen.getByRole("region", { name: "Administrar a Nombre actualizado" })).getByRole("status").textContent).toBe("Cuenta actualizada.");
  const submission = request.mock.calls.find(([url]) => url.endsWith("/api/users/2"))!;
  expect(JSON.parse(String(submission[1]?.body))).toEqual({ nombre_completo: "Nombre actualizado", rol: "administrador", activo: false });
  expect(within(screen.getByRole("table", { name: "Cuentas registradas" })).getByText("Suspendida")).toBeDefined();
});

it("issues a recovery link only after an explicit request and discards it when the account changes", async () => {
  const token = "a".repeat(43), link = `${window.location.origin}/reset-password#token=${token}`;
  const request = vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [administrator, researcher], total: 2, limit: 20, offset: 0 });
    if (url.endsWith("/users/2/password-reset")) return json({ reset_url: link, expires_in: 900 });
    return json({ models: [], triad_status: [] });
  });
  vi.stubGlobal("fetch", request); render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Investigadora" }));
  expect(request.mock.calls.some(([url]) => url.endsWith("/password-reset"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Recuperar acceso" }));
  fireEvent.click(screen.getByRole("button", { name: "Generar enlace de recuperación" }));
  expect((await screen.findByLabelText("Enlace de recuperación") as HTMLInputElement).value).toBe(link);
  expect(window.location.hash).toBe("");
  expect(JSON.stringify(window.localStorage)).not.toContain(token);
  expect(JSON.stringify(window.sessionStorage)).not.toContain(token);
  fireEvent.click(screen.getByRole("button", { name: "Administrar a Administradora" }));
  expect(screen.queryByLabelText("Enlace de recuperación")).toBeNull();
});

it("grants and revokes access using persisted dataset IDs and re-reads the assignment", async () => {
  let assigned = false;
  const request = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [researcher], total: 1, limit: 20, offset: 0 });
    if (url.includes("/access/users/2/datasets?")) return json({ user_id: 2, datasets: [{ dataset_id: 10, name: "AvesChilenas", assigned }], total: 1, limit: 20, offset: 0 });
    if (url.endsWith("/access/users/2/datasets/10")) {
      assigned = options?.method === "PUT";
      return assigned ? json({ user_id: 2, dataset_id: 10, assigned: true }) : new Response(null, { status: 204 });
    }
    return json({ models: [], triad_status: [] });
  });
  vi.stubGlobal("fetch", request); render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Investigadora" }));
  fireEvent.click(screen.getByRole("button", { name: "Acceso a datasets" }));
  fireEvent.click(await screen.findByRole("button", { name: "Conceder acceso a AvesChilenas" }));
  fireEvent.click(await screen.findByRole("button", { name: "Revocar acceso a AvesChilenas" }));
  expect(await screen.findByRole("button", { name: "Conceder acceso a AvesChilenas" })).toBeDefined();
  expect(request.mock.calls.filter(([url]) => url.endsWith("/datasets/10")).map(([, options]) => options?.method)).toEqual(["PUT", "DELETE"]);
  expect(request.mock.calls.filter(([url]) => url.includes("/access/users/2/datasets?")).length).toBe(3);
});

it("paginates the audit and requires an explicit confirmation before bounded maintenance", async () => {
  const request = vi.fn<(url: string, options?: RequestInit) => Promise<Response>>(async (url) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [], total: 0, limit: 20, offset: 0 });
    if (url.includes("/security/audit?")) return url.includes("before_id=7")
      ? json({ events: [{ id: 6, occurred_at: 1792440000, action: "assignment.granted", outcome: "success", actor_id: 1, subject_user_id: 2, dataset_id: 10 }], next_before_id: null })
      : json({ events: [
        { id: 8, occurred_at: 1792440001, action: "account.operator_recovered", outcome: "success", actor_id: null, subject_user_id: 1, dataset_id: null },
        { id: 7, occurred_at: 1792440000, action: "session.login", outcome: "success", actor_id: 1, subject_user_id: 1, dataset_id: null },
      ], next_before_id: 7 });
    if (url.endsWith("/security/cleanup")) return json({ batch_size: 500, deleted: { sessions: 2, recoveries: 1, quotas: 3, audit: 0 }, has_more: true });
    return json({ models: [], triad_status: [] });
  });
  vi.stubGlobal("fetch", request); render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(screen.getByRole("button", { name: "Auditoría y mantenimiento" }));
  expect(await screen.findByText("Inicio de sesión")).toBeDefined();
  expect(screen.getByText("Acceso recuperado por el operador")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Eventos anteriores" }));
  expect(await screen.findByText("Acceso concedido")).toBeDefined();
  expect(request.mock.calls.some(([url]) => url.endsWith("/cleanup"))).toBe(false);
  expect((screen.getByRole("button", { name: "Limpiar expirados" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByLabelText("Confirmo la limpieza de registros vencidos"));
  fireEvent.click(screen.getByRole("button", { name: "Limpiar expirados" }));
  expect(await screen.findByText(/Quedan registros para otra limpieza/)).toBeDefined();
  expect(within(screen.getByRole("table", { name: "Resultado de limpieza" })).getByRole("cell", { name: "Sesiones" })).toBeDefined();
  const submission = request.mock.calls.find(([url]) => url.endsWith("/cleanup"))!;
  expect(JSON.parse(String(submission[1]?.body))).toEqual({ batch_size: 500 });
  expect(request.mock.calls.filter(([url]) => url.endsWith("/cleanup"))).toHaveLength(1);
});

it("discards a recovery capability when the operator refreshes the account catalogue", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [researcher], total: 1, limit: 20, offset: 0 });
    if (url.endsWith("/users/2/password-reset")) return json({ reset_url: `${window.location.origin}/reset-password#token=${"a".repeat(43)}`, expires_in: 900 });
    return json({ models: [], triad_status: [] });
  }));
  render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Investigadora" }));
  fireEvent.click(screen.getByRole("button", { name: "Recuperar acceso" }));
  fireEvent.click(screen.getByRole("button", { name: "Generar enlace de recuperación" }));
  await screen.findByLabelText("Enlace de recuperación");
  fireEvent.click(screen.getByRole("button", { name: "Actualizar cuentas" }));
  expect(screen.queryByLabelText("Enlace de recuperación")).toBeNull();
  expect(screen.queryByRole("form", { name: "Editar cuenta" })).toBeNull();
  await screen.findByRole("button", { name: "Administrar a Investigadora" });
});

it.each([409, 403, 503])("keeps confirmed account state and hides internal errors after HTTP %s", async (status) => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [administrator], total: 1, limit: 20, offset: 0 });
    if (url.endsWith("/api/users/1")) return json({ detail: "private SQL and credential" }, status);
    return json({ models: [], triad_status: [] });
  }));
  render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Administradora" }));
  const form = screen.getByRole("form", { name: "Editar cuenta" });
  fireEvent.click(within(form).getByLabelText("Cuenta activa"));
  fireEvent.click(within(form).getByRole("button", { name: "Guardar cambios" }));
  const error = await within(form).findByRole("alert");
  expect(error.textContent).not.toContain("private SQL");
  if (status === 409) expect(error.textContent).toContain("administrador activo");
  expect(within(screen.getByRole("table", { name: "Cuentas registradas" })).getByText("Activa")).toBeDefined();
  expect(screen.queryByText("Cuenta actualizada.")).toBeNull();
  expect(navigation.replace).not.toHaveBeenCalled();
});

it("rechecks identity after changing the current administrator's own role", async () => {
  let revoked = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return revoked ? json({}, 401) : json(administrator);
    if (url.includes("/api/users?")) return json({ users: [administrator], total: 1, limit: 20, offset: 0 });
    if (url.endsWith("/api/users/1")) { revoked = true; return json({ ...administrator, rol: "investigador" }); }
    return json({ models: [], triad_status: [] });
  }));
  render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Administradora" }));
  const form = screen.getByRole("form", { name: "Editar cuenta" });
  fireEvent.change(within(form).getByLabelText("Rol"), { target: { value: "investigador" } });
  fireEvent.click(within(form).getByRole("button", { name: "Guardar cambios" }));
  await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
  expect(screen.queryByRole("button", { name: "Administración" })).toBeNull();
});

it("does not submit mismatching personal passwords", async () => {
  const request = vi.fn(async (url: string) => url.endsWith("/auth/me") ? json(researcher) : json({ models: [], triad_status: [] }));
  vi.stubGlobal("fetch", request); render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Mi cuenta" }));
  fireEvent.change(screen.getByLabelText("Contraseña actual"), { target: { value: "CurrentPassword2026!" } });
  fireEvent.change(screen.getByLabelText("Nueva contraseña"), { target: { value: "NewPassword2026!" } });
  fireEvent.change(screen.getByLabelText("Confirmar nueva contraseña"), { target: { value: "DifferentPassword!" } });
  fireEvent.click(screen.getByRole("button", { name: "Cambiar contraseña" }));
  expect(screen.getByRole("alert").textContent).toContain("no coinciden");
  expect(request.mock.calls.some(([url]) => url.endsWith("/change-password"))).toBe(false);
});

it("ignores an old account's delayed dataset response after selecting another account", async () => {
  let finish!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [administrator, researcher], total: 2, limit: 20, offset: 0 });
    if (url.includes("/access/users/2/datasets?")) return new Promise<Response>((resolve) => { finish = resolve; });
    if (url.includes("/access/users/1/datasets?")) return json({ user_id: 1, datasets: [], total: 0, limit: 20, offset: 0 });
    return json({ models: [], triad_status: [] });
  }));
  render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Investigadora" }));
  fireEvent.click(screen.getByRole("button", { name: "Acceso a datasets" }));
  await waitFor(() => expect(finish).toBeDefined());
  fireEvent.click(screen.getByRole("button", { name: "Administrar a Administradora" }));
  fireEvent.click(screen.getByRole("button", { name: "Acceso a datasets" }));
  await screen.findByText("No hay datasets registrados en esta página.");
  await act(async () => { finish(json({ user_id: 2, datasets: [{ dataset_id: 10, name: "Respuesta anterior", assigned: true }], total: 1, limit: 20, offset: 0 })); });
  expect(screen.queryByText("Respuesta anterior")).toBeNull();
});

it("honours recovery throttling without reissuing the link automatically", async () => {
  const request = vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [researcher], total: 1, limit: 20, offset: 0 });
    if (url.endsWith("/password-reset")) return json({ detail: "private token" }, 429, { "Retry-After": "60" });
    return json({ models: [], triad_status: [] });
  });
  vi.stubGlobal("fetch", request); render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Investigadora" }));
  fireEvent.click(screen.getByRole("button", { name: "Recuperar acceso" }));
  fireEvent.click(screen.getByRole("button", { name: "Generar enlace de recuperación" }));
  expect(await screen.findByText(/Demasiados intentos/)).toBeDefined();
  const button = screen.getByRole("button", { name: "Generar enlace de recuperación" }) as HTMLButtonElement;
  expect(button.disabled).toBe(true); fireEvent.click(button);
  expect(request.mock.calls.filter(([url]) => url.endsWith("/password-reset"))).toHaveLength(1);
  expect(screen.queryByLabelText("Enlace de recuperación")).toBeNull();
});

it("explains a recovery conflict without confusing it with last-administrator protection", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [researcher], total: 1, limit: 20, offset: 0 });
    if (url.endsWith("/password-reset")) return json({ detail: "private backend data" }, 409);
    return json({ models: [], triad_status: [] });
  }));
  render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Investigadora" }));
  fireEvent.click(screen.getByRole("button", { name: "Recuperar acceso" }));
  fireEvent.click(screen.getByRole("button", { name: "Generar enlace de recuperación" }));
  const error = await within(screen.getByRole("region", { name: "Recuperación administrada" })).findByRole("alert");
  expect(error.textContent).toContain("cuenta activa");
  expect(error.textContent).not.toContain("administrador activo");
});

it.each(["invalid-link", "https://other.example.test/reset-password#token=" + "a".repeat(43)])("rejects an invalid recovery URL without displaying it: %s", async (link) => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return json(administrator);
    if (url.includes("/api/users?")) return json({ users: [researcher], total: 1, limit: 20, offset: 0 });
    if (url.endsWith("/password-reset")) return json({ reset_url: link, expires_in: 900 });
    return json({ models: [], triad_status: [] });
  }));
  render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Administración" }));
  fireEvent.click(await screen.findByRole("button", { name: "Administrar a Investigadora" }));
  fireEvent.click(screen.getByRole("button", { name: "Recuperar acceso" }));
  fireEvent.click(screen.getByRole("button", { name: "Generar enlace de recuperación" }));
  const error = await within(screen.getByRole("region", { name: "Recuperación administrada" })).findByRole("alert");
  expect(error.textContent).toContain("enlace de recuperación válido");
  expect(error.textContent).not.toContain(link);
  expect(screen.queryByLabelText("Enlace de recuperación")).toBeNull();
});
