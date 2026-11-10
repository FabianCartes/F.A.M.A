"use client";

import { useEffect, useRef, useState } from "react";
import { listAssignments, setAssignment, type AccountUser } from "@/lib/api/accountApi";

export default function AssignmentPanel({ person }: { person: AccountUser }) {
  const globalAccess = person.rol === "administrador";
  const [page, setPage] = useState<Awaited<ReturnType<typeof listAssignments>> | null>(null);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const mutation = useRef<AbortController | null>(null);
  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    listAssignments(person.id, offset, controller.signal).then((result) => { if (!controller.signal.aborted) setPage(result); })
      .catch((reason) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [person.id, offset, revision]);
  function reload(next = offset) { setPage(null); setError(""); setOffset(next); setRevision((value) => value + 1); }
  async function change(datasetId: number, assigned: boolean) {
    if (busy || globalAccess) return;
    setBusy(true); setError(""); setNotice("");
    const controller = new AbortController(); mutation.current = controller;
    try {
      await setAssignment(person.id, datasetId, assigned, controller.signal);
      if (!controller.signal.aborted) { setNotice(assigned ? "Acceso concedido. Comprobando asignaciones…" : "Acceso revocado. Comprobando asignaciones…"); reload(); }
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "No se pudo confirmar el acceso."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section aria-label="Asignaciones de datasets"><div className="account-section-heading"><div><h3>Acceso a datasets</h3><p>Un dataset reúne audios y los modelos y predicciones vinculados a ellos.</p></div><button type="button" className="management-quiet" disabled={busy} onClick={() => { setNotice(""); reload(); }}>Actualizar asignaciones</button></div>
    {globalAccess ? <div className="account-note"><strong>Acceso global por rol</strong><p>Esta persona es administradora y tiene acceso a todos los datasets. Las asignaciones individuales se utilizan para cuentas con rol Investigador.</p></div>
      : <p className="account-note">Elige los datasets que podrá utilizar esta persona. Cada botón aplica el permiso de inmediato, sin guardar el perfil.</p>}
    {!person.activo && <p className="account-note account-note-warning">La cuenta está suspendida. Podrá utilizar sus permisos cuando se reactive.</p>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!page && !error && <p role="status">Cargando asignaciones…</p>}
    {page && <><ul className="account-dataset-list" aria-label="Datasets registrados">
      {page.datasets.map((dataset) => <li key={dataset.dataset_id} className="account-dataset" data-access={globalAccess || dataset.assigned}>
        <div className="account-dataset-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v7c0 4 16 4 16 0V5M4 12v7c0 4 16 4 16 0v-7" /></svg></div>
        <div className="account-dataset-description"><strong>{dataset.name}</strong><span className={`account-access-state ${globalAccess || dataset.assigned ? "account-access-allowed" : ""}`}>{globalAccess ? "Permitido por rol Administrador" : dataset.assigned ? "Acceso permitido" : "Sin acceso asignado"}</span></div>
        {!globalAccess && <button type="button" className={dataset.assigned ? "management-quiet" : "management-primary"} disabled={busy} aria-label={`${dataset.assigned ? "Revocar" : "Conceder"} acceso a ${dataset.name}`} onClick={() => void change(dataset.dataset_id, !dataset.assigned)}>{dataset.assigned ? "Revocar acceso" : "Conceder acceso"}</button>}
      </li>)}
    </ul>{page.datasets.length === 0 && <p>No hay datasets registrados en esta página.</p>}
    <div className="management-actions"><button type="button" disabled={busy || offset === 0} onClick={() => reload(Math.max(0, offset - 20))}>Datasets anteriores</button><span>{page.total} datasets</span><button type="button" disabled={busy || offset + page.datasets.length >= page.total} onClick={() => reload(offset + 20)}>Datasets siguientes</button></div></>}
  </section>;
}
