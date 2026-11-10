"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import AuthSurface from "@/components/auth/AuthSurface";
import { AuthError, resetPassword } from "@/lib/auth";
import { useRetryAfter } from "@/components/auth/useRetryAfter";

export default function ResetPasswordPage() {
  const token = useRef<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const [stage, setStage] = useState<"loading" | "ready" | "invalid" | "done">("loading");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [cooldown, setCooldown] = useRetryAfter();

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      const parameters = new URLSearchParams(window.location.hash.slice(1));
      const candidate = parameters.get("token");
      window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
      if (parameters.getAll("token").length === 1 && candidate && /^[A-Za-z0-9_-]{43}$/.test(candidate)) {
        token.current = candidate; setStage("ready");
      } else setStage("invalid");
    });
    return () => { active = false; controller.current?.abort(); };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || cooldown > 0 || !token.current) return;
    if (password !== confirmation) { setError("Las contraseñas no coinciden."); return; }
    if (password.length < 12 || password.length > 1024 || !password.trim()) {
      setError("Usa una contraseña de entre 12 y 1024 caracteres, no vacía."); return;
    }
    const secret = password;
    setPassword(""); setConfirmation(""); setError(""); setBusy(true);
    const request = new AbortController(); controller.current = request;
    try {
      await resetPassword(token.current, secret, request.signal);
      if (!request.signal.aborted) { token.current = null; setStage("done"); }
    } catch (reason) {
      if (!request.signal.aborted) {
        setError(reason instanceof AuthError ? reason.message : "No se pudo confirmar el cambio. Revisa la conexión antes de reintentar.");
        if (reason instanceof AuthError && reason.status === 429) setCooldown(reason.retryAfter);
      }
    } finally { if (!request.signal.aborted) setBusy(false); }
  }

  return <AuthSurface>
    <h1>Recuperar acceso</h1>
    {stage === "loading" && <p role="status" className="auth-description">Preparando recuperación…</p>}
    {stage === "invalid" && <p role="alert" className="auth-error">Enlace de recuperación inválido o incompleto. Solicita uno nuevo al administrador.</p>}
    {stage === "done" && <p role="status" className="auth-description">Contraseña actualizada. Inicia sesión para continuar.</p>}
    {stage === "ready" && <>
      <p className="auth-description">Define una nueva contraseña para tu cuenta.</p>
      <form className="auth-form" onSubmit={submit}>
        <label htmlFor="reset-password">Nueva contraseña</label>
        <input id="reset-password" type="password" autoComplete="new-password" required minLength={12} maxLength={1024} disabled={busy} value={password} onChange={(e) => setPassword(e.target.value)} />
        <label htmlFor="reset-confirm">Confirmar contraseña</label>
        <input id="reset-confirm" type="password" autoComplete="new-password" required minLength={12} maxLength={1024} disabled={busy} value={confirmation} onChange={(e) => setConfirmation(e.target.value)} />
        {error && <p role="alert" className="auth-error">{error}{cooldown > 0 && ` Espera ${cooldown} segundos.`}</p>}
        <button className="auth-submit" type="submit" disabled={busy || cooldown > 0}>{busy ? "Actualizando…" : "Actualizar contraseña"}</button>
      </form>
    </>}
    <p className="auth-help"><a href="/login">Volver al inicio de sesión</a></p>
  </AuthSurface>;
}
