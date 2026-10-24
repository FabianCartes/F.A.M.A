"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { InstallationError, installationState, installationStatus, saveInstallation, checkInstallation, completeInstallation,
  type InstallationState, type InstallationChecks } from "@/lib/installation";
import "@/components/account/management.css";
import "./installation.css";

const steps = ["Requisitos", "PostgreSQL", "Google Cloud Storage", "Comprobaciones", "Administrador"];
const labels = { database: "Conexión PostgreSQL", storage: "Lectura del bucket GCS", schema: "Esquema de la base",
  permissions: "Permisos de la cuenta SQL", configuration: "Configuración de acceso", first_admin: "Primera cuenta de administración" };
const details: Record<string, string> = {
  database_connected: "Conexión confirmada con el usuario de aplicación.",
  database_runtime_permissions_ready: "La cuenta puede operar datos y conserva la versión de migraciones en solo lectura.",
  database_runtime_permissions_invalid: "La cuenta necesita permisos de lectura y escritura sin administrar la estructura. El responsable debe revisar sus permisos.",
  storage_read_connected: "El equipo puede listar los objetos del bucket.",
  schema_current: "Las migraciones y la estructura son compatibles.",
  schema_empty: "Faltan las migraciones. El responsable debe aplicarlas antes de continuar.",
  schema_outdated: "El responsable debe actualizar las migraciones de la base.",
  schema_incompatible: "La estructura de la base requiere revisión del responsable.",
  database_authentication_failed: "PostgreSQL rechazó el usuario o la contraseña.",
  database_unavailable: "No se pudo consultar PostgreSQL. Revisa la conexión preparada en el equipo.",
  storage_forbidden: "La identidad del equipo no tiene permiso para leer este bucket.",
  storage_bucket_not_found: "No se encontró el bucket indicado.",
  storage_credentials_missing: "El responsable debe preparar la autenticación de Google Cloud en el equipo.",
  storage_authentication_failed: "No se pudieron renovar las credenciales de Google Cloud.",
  configuration_ready: "Las claves y opciones de acceso están preparadas.",
  configuration_invalid: "La configuración de acceso necesita revisión del responsable.",
  configuration_incomplete: "Todavía faltan opciones del equipo por configurar.",
  initial_administrator_available: "La base está disponible para la primera cuenta.",
  initial_administrator_resume_pending: "Hay una finalización que se puede reanudar.",
  database_already_initialized: "La base ya contiene datos. Este asistente no reemplaza cuentas existentes.",
};

