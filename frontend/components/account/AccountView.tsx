"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useWebSession } from "@/components/auth/SessionBoundary";
import { changePassword } from "@/lib/api/accountApi";
import "./management.css";

export default function AccountView() {
  const { user, refreshSession } = useWebSession();
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (password !== confirmation) { setError("Las contraseñas no coinciden."); return; }
    if (!password.trim() || password.length < 12 || password.length > 1024) { setError("Usa entre 12 y 1024 caracteres para la nueva contraseña."); return; }
    const previous = current, next = password;
    setCurrent(""); setPassword(""); setConfirmation(""); setError(""); setBusy(true);
    const controller = new AbortController(); request.current = controller;
    try {
      await changePassword(previous, next, controller.signal);
      if (!controller.signal.aborted) await refreshSession();
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "No se pudo confirmar el cambio."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }

  return <div className="management">
    <header className="management-page-header"><div className="management-page-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="4" /><path d="M5 21v-2a7 7 0 0 1 14 0v2" /></svg></div><div><h1>Mi cuenta</h1><p>Consulta tu identidad y actualiza tu contraseña de acceso.</p></div></header>
    <div className="management-grid">
      <section className="management-card" aria-labelledby="account-identity"><h2 id="account-identity"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="8" cy="10" r="2" /><path d="M5 16a3 3 0 0 1 6 0m3-6h4m-4 4h4" /></svg>Identidad</h2>
        <dl className="account-identity"><div><dt>Nombre</dt><dd>{user.nombre_completo}</dd></div><div><dt>Correo electrónico</dt><dd>{user.email}</dd></div><div><dt>Rol</dt><dd><span className="account-badge">{user.rol === "administrador" ? "Administrador" : "Investigador"}</span></dd></div></dl>
      </section>
      <section className="management-card" aria-labelledby="account-password"><h2 id="account-password"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V6a4 4 0 0 1 8 0v4m-4 5v2" /></svg>Cambiar contraseña</h2>
        <p>Al cambiarla se cerrarán todas tus sesiones. Deberás iniciar sesión nuevamente.</p>
        <form onSubmit={submit} className="management-form">
          <label htmlFor="account-current">Contraseña actual</label><input id="account-current" type="password" autoComplete="current-password" required maxLength={1024} disabled={busy} value={current} onChange={(e) => setCurrent(e.target.value)} />
          <label htmlFor="account-new">Nueva contraseña</label><input id="account-new" type="password" autoComplete="new-password" required minLength={12} maxLength={1024} disabled={busy} value={password} onChange={(e) => setPassword(e.target.value)} />
          <label htmlFor="account-confirm">Confirmar nueva contraseña</label><input id="account-confirm" type="password" autoComplete="new-password" required minLength={12} maxLength={1024} disabled={busy} value={confirmation} onChange={(e) => setConfirmation(e.target.value)} />
          {error && <p role="alert">{error}</p>}<button type="submit" className="management-primary" disabled={busy}>{busy ? "Actualizando…" : "Cambiar contraseña"}</button>
        </form>
      </section>
    </div>
  </div>;
}
