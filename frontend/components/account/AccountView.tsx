"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useWebSession } from "@/components/auth/SessionBoundary";
import { changePassword } from "@/lib/api/accountApi";
import { listCatalogue, type CataloguePage } from "@/lib/api/datasetAccessApi";
import { SkeletonRows } from "@/components/common/Skeleton";
import "./management.css";

export function initialsOf(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";
}

/** Visual guidance only: the 12-character rule is still enforced on submit. */
function passwordStrength(value: string) {
  if (!value) return { score: 0, label: "Escribe una contraseña nueva" };
  if (value.length < 12) return { score: 1, label: "Muy corta: mínimo 12 caracteres" };
  let score = 1;
  if (/[a-z]/.test(value) && /[A-Z]/.test(value)) score++;
  if (/\d/.test(value)) score++;
  if (/[^A-Za-z0-9]/.test(value) || value.length >= 20) score++;
  return { score, label: ["", "Aceptable", "Aceptable", "Buena", "Fuerte"][score] };
}

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

  const role = user.rol === "administrador" ? "Administrador" : "Investigador";
  const strength = passwordStrength(password);

  return <div className="management">
    <header className="account-hero">
      <span className="account-hero-avatar" aria-hidden="true">{initialsOf(user.nombre_completo)}</span>
      <div className="account-hero-text">
        <h1 className="management-eyebrow">Mi cuenta</h1>
        <p className="account-hero-name">{user.nombre_completo}</p>
        <p>{user.email} · Consulta tu identidad y actualiza tu contraseña de acceso.</p>
      </div>
      <div className="account-badges"><span className="account-badge">{role}</span><span className="account-badge account-badge-active">Cuenta activa</span></div>
    </header>
    <div className="management-grid">
      <section className="management-card" aria-labelledby="account-identity"><h2 id="account-identity"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="8" cy="10" r="2" /><path d="M5 16a3 3 0 0 1 6 0m3-6h4m-4 4h4" /></svg>Identidad</h2>
        <p>El nombre, el correo y el rol los gestiona un administrador.</p>
        <dl className="account-identity-tiles"><div><dt>Nombre</dt><dd>{user.nombre_completo}</dd></div><div><dt>Correo electrónico</dt><dd>{user.email}</dd></div><div><dt>Rol</dt><dd><span className="account-badge">{role}</span></dd></div></dl>
      </section>
      <section className="management-card" aria-labelledby="account-password"><h2 id="account-password"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V6a4 4 0 0 1 8 0v4m-4 5v2" /></svg>Cambiar contraseña</h2>
        <p>Usa entre 12 y 1024 caracteres para la nueva contraseña.</p>
        <form onSubmit={submit} className="management-form">
          <label htmlFor="account-current">Contraseña actual</label><input id="account-current" type="password" autoComplete="current-password" required maxLength={1024} disabled={busy} value={current} onChange={(e) => setCurrent(e.target.value)} />
          <label htmlFor="account-new">Nueva contraseña</label><input id="account-new" type="password" autoComplete="new-password" required minLength={12} maxLength={1024} disabled={busy} value={password} onChange={(e) => setPassword(e.target.value)} />
          <div className="password-meter" aria-hidden="true" data-score={strength.score}><span /><span /><span /><span /></div>
          <p className="password-meter-label" data-score={strength.score}>{strength.label}</p>
          <label htmlFor="account-confirm">Confirmar nueva contraseña</label><input id="account-confirm" type="password" autoComplete="new-password" required minLength={12} maxLength={1024} disabled={busy} value={confirmation} onChange={(e) => setConfirmation(e.target.value)} />
          <p className="account-note account-note-warning">Al cambiarla se cerrarán todas tus sesiones. Deberás iniciar sesión nuevamente.</p>
          {error && <p role="alert">{error}</p>}<button type="submit" className="management-primary" disabled={busy}>{busy ? "Actualizando…" : "Cambiar contraseña"}</button>
        </form>
      </section>
    </div>
    <MyDatasets administrator={user.rol === "administrador"} />
  </div>;
}

/** Read-only summary of the datasets this person holds or asked for; requests live in Gestión de audios. */
function MyDatasets({ administrator }: { administrator: boolean }) {
  const [page, setPage] = useState<CataloguePage | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (administrator) return;
    const controller = new AbortController();
    listCatalogue(0, controller.signal).then((value) => { if (!controller.signal.aborted) setPage(value); })
      .catch((reason) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "No se pudo consultar el catálogo."); });
    return () => controller.abort();
  }, [administrator]);
  const mine = page?.datasets.filter((item) => item.assigned || item.request_status === "pending" || item.request_status === "rejected") ?? [];
  return <section className="management-card account-datasets" aria-labelledby="account-datasets"><h2 id="account-datasets"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v7c0 4 16 4 16 0V5M4 12v7c0 4 16 4 16 0v-7" /></svg>Mis datasets</h2>
    <p>Definen qué audios y modelos puedes usar. Para solicitar acceso a otro dataset, abre el catálogo en Gestión de audios.</p>
    {administrator ? <p className="account-note"><strong>Acceso global por rol.</strong> Como administrador puedes usar todos los datasets registrados.</p>
      : error ? <p className="account-note account-note-warning">{error}</p>
      : !page ? <SkeletonRows rows={2} className="mt-3" />
      : mine.length === 0 ? <p className="account-note">Aún no tienes datasets asignados ni solicitudes en curso.</p>
      : <ul className="account-dataset-list">{mine.map((item) => <li key={item.dataset_id} className="account-dataset">
          <div className="account-dataset-description"><strong>{item.name}</strong><span className="account-access-state">{item.audio_count} audios · {item.purpose}</span></div>
          <span className={`account-badge ${item.assigned ? "account-badge-active" : item.request_status === "pending" ? "account-badge-suspended" : "account-badge-rejected"}`}>
            {item.assigned ? "Asignado" : item.request_status === "pending" ? "Solicitud pendiente" : "Solicitud rechazada"}
          </span>
        </li>)}</ul>}
  </section>;
}
