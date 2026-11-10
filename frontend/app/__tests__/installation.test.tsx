import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import InstallationPage from "../installation/page";

const state = {
  status: "required", resume_pending: false,
  configuration: { project_id: "synthetic-project", bucket_name: "synthetic-bucket", connection_name: "synthetic-project:us-central1:instance",
    database: "synthetic_db", database_user: "synthetic_app", proxy_host: "127.0.0.1", proxy_port: 5433,
    password_saved: true, credentials_prepared: true },
};
const checks = { ready: true, checks: {
  database: { ok: true, code: "database_connected" }, storage: { ok: true, code: "storage_read_connected" },
  schema: { ok: true, code: "schema_current", revision: "0002_access" },
  configuration: { ok: true, code: "configuration_ready" }, first_admin: { ok: true, code: "initial_administrator_available" },
  permissions: { ok: true, code: "database_runtime_permissions_ready" },
} };
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear(); });

it("requires the operator code before showing resources and keeps it out of persistent storage", async () => {
  const request = vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith("/status") ? { status: "required" } : state)));
  vi.stubGlobal("fetch", request);
  render(<InstallationPage />);
  const input = await screen.findByLabelText("Código de autorización");
  expect(screen.queryByDisplayValue("synthetic-project")).toBeNull();
  fireEvent.change(input, { target: { value: "a".repeat(43) } });
  fireEvent.click(screen.getByRole("button", { name: "Autorizar instalación" }));
  expect(await screen.findByRole("heading", { name: "Requisitos del equipo" })).toBeDefined();
  await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  expect(request.mock.calls[1][0]).toBe("/api/installation/state");
  expect(localStorage.length + sessionStorage.length).toBe(0);
  expect(window.location.hash).toBe("");
});

async function openWizard() {
  render(<InstallationPage />);
  fireEvent.change(await screen.findByLabelText("Código de autorización"), { target: { value: "a".repeat(43) } });
  fireEvent.click(screen.getByRole("button", { name: "Autorizar instalación" }));
  fireEvent.click(await screen.findByRole("button", { name: "Continuar a PostgreSQL" }));
  fireEvent.click(await screen.findByRole("button", { name: "Guardar conexión PostgreSQL" }));
  fireEvent.click(await screen.findByRole("button", { name: "Guardar bucket" }));
  await screen.findByRole("heading", { name: "Comprobaciones del equipo" });
}

it("walks through existing resources, checks services and clears passwords before finalization", async () => {
  let finish!: (response: Response) => void;
  const request = vi.fn(async (url: string, options?: RequestInit) => {
    expect(options?.cache).toBe("no-store");
    expect(options?.credentials).toBe("same-origin");
    if (url.endsWith("/status")) return new Response(JSON.stringify({ status: "required" }));
    if (url.endsWith("/configuration")) return new Response(JSON.stringify({ code: "installation_configuration_saved" }));
    if (url.endsWith("/check")) return new Response(JSON.stringify(checks));
    if (url.endsWith("/complete")) return new Promise<Response>((resolve) => { finish = resolve; });
    return new Response(JSON.stringify(state));
  });
  vi.stubGlobal("fetch", request);
  await openWizard();
  fireEvent.click(await screen.findByRole("button", { name: "Comprobar servicios" }));
  fireEvent.click(await screen.findByRole("button", { name: "Continuar al administrador" }));
  fireEvent.change(screen.getByLabelText("Nombre del administrador"), { target: { value: "Persona inicial" } });
  fireEvent.change(screen.getByLabelText("Correo del administrador"), { target: { value: "first@example.test" } });
  fireEvent.change(screen.getByLabelText("Contraseña del administrador"), { target: { value: "New-Admin-Password-2026" } });
  fireEvent.change(screen.getByLabelText("Confirmar contraseña"), { target: { value: "New-Admin-Password-2026" } });
  fireEvent.click(screen.getByRole("button", { name: "Finalizar instalación" }));
  expect((screen.getByLabelText("Contraseña del administrador") as HTMLInputElement).value).toBe("");
  await waitFor(() => expect(finish).toBeDefined());
  finish(new Response(JSON.stringify({ code: "installation_completed", restart_required: true })));
  expect(await screen.findByRole("heading", { name: "Instalación finalizada" })).toBeDefined();
  expect(screen.getByText(/reiniciar el servicio/i)).toBeDefined();
  expect(localStorage.length + sessionStorage.length).toBe(0);
});

function server(checkResponse: Response, node = state) {
  return vi.fn(async (url: string) => {
    if (url.endsWith("/status")) return new Response(JSON.stringify({ status: "required" }));
    if (url.endsWith("/configuration")) return new Response(JSON.stringify({ code: "installation_configuration_saved" }));
    if (url.endsWith("/check")) return checkResponse;
    if (url.endsWith("/complete")) return new Response(JSON.stringify({ code: "installation_completed", restart_required: true }));
    return new Response(JSON.stringify(node));
  });
}

it("blocks administrator creation when GCS lacks permission", async () => {
  vi.stubGlobal("fetch", server(new Response(JSON.stringify({ ...checks, ready: false,
    checks: { ...checks.checks, storage: { ok: false, code: "storage_forbidden" } } }))));
  await openWizard();
  fireEvent.click(screen.getByRole("button", { name: "Comprobar servicios" }));
  expect(await screen.findByText(/no tiene permiso para leer/)).toBeDefined();
  expect(screen.queryByRole("button", { name: "Continuar al administrador" })).toBeNull();
});

it("clears private state when the authorization expires, including an empty 401 response", async () => {
  vi.stubGlobal("fetch", server(new Response(null, { status: 401 })));
  await openWizard();
  fireEvent.click(screen.getByRole("button", { name: "Comprobar servicios" }));
  expect(await screen.findByLabelText("Código de autorización")).toBeDefined();
  expect(screen.queryByRole("navigation", { name: "Etapas de instalación" })).toBeNull();
  expect(screen.queryByText("synthetic-project")).toBeNull();
});

it("resumes a pending finalization without collecting a second account or password", async () => {
  const request = server(new Response(JSON.stringify(checks)), { ...state, resume_pending: true });
  vi.stubGlobal("fetch", request);
  render(<InstallationPage />);
  fireEvent.change(await screen.findByLabelText("Código de autorización"), { target: { value: "a".repeat(43) } });
  fireEvent.click(screen.getByRole("button", { name: "Autorizar instalación" }));
  fireEvent.click(await screen.findByRole("button", { name: "Reanudar finalización" }));
  expect(await screen.findByRole("heading", { name: "Instalación finalizada" })).toBeDefined();
  const call = request.mock.calls.find(([url]) => url.endsWith("/complete"));
  expect(call).toBeDefined();
  expect(screen.queryByLabelText("Contraseña del administrador")).toBeNull();
});
