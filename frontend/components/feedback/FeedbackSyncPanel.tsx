"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getFeedbackSync } from "@/lib/api/feedbackApi";
import type { FeedbackSyncState } from "@/lib/schemas/feedback";
import PageControls, { PAGE_SIZE } from "@/components/common/PageControls";
import { SkeletonRows } from "@/components/common/Skeleton";
import { stackedCell, stackedRow, stackedTable } from "@/components/common/stackedTable";

function author(id: number | null | undefined, name: string | null | undefined) {
  return name || (id ? `cuenta #${id}` : "autor sin registrar");
}

/** Who proposed and who incorporated the audio (ADR 0061), abbreviated for one person. */
function authorship(record: FeedbackSyncState) {
  const proposed = author(record.proposed_by, record.proposed_by_name);
  if (record.proposed_by && record.proposed_by === record.incorporated_by) return `Propuesto e incorporado por ${proposed}`;
  return `Propuesto por ${proposed} · Incorporado por ${author(record.incorporated_by, record.incorporated_by_name)}`;
}

/** Owns read-only recent outcomes independently of the uncurated queue. */
export default function FeedbackSyncPanel({ refreshKey, onSynced }: {
  refreshKey: number;
  /** Called when a pending cloud copy is observed as synced. */
  onSynced?: () => void;
}) {
  const [records, setRecords] = useState<FeedbackSyncState[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const pageOffset = useRef(0);
  const pending = useRef(new Set<number>());
  const synced = useRef(onSynced);
  useEffect(() => { synced.current = onSynced; }, [onSynced]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const request = useRef<AbortController | null>(null);

  const refresh = useCallback(async (quiet = false, requested = pageOffset.current) => {
    const current = ++generation.current;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    if (!quiet) setLoading(true);
    try {
      let fetched = await getFeedbackSync(PAGE_SIZE + 1, controller.signal, requested);
      // A page emptied since the last read falls back to the previous page.
      while (fetched.length === 0 && requested > 0 && current === generation.current && !controller.signal.aborted) {
        requested = Math.max(0, requested - PAGE_SIZE);
        fetched = await getFeedbackSync(PAGE_SIZE + 1, controller.signal, requested);
      }
      if (current !== generation.current || controller.signal.aborted) return;
      const next = fetched.slice(0, PAGE_SIZE);
      pageOffset.current = requested;
      setOffset(requested);
      setHasNext(fetched.length > PAGE_SIZE);
      const arrived = next.some(record => record.sync_status === "synced" && pending.current.has(record.id_retroalimentacion));
      pending.current = new Set(next.filter(record => record.sync_status === "pending").map(record => record.id_retroalimentacion));
      setRecords(next);
      setError(null);
      if (arrived) synced.current?.();
    } catch {
      if (current !== generation.current || controller.signal.aborted) return;
      setError("No se pudo consultar el registro. Se conserva la última consulta disponible; vuelve a esta pestaña o recarga la página para reintentar.");
    } finally {
      if (current === generation.current && !controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    // Defer the initial read; StrictMode cleanup must not start an abandoned read.
    void Promise.resolve().then(() => { if (!disposed) void refresh(); });
    return () => {
      disposed = true;
      request.current?.abort();
    };
  }, [refresh, refreshKey]);

  // The backend worker copies pending audios to GCS every 60 s; poll only while
  // some copy is pending, so the state and the inventory follow it.
  const waiting = records.some(record => record.sync_status === "pending");
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => void refresh(true), 10000);
    return () => clearInterval(timer);
  }, [waiting, refresh]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  return (
    <section aria-label="Registro de audios incorporados" className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4 text-xs text-gray-300">
      <h2 className="text-sm font-bold text-white">Registro de audios incorporados</h2>
      <p>Registros aceptados, del más reciente al más antiguo y separados de la cola de revisión. La incorporación local es un hito aceptado, no una auditoría física actual. Una copia cloud confirmada es un acuse durable, no una comprobación de existencia actual en GCS.</p>
      {loading && <><p role="status">Consultando registro de audios...</p><SkeletonRows rows={3} /></>}
      {error && <p role="alert" className="text-amber-300">{error}</p>}
      {!loading && !error && records.length === 0 && <p role="status">No hay registros recientes de audios incorporados.</p>}
      {records.length > 0 && (
        <div className="md:overflow-x-auto">
          <table className={stackedTable} aria-label="Estados de audios incorporados">
            <thead className="hidden md:table-header-group">
              <tr className="border-b border-[#23252e]">
                <th className="p-2">Dataset de destino</th>
                <th className="p-2">Nombre del audio revisado</th>
                <th className="p-2">Estado local</th>
                <th className="p-2">Registro y autoría</th>
                <th className="p-2">Copia cloud</th>
              </tr>
            </thead>
            <tbody className="block md:table-row-group">
              {records.map(record => (
                <tr key={record.id_retroalimentacion} className={`${stackedRow} md:border-b md:border-[#23252e]`}>
                  <td data-label="Dataset" className={`${stackedCell} md:p-2`}>
                    {record.dataset_display_name || (record.dataset_name.startsWith('imported:')
                      ? 'Dataset privado' : record.dataset_name)}
                  </td>
                  <td data-label="Audio" className={`${stackedCell} md:p-2`}>
                    <div className="min-w-0 break-words">
                      <p><span className="text-gray-400">Original: </span>{record.audio_filename || 'Nombre original no disponible'}</p>
                      <p><span className="text-gray-400">En el dataset: </span>{record.incorporated_filename || 'Nombre de incorporación no disponible'}</p>
                    </div>
                  </td>
                  <td data-label="Estado local" className={`${stackedCell} md:p-2 text-emerald-300`}>Incorporado localmente</td>
                  <td data-label="Registro" className={`${stackedCell} md:p-2`}><div className="min-w-0"><p>{record.db_persisted === true ? "Registrado en PostgreSQL" : "Registro SQL sin confirmar"}</p><p className="text-gray-400 mt-1">{authorship(record)}</p>{record.incorporated_at && <p className="text-gray-500 mt-1">{new Date(record.incorporated_at).toLocaleString()}</p>}</div></td>
                  <td data-label="Copia cloud" className={`${stackedCell} md:p-2`}>
                    <p>{record.sync_status === "synced" ? "Copia cloud confirmada" : "Pendiente de copia cloud"}</p>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <PageControls offset={offset} hasNext={hasNext} disabled={loading}
        onChange={next => void refresh(false, next)} />
    </section>
  );
}
