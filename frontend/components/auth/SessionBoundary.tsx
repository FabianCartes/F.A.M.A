"use client";

// Keep session confirmation and owner generations centralized for the workspace.
import { createContext, useContext, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { AuthError, currentUser, signIn, signOut, type SessionUser } from "@/lib/auth";
import { onUnauthorized, confirmApiSession } from "@/lib/api";
import LoginForm from "./LoginForm";
import AuthSurface from "./AuthSurface";
import "./auth.css";

type Session = { user: SessionUser | null; message: string; busy: boolean; logoutFailed?: boolean };
const WebSession = createContext<SessionUser | null>(null);
export function useOptionalWebSession() { return useContext(WebSession); }
const WebSessionLogout = createContext<(() => void) | null>(null);
export function useOptionalWebSessionLogout() { return useContext(WebSessionLogout); }

export default function SessionBoundary({ children, mode = "workspace" }: {
  children?: ReactNode; mode?: "workspace" | "login";
}) {
  const router = useRouter();
  const [session, setSession] = useState<Session>({ user: null, message: "", busy: true });
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const logoutPending = useRef(false);
  const confirmedOwner = useRef<number | null>(null);

  const invalidate = useCallback(() => {
    // A private 401 cannot confirm logout revocation or discard its retry context.
    if (logoutPending.current) return;
    generation.current += 1;
    controller.current?.abort();
    confirmedOwner.current = null;
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
        // Revalidating the same owner is not a new session generation: private
        // views must retain their state while their catalogue refreshes.
        const owner = user?.id ?? null;
        if (confirmedOwner.current !== owner) confirmApiSession();
        confirmedOwner.current = owner;
        setSession({ user, message: "", busy: false });
      }
    } catch (reason) {
      if (!request.signal.aborted && version === generation.current) {
        confirmedOwner.current = null;
        setSession({ user: null, busy: false,
          message: reason instanceof AuthError ? reason.message : "No se pudo comprobar la sesión. Revisa la conexión e inténtalo de nuevo." });
      }
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
    if (mode === "workspace" && !session.busy && !session.user && !session.message) router.replace("/login");
  }, [session.user, session.busy, session.message, router, mode]);

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
    confirmedOwner.current = user.id;
    setSession({ user, message: "", busy: false });
  }

  async function logout() {
    const version = ++generation.current;
    controller.current?.abort();
    const request = new AbortController(); controller.current = request;
    logoutPending.current = true;
    // Unmount private state immediately, even if server revocation fails.
    confirmedOwner.current = null;
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

  if (session.message) return <AuthSurface><h1>Acceso a F.A.M.A.</h1><p role="alert">{session.message}</p>
    <button className="auth-submit" onClick={() => {
      if (session.logoutFailed) void logout(); else void check();
    }}>{session.logoutFailed ? "Reintentar cierre de sesión" : "Reintentar comprobación"}</button></AuthSurface>;

  if (mode === "login") {
    if (!session.busy && !session.user) return <LoginForm onLogin={login} />;
    return <AuthSurface><p role="status">{session.user ? "Abriendo aplicación…" : "Comprobando sesión…"}</p></AuthSurface>;
  }

  if (session.busy || !session.user) return <AuthSurface><p role="status">{session.busy ? "Comprobando sesión…" : "Abriendo acceso…"}</p></AuthSurface>;

  return <WebSession.Provider value={session.user}><WebSessionLogout.Provider value={() => void logout()}><div className="session-workspace">
    <div className="session-content" key={session.user.id}>{children}</div>
  </div></WebSessionLogout.Provider></WebSession.Provider>;
}
