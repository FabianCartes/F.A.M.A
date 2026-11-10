"use client";
import { useEffect, useRef, useState } from 'react';
import { listCatalogue, requestAccess, type CataloguePage } from '@/lib/api/datasetAccessApi';

export default function DatasetCatalogue() {
  const [page, setPage] = useState<CataloguePage | null>(null);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const mutation = useRef<AbortController | null>(null);
  useEffect(() => () => mutation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    listCatalogue(offset, controller.signal).then(value => { if (!controller.signal.aborted) { setPage(value); setError(''); } })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [offset, revision]);
  function refresh(next = offset) { setPage(null); setError(''); setOffset(next); setRevision(value => value + 1); }
  async function submit(id: number) {
    if (mutation.current) return;
    const controller = new AbortController(); mutation.current = controller; setBusy(true); setError('');
    try { await requestAccess(id, controller.signal); if (!controller.signal.aborted) refresh(); }
    catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'No se pudo confirmar la solicitud.'); }
    finally { if (!controller.signal.aborted) { mutation.current = null; setBusy(false); } }
  }
  const button = 'px-3 py-2 rounded-lg border border-[#373a46] text-xs text-gray-200 hover:bg-[#23252e] disabled:opacity-40';
  return <section aria-label="Catálogo de datasets" className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4 text-sm text-gray-300">
    <div className="flex justify-between gap-3"><h2 className="font-semibold text-gray-100">Datasets disponibles</h2><button className={button} disabled={busy} onClick={() => refresh()}>Actualizar catálogo</button></div>
    <p className="text-xs text-gray-400">Consulta los metadatos registrados y solicita acceso. Los audios y las operaciones se habilitan cuando el administrador concede la asignación.</p>
    {error && <p role="alert" className="text-red-300">{error}</p>}
    {!page && !error && <p role="status">Cargando catálogo…</p>}
    {page && <><div className="overflow-x-auto"><table className="w-full text-left text-xs" aria-label="Datasets disponibles"><thead><tr><th className="p-2">Dataset y finalidad</th><th className="p-2">Audios registrados</th><th className="p-2">Tu acceso</th></tr></thead><tbody>
      {page.datasets.map(item => <tr key={item.dataset_id} className="border-t border-[#23252e]"><td className="p-2"><strong className="text-gray-100">{item.name}</strong><p className="text-gray-400 mt-1">{item.purpose}</p></td><td className="p-2">{item.audio_count}</td><td className="p-2">
        {item.assigned ? <span className="text-emerald-300">Asignado</span> : item.request_status === 'pending' ? <span className="text-amber-300">Solicitud pendiente</span> : <>
          {item.request_status === 'rejected' && <p className="text-amber-300 mb-2">Solicitud rechazada. Puedes volver a solicitar acceso.</p>}
          {item.request_status === 'approved' && <p className="text-gray-400 mb-2">Ya no tienes asignación. Puedes volver a solicitar acceso.</p>}
          <button disabled={busy} className={button} aria-label={`Solicitar acceso a ${item.name}`} onClick={() => void submit(item.dataset_id)}>Solicitar acceso</button>
        </>}
      </td></tr>)}
    </tbody></table></div>{page.datasets.length === 0 && <p>No hay datasets registrados en este catálogo.</p>}
      <div className="flex items-center gap-3 text-xs"><button className={button} disabled={busy || offset === 0} onClick={() => refresh(Math.max(0, offset - 20))}>Anteriores</button><span>{page.total} datasets</span><button className={button} disabled={busy || offset + page.datasets.length >= page.total} onClick={() => refresh(offset + 20)}>Siguientes</button></div></>}
  </section>;
}