type Mode = "loading" | "authorize" | "authorized" | "closed" | "error" | "finished";
export default function InstallationPage() {
  const [mode, setMode] = useState<Mode>("loading");
  const [revision, setRevision] = useState(0);
  const [code, setCode] = useState("");
  const [node, setNode] = useState<InstallationState | null>(null);
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({ project_id: "", bucket_name: "", database: "", database_user: "" });
  const [sqlPassword, setSqlPassword] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [report, setReport] = useState<InstallationChecks | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const request = useRef<AbortController | null>(null);
  const proof = useRef("");

  useEffect(() => {
    const controller = new AbortController(); request.current = controller;
    void installationStatus(controller.signal).then((status) => {
      if (!controller.signal.aborted) setMode(status === "required" ? "authorize" : status === "unavailable" ? "error" : "closed");
    }).catch(() => { if (!controller.signal.aborted) setMode("error"); });
    return () => { controller.abort(); request.current?.abort(); proof.current = ""; };
  }, [revision]);

  function accept(state: InstallationState) {
    setNode(state);
    const c = state.configuration;
    setForm({ project_id: c.project_id, bucket_name: c.bucket_name, database: c.database, database_user: c.database_user });
  }

  async function execute(task: (signal: AbortSignal) => Promise<void>, recover = false) {
    if (working.current) return;
    working.current = true; setBusy(true); setError("");
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    try { await task(controller.signal); }
    catch (reason) {
      if (controller.signal.aborted) return;
      setError(reason instanceof InstallationError ? reason.message : "No se pudo conectar con el equipo. Reintenta la operación.");
      if (reason instanceof InstallationError && (reason.status === 401 || reason.status === 410)) {
        proof.current = ""; setNode(null); setCode(""); setSqlPassword(""); setPassword(""); setConfirmation("");
        setMode(reason.status === 401 ? "authorize" : "closed");
      } else if (recover) {
        try {
          const state = await installationState(proof.current, controller.signal);
          if (!controller.signal.aborted) { accept(state); if (state.resume_pending) setStep(4); }
        } catch (failure) {
          if (!controller.signal.aborted && failure instanceof InstallationError && failure.status === 410) { proof.current = ""; setMode("closed"); }
        }
      }
    } finally { working.current = false; if (!controller.signal.aborted) setBusy(false); }
  }

  function authorize(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = code.trim(); setCode("");
    void execute(async (signal) => {
      const state = await installationState(token, signal);
      if (!signal.aborted) { proof.current = token; accept(state); setStep(state.resume_pending ? 4 : 0); setMode("authorized"); }
    });
  }

  function saveDatabase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const secret = sqlPassword; setSqlPassword(""); setReport(null);
    void execute(async (signal) => {
      await saveInstallation(proof.current, { project_id: form.project_id, database: form.database,
        database_user: form.database_user, database_password: secret }, signal);
      const state = await installationState(proof.current, signal);
      if (!signal.aborted) { accept(state); setStep(2); }
    });
  }

  function saveBucket(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setReport(null);
    void execute(async (signal) => {
      await saveInstallation(proof.current, { project_id: form.project_id, bucket_name: form.bucket_name }, signal);
      const state = await installationState(proof.current, signal);
      if (!signal.aborted) { accept(state); setStep(3); }
    });
  }

  function verify() {
    setReport(null);
    void execute(async (signal) => {
      const result = await checkInstallation(proof.current, signal);
      if (!signal.aborted) setReport(result);
    });
  }

  function finish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!node?.resume_pending && (password !== confirmation || !password.trim() || password.length < 12)) {
      setError(password !== confirmation ? "Las contraseñas no coinciden." : "La contraseña debe tener al menos 12 caracteres."); return;
    }
    const administrator: { name: string; email: string; password: string } | Record<string, never> =
      node?.resume_pending ? {} : { name: name.trim(), email: email.trim(), password };
    setPassword(""); setConfirmation("");
    void execute(async (signal) => {
      await completeInstallation(proof.current, administrator, signal);
      if (!signal.aborted) { proof.current = ""; setMode("finished"); }
    }, true);
  }

  function back(target: number) { setError(""); setSqlPassword(""); setPassword(""); setConfirmation(""); setStep(target); }

  return <main className="installation-page management"><div className="installation-container">
    <header className="management-page-header"><div className="management-page-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7Z" /><path d="m8 12 3 3 5-6" /></svg></div><div>
      <h1>Primera instalación</h1><p>Prepara F.A.M.A. para tu equipo de investigación.</p>
    </div></header>
    <div className={mode === "authorized" ? "installation-workspace" : ""}>
      {mode === "authorized" && <nav className="installation-steps" aria-label="Etapas de instalación"><ol>{steps.map((label, index) =>
        <li key={label} aria-current={index === step ? "step" : undefined} data-done={index < step}><span>{index < step ? "✓" : index + 1}</span>{label}</li>)}</ol>
        <p>Los recursos se guardan en el equipo. Las contraseñas no se muestran al volver a abrir el asistente.</p></nav>}
      <section className="management-card installation-card" aria-busy={busy}>
        {mode === "loading" && <p role="status">Comprobando instalación…</p>}
        {mode === "error" && <><p role="alert">No se pudo comprobar el estado del equipo. Revisa el servicio antes de continuar.</p><button onClick={() => { setMode("loading"); setRevision((value) => value + 1); }}>Reintentar comprobación</button></>}
        {mode === "closed" && <><h2>Instalación cerrada</h2><p>Este equipo ya está configurado. Utiliza el acceso habitual. Si acaba de finalizar, el responsable debe reiniciar el servicio del backend.</p><Link href="/login">Ir al inicio de sesión</Link></>}
        {mode === "finished" && <><div className="installation-success" aria-hidden="true">✓</div><h2>Instalación finalizada</h2><p>La configuración y la cuenta de administración quedaron guardadas.</p><p>El responsable del equipo debe reiniciar el servicio del backend para habilitar el acceso. Después podrás iniciar sesión con la cuenta que acabas de crear.</p><Link href="/login">Ir al inicio de sesión</Link></>}
        {mode === "authorize" && <><h2>Autoriza este equipo</h2><p>Introduce el código temporal generado por el responsable del equipo. Caduca a los 15 minutos.</p>
          <form className="management-form" onSubmit={authorize}><label htmlFor="installation-code">Código de autorización</label>
            <input id="installation-code" type="password" autoComplete="off" value={code} maxLength={128} required disabled={busy} onChange={(event) => setCode(event.target.value)} />
            {error && <p role="alert">{error}</p>}<button className="management-primary" disabled={busy} type="submit">{busy ? "Autorizando…" : "Autorizar instalación"}</button>
          </form></>}
        {mode === "authorized" && node && <>
          <p className="installation-eyebrow">PASO {step + 1} DE {steps.length}</p>
          {step === 0 && <><h2>Requisitos del equipo</h2><p>Este asistente utiliza una instancia PostgreSQL y un bucket existentes. El responsable prepara la conexión, autenticación y migraciones antes de continuar.</p>
            <ul className="installation-requirements"><li><strong>Conexión del equipo</strong><span>{node.configuration.connection_name || "Proxy PostgreSQL preparado por el responsable"}</span></li>
              <li><strong>Google Cloud</strong><span>{node.configuration.credentials_prepared ? "Archivo de autenticación preparado en el servidor." : "La autenticación disponible en el equipo se comprobará con GCS."}</span></li>
              <li><strong>Base de datos y permisos</strong><span>Se comprobarán las migraciones y que la base esté disponible para la primera cuenta.</span></li></ul>
            <div className="management-actions"><button className="management-primary" onClick={() => back(1)}>Continuar a PostgreSQL</button></div></>}
          {step === 1 && <><h2>Conexión PostgreSQL</h2><p>Introduce la base y el usuario diario de la aplicación. La instancia y el proxy son los preparados en el equipo.</p>
            <div className="installation-connection">{node.configuration.connection_name || "Conexión del nodo"}<span>{node.configuration.proxy_host}:{node.configuration.proxy_port}</span></div>
            <form className="management-form" onSubmit={saveDatabase}>
              <label htmlFor="installation-project">ID del proyecto de Google Cloud</label><input id="installation-project" required maxLength={63} disabled={busy} value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })} />
              <div className="installation-fields"><div><label htmlFor="installation-database">Base de datos</label><input id="installation-database" required maxLength={63} disabled={busy} value={form.database} onChange={(e) => setForm({ ...form, database: e.target.value })} /></div>
                <div><label htmlFor="installation-sql-user">Usuario de aplicación</label><input id="installation-sql-user" required maxLength={63} disabled={busy} value={form.database_user} onChange={(e) => setForm({ ...form, database_user: e.target.value })} /></div></div>
              <label htmlFor="installation-sql-password">Contraseña PostgreSQL</label><input id="installation-sql-password" type="password" autoComplete="off" required={!node.configuration.password_saved} maxLength={1024} disabled={busy} value={sqlPassword} onChange={(e) => setSqlPassword(e.target.value)} />
              <p>{node.configuration.password_saved ? "Deja este campo vacío para conservar la contraseña guardada." : "Se guardará de forma privada en el equipo."}</p>
              <div className="management-actions"><button type="button" disabled={busy} onClick={() => back(0)}>Volver</button><button type="submit" disabled={busy} className="management-primary">{busy ? "Guardando…" : "Guardar conexión PostgreSQL"}</button></div>
            </form></>}
          {step === 2 && <><h2>Google Cloud Storage</h2><p>Indica el bucket de esta instalación, sin el prefijo gs://. La autenticación la gestiona el equipo.</p><p>Proyecto: <strong>{form.project_id}</strong></p>
            <form className="management-form" onSubmit={saveBucket}><label htmlFor="installation-bucket">Nombre del bucket</label><input id="installation-bucket" required maxLength={222} disabled={busy} value={form.bucket_name} onChange={(e) => setForm({ ...form, bucket_name: e.target.value })} />
              <div className="management-actions"><button type="button" disabled={busy} onClick={() => back(1)}>Volver</button><button type="submit" disabled={busy} className="management-primary">{busy ? "Guardando…" : "Guardar bucket"}</button></div>
            </form></>}
          {step === 3 && <><h2>Comprobaciones del equipo</h2><p>Comprueba las conexiones y migraciones antes de crear la primera cuenta. Este paso consulta los servicios sin crear tablas ni subir archivos.</p>
            {report && <ul className="installation-checks">{(Object.keys(labels) as (keyof typeof labels)[]).map((key) => <li key={key} data-ok={report.checks[key].ok}>
              <span aria-hidden="true">{report.checks[key].ok ? "✓" : "!"}</span><div><strong>{labels[key]}</strong><p>{details[report.checks[key].code] ?? "No se pudo completar esta comprobación. Revisa el servicio y su configuración."}</p></div>
              <small>{report.checks[key].ok ? "Correcto" : "Revisar"}</small></li>)}</ul>}
            <div className="management-actions"><button disabled={busy} onClick={() => back(2)}>Volver</button><button className="management-primary" disabled={busy} onClick={verify}>{busy ? "Comprobando…" : "Comprobar servicios"}</button>
              {report?.ready && <button className="management-primary" disabled={busy} onClick={() => back(4)}>Continuar al administrador</button>}</div></>}
          {step === 4 && <><h2>{node.resume_pending ? "Reanudar finalización" : "Primer administrador"}</h2><p>{node.resume_pending ? "La finalización anterior quedó pendiente. Se conservarán la cuenta y contraseña originales, sin crear otra cuenta." : "Esta cuenta administrará los usuarios y recursos. Utiliza un correo y una contraseña que puedas conservar."}</p>
            <form className="management-form" onSubmit={finish}>
              {!node.resume_pending && <><label htmlFor="installation-admin-name">Nombre del administrador</label><input id="installation-admin-name" autoComplete="name" required maxLength={150} disabled={busy} value={name} onChange={(e) => setName(e.target.value)} />
                <label htmlFor="installation-admin-email">Correo del administrador</label><input id="installation-admin-email" type="email" autoComplete="username" required maxLength={150} disabled={busy} value={email} onChange={(e) => setEmail(e.target.value)} />
                <label htmlFor="installation-admin-password">Contraseña del administrador</label><input id="installation-admin-password" type="password" autoComplete="new-password" minLength={12} maxLength={1024} required disabled={busy} value={password} onChange={(e) => setPassword(e.target.value)} />
                <label htmlFor="installation-confirm">Confirmar contraseña</label><input id="installation-confirm" type="password" autoComplete="new-password" minLength={12} maxLength={1024} required disabled={busy} value={confirmation} onChange={(e) => setConfirmation(e.target.value)} />
                <p>Usa al menos 12 caracteres. La contraseña se borra del formulario al enviarla.</p></>}
              <div className="management-actions">{!node.resume_pending && <button type="button" disabled={busy} onClick={() => back(3)}>Volver</button>}
                <button className="management-primary" type="submit" disabled={busy}>{busy ? "Finalizando…" : node.resume_pending ? "Reanudar finalización" : "Finalizar instalación"}</button></div>
            </form></>}
          {error && <p className="installation-error" role="alert">{error}</p>}
        </>}
      </section>
    </div>
    <p className="installation-footer">F.A.M.A. · Configuración del equipo de investigación</p>
  </div></main>;
}
