"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useWebSession } from "@/components/auth/SessionBoundary";
import { AccountApiError, createAccount, listAccounts, updateAccount, issueRecovery, type AccountUser } from "@/lib/api/accountApi";
import { useRetryAfter } from "@/components/auth/useRetryAfter";
import AssignmentPanel from "./AssignmentPanel";
import SecurityPanel from "./SecurityPanel";
import RequestsPanel from "./RequestsPanel";
import "./management.css";

export default function AdministrationView() {
  const { user } = useWebSession();
  const [section, setSection] = useState<"accounts" | "security" | "requests">("accounts");
  if (user.rol !== "administrador") return null;
  return <div className="management"><header className="management-page-header"><div className="management-page-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="9" cy="7" r="3" /><path d="M3 21v-3a6 6 0 0 1 12 0v3m1-17a3 3 0 0 1 0 6m5 11v-3a6 6 0 0 0-3-5" /></svg></div><div><h1>Administración</h1><p>Gestiona cuentas y recursos de la plataforma.</p></div></header>
    <nav className="management-tabs" aria-label="Secciones administrativas"><button type="button" aria-pressed={section === "accounts"} onClick={() => setSection("accounts")}>Cuentas y asignaciones</button><button type="button" aria-pressed={section === "requests"} onClick={() => setSection("requests")}>Solicitudes de datasets</button><button type="button" aria-pressed={section === "security"} onClick={() => setSection("security")}>Auditoría y mantenimiento</button></nav>
    {section === "accounts" ? <AccountsPanel /> : section === "requests" ? <RequestsPanel /> : <SecurityPanel />}</div>;
}

function AccountsPanel() {
  const { user, refreshSession } = useWebSession();
  const [selected, setSelected] = useState<AccountUser | null>(null);
  const [page, setPage] = useState<Awaited<ReturnType<typeof listAccounts>> | null>(null);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const selectionTrigger = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    listAccounts(offset, controller.signal).then((result) => { if (!controller.signal.aborted) setPage(result); })
      .catch((reason) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [offset, revision]);
  function reload(next = offset) { setError(""); setPage(null); setOffset(next); setRevision((value) => value + 1); }
  return <><div className="management-grid">
    <section className="management-card" aria-labelledby="accounts-list"><h2 id="accounts-list">Cuentas registradas</h2>
      <button type="button" onClick={() => { setSelected(null); setNotice(""); reload(); }}>Actualizar cuentas</button>
      {error && <p role="alert">{error}</p>}{notice && !selected && <p role="status">{notice}</p>}
      {!page && !error && <p role="status">Cargando cuentas…</p>}
      {page && <><div className="management-table"><table><caption className="sr-only">Cuentas registradas</caption><thead><tr><th>Persona</th><th>Rol</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>
        {page.users.map((person) => <tr key={person.id} data-selected={selected?.id === person.id}><td>{person.nombre_completo}<br /><span>{person.email}</span></td><td>{person.rol === "administrador" ? "Administrador" : "Investigador"}</td><td>{person.activo ? "Activa" : "Suspendida"}</td><td><button type="button" aria-label={`Administrar a ${person.nombre_completo}`} aria-pressed={selected?.id === person.id} onClick={(event) => { selectionTrigger.current = event.currentTarget; setSelected(person); setNotice(""); }}>Administrar</button></td></tr>)}
      </tbody></table></div>{page.users.length === 0 && <p>No hay cuentas en esta página.</p>}
        <div className="management-actions"><button type="button" disabled={offset === 0} onClick={() => { setSelected(null); setNotice(""); reload(Math.max(0, offset - 20)); }}>Cuentas anteriores</button><span>{page.total} cuentas</span><button type="button" disabled={offset + page.users.length >= page.total} onClick={() => { setSelected(null); setNotice(""); reload(offset + 20); }}>Cuentas siguientes</button></div></>}
    </section>
    <CreateAccount onCreated={() => { setSelected(null); setNotice("Cuenta creada."); reload(0); }} />
  </div>{selected && <AccountWorkspace key={selected.id} person={selected} notice={notice} onClose={() => { setSelected(null); selectionTrigger.current?.focus(); }} onUpdated={async (updated) => {
    setSelected(updated); setNotice("Cuenta actualizada."); reload();
    if (updated.id === user.id) await refreshSession();
  }} />}</>;
}

