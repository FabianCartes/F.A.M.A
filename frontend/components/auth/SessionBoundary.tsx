"use client";

import { createContext, useContext, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { AuthError, currentUser, signIn, signOut, type SessionUser } from "@/lib/auth";
import { confirmApiSession, onUnauthorized } from "@/lib/api";
import { installationStatus } from "@/lib/installation";
import LoginForm from "./LoginForm";
import AuthSurface from "./AuthSurface";
import "./auth.css";

type Session = { status: "checking" | "anonymous" | "logging-out" | "installation" } |
  { status: "authenticated"; user: SessionUser } | { status: "error"; message: string; logout?: boolean };

const WebSession = createContext<{ user: SessionUser; refreshSession: () => Promise<void> } | null>(null);

export function useWebSession() {
  const session = useContext(WebSession);
  if (!session) throw new Error("Se requiere una sesión web confirmada.");
  return session;
}

export default function SessionBoundary({ children, mode = "protected" }: { children?: ReactNode; mode?: "protected" | "login" }) {
  const router = useRouter();
  const [session, setSession] = useState<Session>({ status: "checking" });
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const invalidate = useCallback(() => {
    generation.current += 1;
    controller.current?.abort();
    setSession({ status: "anonymous" });
  }, []);

  const check = useCallback(async () => {
    const version = ++generation.current;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    try {
      const user = await currentUser(request.signal);
      if (request.signal.aborted || version !== generation.current) return;
      if (user) confirmApiSession();
      setSession(user ? { status: "authenticated", user } : { status: "anonymous" });
    } catch (reason) {
      if (reason instanceof AuthError && reason.status === 503 && !request.signal.aborted && version === generation.current) {
        try {
          const status = await installationStatus(request.signal);
          if (request.signal.aborted || version !== generation.current) return;
          if (status === "required") { setSession({ status: "installation" }); return; }
        } catch { /* La falta de confirmación conserva el acceso bloqueado. */ }
      }
      if (!request.signal.aborted && version === generation.current) setSession({
        status: "error", message: reason instanceof AuthError ? reason.message : "No se pudo comprobar la sesión. Revisa la conexión e inténtalo de nuevo.",
      });
    }
  }, []);

  useEffect(() => {
    const unsubscribe = onUnauthorized(invalidate);
    let active = true;
    queueMicrotask(() => { if (active) void check(); });
    return () => { active = false; unsubscribe(); generation.current += 1; controller.current?.abort(); };
  }, [check, invalidate]);

  useEffect(() => {
    if (session.status !== "authenticated") return;
    const recheck = () => {
      // A file picker also restores focus. Keep the already-verified workspace
      // mounted while rechecking; negative/error results still close it.
      if (!document.hidden) void check();
    };
    window.addEventListener("focus", recheck);
    document.addEventListener("visibilitychange", recheck);
    return () => {
      window.removeEventListener("focus", recheck);
      document.removeEventListener("visibilitychange", recheck);
    };
  }, [session.status, check]);

  useEffect(() => {
    if (session.status === "installation") router.replace("/installation");
    if (session.status === "anonymous" && mode === "protected") router.replace("/login");
    if (session.status === "authenticated" && mode === "login") router.replace("/");
  }, [session.status, router, mode]);

  async function login(email: string, password: string) {
    const version = ++generation.current;
    const request = new AbortController();
    controller.current?.abort(); controller.current = request;
    const expected = await signIn(email, password, request.signal);
    const user = await currentUser(request.signal);
    if (request.signal.aborted || version !== generation.current) return;
    if (!user) throw new AuthError("No se pudo confirmar la cookie de sesión. Revisa HTTPS y la configuración del servidor.");
    if (user.id !== expected.id) throw new AuthError("La sesión cambió durante el acceso. Vuelve a iniciar sesión para confirmar tu cuenta.");
    confirmApiSession();
    setSession({ status: "authenticated", user });
  }

  async function logout() {
    const version = ++generation.current;
    controller.current?.abort();
    const request = new AbortController(); controller.current = request;
    setSession({ status: "logging-out" });
    try {
      await signOut(request.signal);
      if (version === generation.current && !request.signal.aborted) invalidate();
    } catch {
      if (version === generation.current && !request.signal.aborted) setSession({ status: "error", logout: true,
        message: "No se pudo confirmar el cierre de sesión en el servidor. Reintenta; no se ha confirmado la revocación." });
    }
  }

  if (session.status === "anonymous" && mode === "login") return <LoginForm onLogin={login} />;
  if (session.status === "authenticated" && mode === "protected") return <WebSession.Provider value={{ user: session.user, refreshSession: check }}><div className="session-workspace">
    <div className="session-toolbar" aria-label="Sesión actual">
      <span>{session.user.nombre_completo || session.user.email} <small>· {session.user.rol === "administrador" ? "Administrador" : "Investigador"}</small></span>
      <button type="button" onClick={() => void logout()}>Cerrar sesión</button>
    </div>
    <div className="session-content" key={session.user.id}>{children}</div>
  </div></WebSession.Provider>;
  if (session.status === "error") {
    const content = <div className="max-w-md space-y-4 text-center">
      <p role="alert">{session.message}</p>
      <button type="button" className="auth-submit px-6" onClick={() => {
        if (session.logout) void logout(); else { setSession({ status: "checking" }); void check(); }
      }}>{session.logout ? "Reintentar cierre de sesión" : "Reintentar comprobación"}</button>
    </div>;
    return mode === "login" ? <AuthSurface><h1>Acceso a F.A.M.A.</h1><div className="mt-6">{content}</div></AuthSurface> :
      <main className="min-h-dvh grid place-items-center bg-gray-950 text-gray-200 p-6">{content}</main>;
  }
  return <main className="min-h-dvh grid place-items-center bg-gray-950 text-gray-200 p-6">
    <p role="status">{session.status === "checking" ? "Comprobando sesión…" :
      session.status === "logging-out" ? "Cerrando sesión…" : session.status === "installation" ? "Abriendo configuración del equipo…" : session.status === "authenticated" ? "Abriendo aplicación…" : "Inicia sesión para continuar…"}</p>
  </main>;
}
