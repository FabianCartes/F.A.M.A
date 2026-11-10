import { z } from "zod";
import { API_BASE_URL } from "@/lib/api";

const userSchema = z.object({
  id: z.number().int().positive(), email: z.string(), nombre_completo: z.string(),
  rol: z.enum(["administrador", "investigador"]), activo: z.literal(true),
});
export type SessionUser = z.infer<typeof userSchema>;

export class AuthError extends Error {
  constructor(message: string, public status = 0, public retryAfter = 0) { super(message); }
}

function responseError(response: Response): AuthError {
  const raw = response.headers.get("Retry-After") ?? "";
  const retry = /^\d+$/.test(raw) ? Math.min(86400, Math.max(1, Number(raw))) : 60;
  const messages: Record<number, string> = {
    401: "Correo o contraseña incorrectos.",
    403: "Solicitud no permitida. Revisa el origen configurado de la aplicación.",
    429: "Demasiados intentos. Espera antes de volver a intentarlo.",
    503: "El servicio de acceso no está disponible o no está configurado. Contacta al administrador.",
  };
  return new AuthError(messages[response.status] ?? "No se pudo completar la solicitud de acceso.",
    response.status, response.status === 429 ? retry : 0);
}

async function post(path: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  const response = await fetch(authUrl(path), {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    credentials: "same-origin", cache: "no-store", redirect: "error", signal,
  });
  if (!response.ok) throw responseError(response);
  return response;
}

export async function signOut(signal?: AbortSignal): Promise<void> {
  const response = await post("logout", undefined, signal);
  if (response.status !== 204) throw new AuthError("No se pudo confirmar el cierre de sesión en el servidor.");
}

export async function resetPassword(token: string, newPassword: string, signal?: AbortSignal): Promise<void> {
  try {
    const response = await post("reset-password", { token, new_password: newPassword }, signal);
    if (response.status !== 204) throw new AuthError("No se pudo confirmar el cambio de contraseña.");
  } catch (reason) {
    if (reason instanceof AuthError && reason.status === 400) {
      throw new AuthError("El enlace de recuperación es inválido, expiró o ya se utilizó. Solicita uno nuevo al administrador.", 400);
    }
    throw reason;
  }
}

export async function signIn(email: string, password: string, signal?: AbortSignal): Promise<SessionUser> {
  const response = await post("login", { email: email.trim(), password }, signal);
  const parsed = userSchema.safeParse((await response.json())?.user);
  if (!parsed.success) throw new AuthError("La respuesta de acceso no es válida.");
  return parsed.data;
}

export function authUrl(path: string): string {
  const base = API_BASE_URL.replace(/\/+$/, "");
  const url = new URL(`${base}/api/auth/${path}`, window.location.origin);
  if (url.origin !== window.location.origin || url.username || url.password || url.search || url.hash) {
    throw new AuthError("La API debe usar el mismo origen de la aplicación. Revisa la configuración del proxy.");
  }
  return `${base}/api/auth/${path}`;
}

export async function currentUser(signal?: AbortSignal): Promise<SessionUser | null> {
  const response = await fetch(authUrl("me"), {
    credentials: "same-origin", cache: "no-store", redirect: "error", signal,
  });
  if (response.status === 401) return null;
  if (!response.ok) throw responseError(response);
  const parsed = userSchema.safeParse(await response.json());
  if (!parsed.success) throw new AuthError("La respuesta de sesión no es válida.");
  return parsed.data;
}