function AccountWorkspace({ person, notice, onUpdated, onClose }: { person: AccountUser; notice: string; onUpdated: (person: AccountUser) => Promise<void>; onClose: () => void }) {
  const { user } = useWebSession();
  const [task, setTask] = useState<"profile" | "datasets" | "recovery">("profile");
  const title = useRef<HTMLHeadingElement | null>(null);
  useEffect(() => { title.current?.focus(); }, []);
  return <section className="account-workspace" aria-label={`Administrar a ${person.nombre_completo}`}>
    <header className="account-workspace-header">
      <div className="account-avatar" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="4" /><path d="M5 21v-2a7 7 0 0 1 14 0v2" /></svg></div>
      <div className="account-person"><p className="management-eyebrow">Cuenta seleccionada</p><h2 ref={title} tabIndex={-1}>{person.nombre_completo}</h2><p>{person.email}</p>
        <div className="account-badges"><span className="account-badge">{person.rol === "administrador" ? "Administrador" : "Investigador"}</span><span className={`account-badge ${person.activo ? "account-badge-active" : "account-badge-suspended"}`}>{person.activo ? "Activa" : "Suspendida"}</span>{person.id === user.id && <span className="account-badge">Tu cuenta</span>}</div>
      </div>
      <button type="button" className="management-quiet" onClick={onClose}>Cerrar detalle</button>
    </header>
    <nav className="account-task-nav" aria-label="Opciones de la cuenta">
      <button type="button" aria-pressed={task === "profile"} onClick={() => setTask("profile")}>Perfil y estado</button>
      <button type="button" aria-pressed={task === "datasets"} onClick={() => setTask("datasets")}>Acceso a datasets</button>
      <button type="button" aria-pressed={task === "recovery"} onClick={() => setTask("recovery")}>Recuperar acceso</button>
    </nav>
    <div className="account-task-content">
      {notice && <p className="account-note" role="status">{notice}</p>}
      <div hidden={task !== "profile"}><AccountEditor key={`${person.id}:${person.nombre_completo}:${person.rol}:${person.activo}`} person={person} onUpdated={onUpdated} /></div>
      {task === "datasets" && <AssignmentPanel person={person} />}
      {task === "recovery" && <RecoveryLink person={person} />}
    </div>
  </section>;
}

function AccountEditor({ person, onUpdated }: { person: AccountUser; onUpdated: (person: AccountUser) => Promise<void> }) {
  const [name, setName] = useState(person.nombre_completo);
  const [role, setRole] = useState(person.rol);
  const [active, setActive] = useState(person.activo);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  const dirty = name.trim() !== person.nombre_completo || role !== person.rol || active !== person.activo;
  const changesAccess = role !== person.rol || active !== person.activo;
  function discard() { setName(person.nombre_completo); setRole(person.rol); setActive(person.activo); setError(""); }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy || !dirty) return;
    if (name.trim().length < 2) { setError("Escribe un nombre de al menos dos caracteres."); return; }
    setBusy(true); setError("");
    const controller = new AbortController(); request.current = controller;
    try {
      const result = await updateAccount(person.id, { nombre_completo: name.trim(), rol: role, activo: active }, controller.signal);
      if (!controller.signal.aborted) await onUpdated(result);
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "No se pudo confirmar la modificación."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section aria-labelledby="account-profile-title"><h3 id="account-profile-title">Perfil y estado de la cuenta</h3><p>Actualiza sus datos y decide cómo puede ingresar a la plataforma.</p>
    <form aria-label="Editar cuenta" className="management-form account-profile-form" onSubmit={submit}>
      <div className="account-profile-fields">
        <div className="account-field"><label htmlFor="edit-name">Nombre completo</label><input id="edit-name" required minLength={2} maxLength={150} disabled={busy} value={name} onChange={(e) => setName(e.target.value)} /><p>Así se identifica a la persona dentro de F.A.M.A.</p></div>
        <div className="account-field"><label htmlFor="edit-role">Rol</label><select id="edit-role" aria-describedby="edit-role-hint" disabled={busy} value={role} onChange={(e) => setRole(e.target.value as AccountUser["rol"])}><option value="investigador">Investigador</option><option value="administrador">Administrador</option></select><p id="edit-role-hint">{role === "administrador" ? "Puede administrar cuentas y acceder a todos los datasets." : "Accede a los datasets que le concedas en Acceso a datasets."}</p></div>
      </div>
      <label className="account-state-control"><input type="checkbox" aria-label="Cuenta activa" checked={active} disabled={busy} onChange={(e) => setActive(e.target.checked)} aria-describedby="edit-state-hint" /><span><strong>Cuenta activa</strong><span id="edit-state-hint">{active ? "Permitirá iniciar sesión al guardar." : "Se bloqueará el ingreso al guardar. Sus datos y asignaciones se conservarán."}</span></span></label>
      {changesAccess && <p className="account-note account-note-warning">Al guardar, se cerrarán sus sesiones y se invalidarán sus enlaces de recuperación. Los entrenamientos ya admitidos continúan.</p>}
      {error && <p role="alert">{error}</p>}
      <div className="account-save-bar"><p>{dirty ? "Tienes cambios sin guardar." : "Los datos coinciden con la cuenta guardada."}</p><div className="account-button-group"><button type="button" className="management-quiet" disabled={busy || !dirty} onClick={discard}>Descartar cambios</button><button type="submit" className="management-primary" disabled={busy || !dirty}>{busy ? "Guardando…" : "Guardar cambios"}</button></div></div>
    </form></section>;
}

