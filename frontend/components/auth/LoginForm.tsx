"use client";

import { useState, type FormEvent } from "react";
import { AuthError } from "@/lib/auth";
import AuthSurface from "./AuthSurface";
import { useRetryAfter } from "./useRetryAfter";

export default function LoginForm({ onLogin }: { onLogin: (email: string, password: string) => Promise<void> }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [cooldown, setCooldown] = useRetryAfter();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || cooldown > 0) return;
    setBusy(true); setError("");
    const secret = password;
    setPassword("");
    try { await onLogin(email, secret); }
    catch (reason) {
      setError(reason instanceof AuthError ? reason.message : "No se pudo conectar con el servicio de acceso.");
      if (reason instanceof AuthError && reason.status === 429) setCooldown(reason.retryAfter);
    } finally { setBusy(false); }
  }
  return <AuthSurface>
    <h1>Iniciar sesión</h1>
    <p className="auth-description">Accede a tus recursos de investigación.</p>
    <form className="auth-form" onSubmit={submit}>
      <label htmlFor="login-email">Correo electrónico</label>
      <input id="login-email" type="email" autoComplete="username" required maxLength={150} value={email} onChange={(e) => setEmail(e.target.value)} disabled={busy} />
      <label htmlFor="login-password">Contraseña</label>
      <input id="login-password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy} />
      {error && <p role="alert" className="auth-error">{error}{cooldown > 0 && ` Espera ${cooldown} segundos.`}</p>}
      <button className="auth-submit" type="submit" disabled={busy || cooldown > 0}>{busy ? "Verificando…" : "Iniciar sesión"}</button>
    </form>
    <p className="auth-help">¿No puedes acceder?<br />Contacta al administrador para recuperar tu cuenta.<br />Las cuentas son creadas por administradores autorizados.</p>
  </AuthSurface>;
}
