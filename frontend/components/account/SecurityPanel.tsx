"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { cleanupSecurity, listAudit } from "@/lib/api/accountApi";

const actions: Record<string, string> = {
  "session.login": "Inicio de sesión", "account.created": "Cuenta creada", "account.name_updated": "Nombre actualizado",
  "account.role_changed": "Rol modificado", "account.suspended": "Cuenta suspendida", "account.reactivated": "Cuenta reactivada",
  "account.recovery_issued": "Recuperación emitida", "account.password_reset": "Contraseña restablecida", "account.password_changed": "Contraseña modificada",
  "account.operator_recovered": "Acceso recuperado por el operador",
  "account.operator_adopted": "Cuenta existente adoptada por el operador",
  "assignment.granted": "Acceso concedido", "assignment.revoked": "Acceso revocado", "security.cleanup": "Limpieza de expirados",
  "dataset.requested": "Acceso solicitado", "dataset.request_approved": "Solicitud de acceso aprobada", "dataset.request_rejected": "Solicitud de acceso rechazada", "dataset.audio_uploaded": "Audios aportados al dataset",
};

export default function SecurityPanel() {
  const [page, setPage] = useState<Awaited<ReturnType<typeof listAudit>> | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    listAudit(cursor, controller.signal).then((result) => { if (!controller.signal.aborted) setPage(result); })
      .catch((reason) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [cursor, revision]);
  function load(next: number | null) { setPage(null); setError(""); setCursor(next); setRevision((value) => value + 1); }
  return <div className="management-grid"><section className="management-card" aria-label="Auditoría de seguridad"><h2>Auditoría de seguridad</h2>
    <p>Eventos de acceso y administración. Las horas se muestran en UTC.</p>
    {error && <p role="alert">{error}</p>}{!page && !error && <p role="status">Cargando auditoría…</p>}
    {page && <><div className="management-table"><table><caption className="sr-only">Eventos de seguridad</caption><thead><tr><th>Fecha UTC</th><th>Evento</th><th>Resultado</th><th>Actor</th><th>Cuenta</th><th>Dataset</th></tr></thead><tbody>
      {page.events.map((event) => <tr key={event.id}><td>{new Date(event.occurred_at * 1000).toLocaleString("es-CL", { timeZone: "UTC" })}</td><td>{actions[event.action] ?? "Evento no reconocido"}</td><td>{event.outcome === "success" ? "Realizado" : "Denegado"}</td><td>{event.actor_id ?? "—"}</td><td>{event.subject_user_id ?? "—"}</td><td>{event.dataset_id ?? "—"}</td></tr>)}
    </tbody></table></div>{page.events.length === 0 && <p>No hay eventos en esta página.</p>}</>}
    <div className="management-actions"><button type="button" onClick={() => load(null)}>Más recientes</button><button type="button" disabled={!page?.next_before_id} onClick={() => load(page!.next_before_id)}>Eventos anteriores</button></div>
  </section><Maintenance onCompleted={() => load(null)} /></div>;
}

function Maintenance({ onCompleted }: { onCompleted: () => void }) {
  const [batch, setBatch] = useState("500");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Awaited<ReturnType<typeof cleanupSecurity>> | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!confirmed || busy) return;
    if (!/^\d+$/.test(batch) || Number(batch) < 1 || Number(batch) > 1000) { setError("El lote debe ser un entero entre 1 y 1000."); return; }
    setBusy(true); setError(""); setResult(null); setConfirmed(false);
    const controller = new AbortController(); request.current = controller;
    try {
      const value = await cleanupSecurity(Number(batch), controller.signal);
      if (!controller.signal.aborted) { setResult(value); onCompleted(); }
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "No se pudo confirmar la limpieza."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className="management-card" aria-label="Mantenimiento de seguridad"><h2>Mantenimiento de seguridad</h2>
    <p>Elimina sesiones, recuperaciones y cuotas vencidas, y eventos que hayan alcanzado la retención configurada. Cada solicitud procesa como máximo el lote indicado por categoría.</p>
    <p>Las cuentas, datasets, audios y modelos se conservan. Si quedan registros vencidos, puedes solicitar otro lote.</p>
    <form className="management-form" onSubmit={submit}>
      <label htmlFor="cleanup-batch">Lote por categoría</label><input id="cleanup-batch" type="number" required min={1} max={1000} step={1} disabled={busy} value={batch} onChange={(e) => setBatch(e.target.value)} />
      <label className="management-inline"><input type="checkbox" checked={confirmed} disabled={busy} onChange={(e) => setConfirmed(e.target.checked)} />Confirmo la limpieza de registros vencidos</label>
      <button type="submit" className="management-danger" disabled={busy || !confirmed}>{busy ? "Limpiando…" : "Limpiar expirados"}</button>
      {error && <p role="alert">{error}</p>}
    </form>
    {result && <><p role="status">Limpieza confirmada. {result.has_more ? "Quedan registros para otra limpieza." : "No quedan registros vencidos en la comprobación realizada."}</p>
      <div className="management-table"><table><caption>Resultado de limpieza</caption><thead><tr><th>Categoría</th><th>Eliminados</th></tr></thead><tbody>
        <tr><td>Sesiones</td><td>{result.deleted.sessions}</td></tr><tr><td>Recuperaciones</td><td>{result.deleted.recoveries}</td></tr><tr><td>Cuotas</td><td>{result.deleted.quotas}</td></tr><tr><td>Auditoría</td><td>{result.deleted.audit}</td></tr>
      </tbody></table></div></>}
  </section>;
}
