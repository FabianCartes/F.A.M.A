"use client";

// Adapted from aa53e09: keep its confirmation/generation discipline, but never
// impose that branch's global authentication or installation policy on legacy.
import { createContext, useContext, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AuthError, currentUser, signIn, signOut, type SessionUser } from "@/lib/auth";
import { onUnauthorized, confirmApiSession } from "@/lib/api";
import LoginForm from "./LoginForm";
import AuthSurface from "./AuthSurface";
import "./auth.css";

type Session = { user: SessionUser | null; message: string; busy: boolean; logoutFailed?: boolean };
const WebSession = createContext<SessionUser | null>(null);
export function useOptionalWebSession() { return useContext(WebSession); }

export default function SessionBoundary({ children, mode = "workspace" }: {
  children?: ReactNode; mode?: "workspace" | "login";
}) {
  const router = useRouter();
  const [session, setSession] = useState<Session>({ user: null, message: "", busy: true });
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const logoutPending = useRef(false);

  const invalidate = useCallback(() => {
    generation.current += 1;
    controller.current?.abort();
    setSession({ user: null, message: "", busy: false });
  }, []);

  const check = useCallback(async () => {
    if (logoutPending.current) return;
    const version = ++generation.current;
    controller.current?.abort();
    const request = new AbortController(); controller.current = request;
    try {
      const user = await currentUser(request.signal);
      if (!request.signal.aborted && version === generation.current) {
        confirmApiSession();
        setSession({ user, message: "", busy: false });
      }
    } catch (reason) {
      if (!request.signal.aborted && version === generation.current) setSession({ user: null, busy: false,
        message: reason instanceof AuthError ? reason.message : "No se pudo comprobar la sesión. Revisa la conexión e inténtalo de nuevo." });
    }
  }, []);

  useEffect(() => {
    const unsubscribe = onUnauthorized(invalidate);
    let active = true;
    queueMicrotask(() => { if (active) void check(); });
    const recheck = () => { if (!document.hidden) void check(); };
    window.addEventListener("focus", recheck);
    document.addEventListener("visibilitychange", recheck);
    return () => {
      active = false; unsubscribe(); generation.current += 1; controller.current?.abort();
      window.removeEventListener("focus", recheck);
      document.removeEventListener("visibilitychange", recheck);
    };
  }, [check, invalidate]);

  useEffect(() => {
    if (session.user && mode === "login") router.replace("/");
  }, [session.user, router, mode]);

  async function login(email: string, password: string) {
    const version = ++generation.current;
    controller.current?.abort();
    const request = new AbortController(); controller.current = request;
    const expected = await signIn(email, password, request.signal);
    const user = await currentUser(request.signal);
    if (request.signal.aborted || version !== generation.current) return;
    if (!user) throw new AuthError("No se pudo confirmar la cookie de sesión. Revisa HTTPS y la configuración del servidor.");
    if (user.id !== expected.id) throw new AuthError("La sesión cambió durante el acceso. Vuelve a iniciar sesión para confirmar tu cuenta.");
    confirmApiSession();
    setSession({ user, message: "", busy: false });
  }

  async function logout() {
    const version = ++generation.current;
    controller.current?.abort();
    const request = new AbortController(); controller.current = request;
    logoutPending.current = true;
    // Unmount private state immediately, even if server revocation fails.
    setSession({ user: null, message: "", busy: true });
    try {
      await signOut(request.signal);
      if (version !== generation.current || request.signal.aborted) return;
      logoutPending.current = false;
      invalidate();
    } catch {
      if (version === generation.current && !request.signal.aborted) setSession({ user: null, busy: false,
        logoutFailed: true, message: "No se pudo confirmar el cierre de sesión en el servidor. Reintenta; no se ha confirmado la revocación." });
    }
  }

  if (mode === "login") {
    if (session.message) return <AuthSurface><h1>Acceso a F.A.M.A.</h1><p role="alert">{session.message}</p>
      <button className="auth-submit" onClick={() => void check()}>Reintentar comprobación</button>
      <Link href="/">Continuar con recursos legacy</Link></AuthSurface>;
    if (!session.busy && !session.user) return <LoginForm onLogin={login} />;
    return <AuthSurface><p role="status">{session.user ? "Abriendo aplicación…" : "Comprobando sesión…"}</p></AuthSurface>;
  }

  return <WebSession.Provider value={session.user}><div className="session-workspace">
    <div className="session-toolbar" aria-label="Sesión actual">
      {session.user ? <><span>{session.user.nombre_completo}</span><button onClick={() => void logout()}>Cerrar sesión</button></> :
        <><span>{session.busy ? "Comprobando sesión…" : "Acceso legacy disponible"}</span><Link href="/login">Iniciar sesión</Link></>}
      {session.message && <><span role="alert">{session.message}</span><button onClick={() => {
        if (session.logoutFailed) void logout(); else void check();
      }}>{session.logoutFailed ? "Reintentar cierre de sesión" : "Reintentar comprobación"}</button></>}
    </div>
    <div className="session-content" key={session.user?.id ?? "anonymous"}>{children}</div>
  </div></WebSession.Provider>;
}
