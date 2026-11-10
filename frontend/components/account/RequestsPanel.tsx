"use client";
import { useEffect, useRef, useState } from 'react';
import { listRequests, decideRequest, type RequestsPage } from '@/lib/api/datasetAccessApi';

export default function RequestsPanel() {
  const [page, setPage] = useState<RequestsPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [state, setState] = useState('pending');
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const mutation = useRef<AbortController | null>(null);
  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    listRequests(offset, state, controller.signal).then(value => { if (!controller.signal.aborted) { setPage(value); setError(''); } })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [offset, state, revision]);
  function refresh(next = offset) { setPage(null); setError(''); setOffset(next); setRevision(value => value + 1); }
  async function decide(user: number, dataset: number, decision: 'approve' | 'reject') {
    if (mutation.current) return;
    const controller = new AbortController(); mutation.current = controller; setBusy(true); setNotice(''); setError('');
    try {
      const result = await decideRequest(user, dataset, decision, controller.signal);
      if (!controller.signal.aborted) {
        setNotice(decision === 'approve'
          ? result.assigned ? 'Acceso concedido. La solicitud quedó aprobada.' : 'La solicitud ya estaba aprobada, pero la cuenta no tiene una asignación actual. Revisa sus accesos.'
          : result.assigned ? 'Solicitud rechazada. La asignación existente no se ha revocado.' : 'Solicitud rechazada. No se concedió una asignación.');
        refresh(0);
      }
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'No se pudo confirmar la decisión.'); }
    finally { if (!controller.signal.aborted) { mutation.current = null; setBusy(false); } }
  }
  return <section className="management-card" aria-label="Solicitudes de datasets"><h2>Solicitudes de datasets</h2>
    <p>Aprueba para conceder el uso y los aportes autónomos al dataset. Rechazar no concede acceso.</p>
    <div className="management-actions"><label>Estado de solicitudes<select value={state} disabled={busy} onChange={event => { setState(event.target.value); setNotice(''); refresh(0); }}><option value="pending">Pendientes</option><option value="approved">Aprobadas</option><option value="rejected">Rechazadas</option><option value="all">Todas</option></select></label><button disabled={busy} onClick={() => refresh()}>Actualizar solicitudes</button></div>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!page && !error && <p role="status">Cargando solicitudes…</p>}
    {page && <><div className="management-table"><table aria-label="Solicitudes de datasets"><thead><tr><th>Solicitante</th><th>Dataset</th><th>Solicitud</th><th>Decisión</th></tr></thead><tbody>
      {page.requests.map(item => <tr key={`${item.user_id}:${item.dataset_id}`}><td>{item.user_name}<br /><span>Cuenta #{item.user_id}</span></td><td>{item.dataset_name}</td><td>{new Date(item.requested_at * 1000).toLocaleString()}</td><td>
        {item.status === 'pending' ? <div className="management-actions"><button className="management-primary" disabled={busy} onClick={() => void decide(item.user_id, item.dataset_id, 'approve')}>Aprobar acceso</button><button disabled={busy} onClick={() => void decide(item.user_id, item.dataset_id, 'reject')}>Rechazar solicitud</button></div> : <><p>{item.status === 'approved' ? 'Aprobada' : 'Rechazada'}</p><span>Por cuenta #{item.decided_by}{item.decided_at ? ` · ${new Date(item.decided_at * 1000).toLocaleString()}` : ''}</span></>}
      </td></tr>)}
    </tbody></table></div>{page.requests.length === 0 && <p>No hay solicitudes con este estado.</p>}
      <div className="management-actions"><button disabled={busy || offset === 0} onClick={() => refresh(Math.max(0, offset - 20))}>Solicitudes anteriores</button><span>{page.total} solicitudes</span><button disabled={busy || offset + page.requests.length >= page.total} onClick={() => refresh(offset + 20)}>Solicitudes siguientes</button></div></>}
  </section>;
}
