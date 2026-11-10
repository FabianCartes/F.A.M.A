import { z } from "zod";
import { API_BASE_URL, sameOriginUrl } from "@/lib/api";

const status = z.enum(["required", "configured", "completed", "unavailable"]);
const state = z.object({
  status, resume_pending: z.boolean(),
  configuration: z.object({ project_id: z.string(), bucket_name: z.string(), connection_name: z.string(),
    database: z.string(), database_user: z.string(), proxy_host: z.string(), proxy_port: z.number().int().positive(),
    password_saved: z.boolean(), credentials_prepared: z.boolean() }),
});
export type InstallationState = z.infer<typeof state>;

const messages: Record<string, string> = {
  installation_authorization_required: "El código no es válido o ha caducado. Genera uno nuevo en el equipo.",
  installation_origin_forbidden: "El origen web no coincide con el autorizado en el equipo.",
  installation_closed: "La primera instalación ya está cerrada.",
  installation_busy: "Hay otra operación de instalación en curso. Espera y vuelve a intentarlo.",
  database_already_initialized: "La base ya contiene datos. El asistente no puede adoptarla ni reemplazar sus cuentas.",
  installation_resume_required: "Hay una finalización pendiente. Reanúdala para conservar la cuenta original.",
  installation_checks_failed: "Las comprobaciones no están completas. Revisa los servicios antes de finalizar.",
  installation_finalization_pending: "No se pudo confirmar el cierre. Puedes reanudar la finalización de forma segura.",
  installation_project_mismatch: "El proyecto debe coincidir con la instancia preparada en el equipo.",
  installation_request_invalid: "Revisa los datos del formulario.",
  installation_configuration_changed: "La configuración cambió durante la finalización. Requiere revisión del responsable del equipo.",
};

export class InstallationError extends Error {
  constructor(public status: number, public code: string) {
    super(messages[code] ?? "No se pudo completar la operación. Revisa la conexión y vuelve a intentarlo.");
  }
}

async function request(path: string, token?: string, body?: unknown, signal?: AbortSignal) {
  const url = `${API_BASE_URL}/api/installation/${path}`;
  sameOriginUrl(url);
  const target = new URL(url, window.location.origin);
  if (target.search || target.hash) throw new InstallationError(0, "invalid_api_origin");
  const headers: Record<string, string> = {};
  if (token) headers["X-FAMA-Setup-Code"] = token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(url, { method: body === undefined ? "GET" : "POST", headers,
    body: body === undefined ? undefined : JSON.stringify(body), signal,
    credentials: "same-origin", cache: "no-store", redirect: "error" });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const code = z.object({ code: z.string() }).safeParse(data);
    const fallback: Record<number, string> = { 401: "installation_authorization_required", 410: "installation_closed", 403: "installation_origin_forbidden" };
    throw new InstallationError(response.status, code.success ? code.data.code : fallback[response.status] ?? "request_failed");
  }
  return data;
}

export async function installationStatus(signal?: AbortSignal) {
  const parsed = z.object({ status }).safeParse(await request("status", undefined, undefined, signal));
  if (!parsed.success) throw new InstallationError(0, "invalid_response");
  return parsed.data.status;
}

export async function installationState(token: string, signal?: AbortSignal): Promise<InstallationState> {
  const parsed = state.safeParse(await request("state", token, undefined, signal));
  if (!parsed.success) throw new InstallationError(0, "invalid_response");
  return parsed.data;
}

export type InstallationFields = { project_id?: string; bucket_name?: string; database?: string; database_user?: string; database_password?: string };

export async function saveInstallation(token: string, values: InstallationFields, signal?: AbortSignal) {
  const result = await request("configuration", token, values, signal);
  if (!z.object({ code: z.literal("installation_configuration_saved") }).safeParse(result).success) throw new InstallationError(0, "invalid_response");
}

const check = z.object({ ok: z.boolean(), code: z.string(), revision: z.string().nullable().optional() });
const checks = z.object({ ready: z.boolean(), checks: z.object({
  database: check, storage: check, schema: check, configuration: check, first_admin: check, permissions: check,
}) });
export type InstallationChecks = z.infer<typeof checks>;

export async function checkInstallation(token: string, signal?: AbortSignal): Promise<InstallationChecks> {
  const parsed = checks.safeParse(await request("check", token, {}, signal));
  if (!parsed.success || parsed.data.ready !== Object.values(parsed.data.checks).every((value) => value.ok)) throw new InstallationError(0, "invalid_response");
  return parsed.data;
}

export async function completeInstallation(token: string, administrator: { name: string; email: string; password: string } | Record<string, never>, signal?: AbortSignal) {
  const result = await request("complete", token, administrator, signal);
  if (!z.object({ code: z.literal("installation_completed"), restart_required: z.literal(true) }).safeParse(result).success) throw new InstallationError(0, "invalid_response");
}
