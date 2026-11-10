import { apiFetch, API_BASE_URL } from "@/lib/api";
import { z } from "zod";

const userSchema = z.object({ id: z.number().int().positive(), email: z.string(), nombre_completo: z.string(),
  rol: z.enum(["administrador", "investigador"]), activo: z.boolean() });
export type AccountUser = z.infer<typeof userSchema>;
const userPageSchema = z.object({ users: z.array(userSchema), total: z.number().int().nonnegative(), limit: z.number().int().positive(), offset: z.number().int().nonnegative() });

export class AccountApiError extends Error {
  constructor(message: string, public status = 0, public retryAfter = 0) { super(message); }
}

async function send(path: string, options?: RequestInit): Promise<Response> {
  let response: Response;
  try { response = await apiFetch(`${API_BASE_URL}/api/${path}`, options); }
  catch { throw new AccountApiError("No se pudo confirmar la operación. Actualiza el estado antes de reintentar."); }
  if (!response.ok) {
    const messages: Record<number, string> = {
      400: "Revisa los datos enviados. La operación no se completó.",
      401: "La sesión expiró. Vuelve a iniciar sesión.",
      403: "No tienes permiso para realizar esta operación.",
      404: "El recurso ya no existe o no está disponible.",
      409: "La operación entra en conflicto con el estado actual. Actualiza los datos antes de reintentar.",
      422: "Los datos enviados no son válidos.",
      429: "Demasiados intentos. Espera antes de volver a intentarlo.",
      503: "El servicio no está disponible. No se pudo confirmar la operación.",
    };
    const retry = response.headers.get("Retry-After") ?? "";
    throw new AccountApiError(messages[response.status] ?? "No se pudo confirmar la operación. Actualiza el estado antes de reintentar.",
      response.status, response.status === 429 ? (/^\d+$/.test(retry) ? Math.min(86400, Math.max(1, Number(retry))) : 60) : 0);
  }
  return response;
}

function body(method: string, value?: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: value === undefined ? undefined : JSON.stringify(value) };
}

async function decode<T>(response: Response, schema: z.ZodType<T>): Promise<T> {
  try { return schema.parse(await response.json()); }
  catch { throw new AccountApiError("La respuesta del servidor no es válida. Actualiza el estado antes de continuar."); }
}

export async function listAccounts(offset: number, signal?: AbortSignal) {
  return decode(await send(`users?limit=20&offset=${offset}`, { signal }), userPageSchema);
}

export async function createAccount(value: { nombre_completo: string; email: string; password: string; rol: AccountUser["rol"] }, signal?: AbortSignal) {
  return decode(await send("auth/register", { ...body("POST", value), signal }), userSchema);
}

export async function updateAccount(id: number, changes: Pick<AccountUser, "nombre_completo" | "rol" | "activo">, signal?: AbortSignal) {
  try {
    return await decode(await send(`users/${id}`, { ...body("PATCH", changes), signal }), userSchema);
  } catch (error) {
    if (error instanceof AccountApiError && error.status === 409) throw new AccountApiError("Debe conservarse al menos un administrador activo. No se modificó la cuenta.", 409);
    throw error;
  }
}

export async function issueRecovery(id: number, signal?: AbortSignal) {
  let response: Response;
  try { response = await send(`users/${id}/password-reset`, { ...body("POST"), signal }); }
  catch (error) {
    if (error instanceof AccountApiError && error.status === 409) throw new AccountApiError("La recuperación requiere una cuenta activa. Actualiza su estado antes de reintentar.", 409);
    throw error;
  }
  const result = await decode(response, z.object({ reset_url: z.string(), expires_in: z.number().int().positive().max(900) }));
  try {
    const target = new URL(result.reset_url);
    if (target.origin !== window.location.origin || target.pathname !== "/reset-password" || target.search || target.username || target.password || !/^#token=[A-Za-z0-9_-]{43}$/.test(target.hash)) throw new Error();
  } catch {
    throw new AccountApiError("El servidor no devolvió un enlace de recuperación válido para esta aplicación.");
  }
  return result;
}

const assignmentPageSchema = z.object({ user_id: z.number().int().positive(),
  datasets: z.array(z.object({ dataset_id: z.number().int().positive(), name: z.string(), assigned: z.boolean() })),
  total: z.number().int().nonnegative(), limit: z.number().int().positive(), offset: z.number().int().nonnegative() });

export async function listAssignments(userId: number, offset: number, signal?: AbortSignal) {
  const page = await decode(await send(`access/users/${userId}/datasets?limit=20&offset=${offset}`, { signal }), assignmentPageSchema);
  if (page.user_id !== userId) throw new AccountApiError("La respuesta no corresponde a la cuenta seleccionada.");
  return page;
}

export async function setAssignment(userId: number, datasetId: number, assigned: boolean, signal?: AbortSignal) {
  const response = await send(`access/users/${userId}/datasets/${datasetId}`, { method: assigned ? "PUT" : "DELETE", signal });
  if (!assigned) {
    if (response.status !== 204) throw new AccountApiError("No se pudo confirmar la revocación.");
    return;
  }
  const value = await decode(response, z.object({ user_id: z.number(), dataset_id: z.number(), assigned: z.literal(true) }));
  if (value.user_id !== userId || value.dataset_id !== datasetId) throw new AccountApiError("No se pudo confirmar la asignación solicitada.");
}

const auditPageSchema = z.object({ events: z.array(z.object({ id: z.number().int().positive(), occurred_at: z.number(),
  action: z.string(), outcome: z.enum(["success", "denied"]), actor_id: z.number().int().nullable(),
  subject_user_id: z.number().int().nullable(), dataset_id: z.number().int().nullable() })), next_before_id: z.number().int().positive().nullable() });

export async function listAudit(beforeId: number | null, signal?: AbortSignal) {
  return decode(await send(`security/audit?limit=50${beforeId === null ? "" : `&before_id=${beforeId}`}`, { signal }), auditPageSchema);
}

export async function cleanupSecurity(batchSize: number, signal?: AbortSignal) {
  return decode(await send("security/cleanup", { ...body("POST", { batch_size: batchSize }), signal }), z.object({
    batch_size: z.number().int().positive().max(1000), has_more: z.boolean(),
    deleted: z.object({ sessions: z.number().int().nonnegative(), recoveries: z.number().int().nonnegative(),
      quotas: z.number().int().nonnegative(), audit: z.number().int().nonnegative() }),
  }));
}

export async function changePassword(currentPassword: string, newPassword: string, signal?: AbortSignal) {
  try {
    const response = await send("auth/change-password", { ...body("POST", { current_password: currentPassword, new_password: newPassword }), signal });
    if (response.status !== 204) throw new AccountApiError("No se pudo confirmar el cambio de contraseña.");
  } catch (error) {
    if (error instanceof AccountApiError && error.status === 400) throw new AccountApiError("La contraseña actual es incorrecta.", 400);
    throw error;
  }
}