function RecoveryLink({ person }: { person: AccountUser }) {
  const { user } = useWebSession();
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [cooldown, setCooldown] = useRetryAfter();
  const request = useRef<AbortController | null>(null);
  const expiry = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { request.current?.abort(); if (expiry.current) clearTimeout(expiry.current); }, []);
  async function issue() {
    if (busy || cooldown > 0 || user.id === person.id || !person.activo) return;
    setLink(""); setError(""); setBusy(true);
    if (expiry.current) clearTimeout(expiry.current);
    const controller = new AbortController(); request.current = controller;
    try {
      const result = await issueRecovery(person.id, controller.signal);
      if (!controller.signal.aborted) { setLink(result.reset_url); expiry.current = setTimeout(() => setLink(""), result.expires_in * 1000); }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : "No se pudo confirmar la recuperación.");
        if (reason instanceof AccountApiError && reason.status === 429) setCooldown(reason.retryAfter);
      }
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section aria-label="Recuperación administrada"><h3>Ayudar a recuperar el acceso</h3>
    <p>Úsalo si esta persona olvidó su contraseña. Verifica su identidad antes de generar el enlace.</p>
    <ol className="account-recovery-steps"><li><strong>Genera un enlace</strong><p>Será válido durante 15 minutos y podrá utilizarse una sola vez.</p></li><li><strong>Entrégalo a la persona</strong><p>Copia el enlace y compártelo por un canal seguro. F.A.M.A. no envía un correo automáticamente.</p></li><li><strong>La persona elige su contraseña</strong><p>La contraseña cambia cuando complete el formulario de recuperación.</p></li></ol>
    <p className="account-note account-note-warning">Generar el enlace cierra sus sesiones y reemplaza cualquier enlace de recuperación anterior.</p>
    {user.id === person.id && <p>Para tu propia cuenta utiliza el cambio de contraseña de Mi cuenta.</p>}
    {!person.activo && <p>Reactiva la cuenta antes de emitir una recuperación.</p>}
    <div className="management-actions"><button type="button" className="management-primary" disabled={busy || cooldown > 0 || !person.activo || user.id === person.id} onClick={() => void issue()}>{busy ? "Generando…" : "Generar enlace de recuperación"}</button></div>
    {error && <p role="alert">{error}{cooldown > 0 && ` Espera ${cooldown} segundos.`}</p>}
    {link && <div className="management-form"><label htmlFor="recovery-link">Enlace de recuperación</label><input id="recovery-link" readOnly value={link} autoComplete="off" spellCheck={false} />
      <p>Al salir de esta sección se oculta. Ocultarlo no lo invalida: vence a los 15 minutos, al usarse o al reemplazarlo.</p><button type="button" className="management-quiet" onClick={() => setLink("")}>Ocultar enlace</button></div>}
  </section>;
}

function CreateAccount({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<AccountUser["rol"]>("investigador");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return;
    if (name.trim().length < 2 || !password.trim() || password.length < 12) { setError("Revisa el nombre y utiliza una contraseña de al menos 12 caracteres."); return; }
    const secret = password; setPassword(""); setBusy(true); setError("");
    const controller = new AbortController(); request.current = controller;
    try {
      await createAccount({ nombre_completo: name.trim(), email: email.trim(), password: secret, rol: role }, controller.signal);
      if (!controller.signal.aborted) { setName(""); setEmail(""); setRole("investigador"); onCreated(); }
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "No se pudo confirmar la creación."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className="management-card"><h2>Crear cuenta</h2><p>La contraseña inicial debe entregarse a la persona por un canal seguro.</p>
    <form className="management-form" aria-label="Crear cuenta" onSubmit={submit}>
      <label htmlFor="create-name">Nombre completo</label><input id="create-name" required minLength={2} maxLength={150} disabled={busy} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
      <label htmlFor="create-email">Correo electrónico</label><input id="create-email" type="email" required maxLength={150} disabled={busy} value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
      <label htmlFor="create-password">Contraseña inicial</label><input id="create-password" type="password" required minLength={12} maxLength={1024} disabled={busy} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
      <label htmlFor="create-role">Rol de la nueva cuenta</label><select id="create-role" disabled={busy} value={role} onChange={(e) => setRole(e.target.value as AccountUser["rol"])}><option value="investigador">Investigador</option><option value="administrador">Administrador</option></select>
      {error && <p role="alert">{error}</p>}<button type="submit" className="management-primary" disabled={busy}>{busy ? "Creando…" : "Crear cuenta"}</button>
    </form></section>;
}
