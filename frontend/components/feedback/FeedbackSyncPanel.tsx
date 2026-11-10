"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getFeedbackSync } from "@/lib/api/feedbackApi";
import type { FeedbackSyncState } from "@/lib/schemas/feedback";

/** Owns read-only recent outcomes independently of the uncurated queue. */
export default function FeedbackSyncPanel({ refreshKey }: { refreshKey: number }) {
  const [records, setRecords] = useState<FeedbackSyncState[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const request = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    const current = ++generation.current;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    try {
      const next = await getFeedbackSync(50, controller.signal);
      if (current !== generation.current || controller.signal.aborted) return;
      setRecords(next);
      setError(null);
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
      <p>Últimos 50 registros aceptados, separados de la cola de revisión. La incorporación local es un hito aceptado, no una auditoría física actual. Una copia cloud confirmada es un acuse durable, no una comprobación de existencia actual en GCS.</p>
      {loading && <p role="status">Consultando registro de audios...</p>}
      {error && <p role="alert" className="text-amber-300">{error}</p>}
      {!loading && !error && records.length === 0 && <p role="status">No hay registros recientes de audios incorporados.</p>}
      {records.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left" aria-label="Estados de audios incorporados">
            <thead>
              <tr className="border-b border-[#23252e]">
                <th className="p-2">Dataset de destino</th>
                <th className="p-2">Nombre del audio revisado</th>
                <th className="p-2">Estado local</th>
                <th className="p-2">Registro y autoría</th>
                <th className="p-2">Copia cloud</th>
              </tr>
            </thead>
            <tbody>
              {records.map(record => (
                <tr key={record.id_retroalimentacion} className="border-b border-[#23252e]">
                  <td className="p-2">
                    {record.dataset_display_name || (record.dataset_name.startsWith('imported:')
                      ? 'Dataset privado' : record.dataset_name)}
                  </td>
                  <td className="p-2">
                    <p><span className="text-gray-400">Original: </span>{record.audio_filename || 'Nombre original no disponible'}</p>
                    <p><span className="text-gray-400">En el dataset: </span>{record.incorporated_filename || 'Nombre de incorporación no disponible'}</p>
                  </td>
                  <td className="p-2 text-emerald-300">Incorporado localmente</td>
                  <td className="p-2"><p>{record.db_persisted === true ? "Registrado en PostgreSQL" : "Registro SQL sin confirmar"}</p><p className="text-gray-400 mt-1">Propuesto por {record.proposed_by ? `cuenta #${record.proposed_by}` : "autor sin registrar"} · Incorporado por {record.incorporated_by ? `cuenta #${record.incorporated_by}` : "autor sin registrar"}</p>{record.incorporated_at && <p className="text-gray-500 mt-1">{new Date(record.incorporated_at).toLocaleString()}</p>}</td>
                  <td className="p-2">
                    <p>{record.sync_status === "synced" ? "Copia cloud confirmada" : "Pendiente de copia cloud"}</p>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
