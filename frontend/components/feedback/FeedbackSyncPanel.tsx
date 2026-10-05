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
      setError("No se pudo consultar la sincronización. Se conserva la última consulta disponible; actualiza para reintentar.");
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
    <section aria-label="Sincronización de audios incorporados" className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4 text-xs text-gray-300">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-bold text-white">Sincronización de audios incorporados</h2>
        <button type="button" onClick={() => void refresh()} className="px-3 py-2 rounded-lg border border-[#373a46] hover:text-white focus-visible:outline focus-visible:outline-emerald-400">
          Actualizar sincronización
        </button>
      </div>
      <p>Últimos 50 registros aceptados, separados de la cola de revisión. La incorporación local es un hito aceptado, no una auditoría física actual. Una copia cloud confirmada es un acuse durable, no una comprobación de existencia actual en GCS.</p>
      {loading && <p role="status">Consultando sincronización de audios...</p>}
      {error && <p role="alert" className="text-amber-300">{error}</p>}
      {!loading && !error && records.length === 0 && <p role="status">No hay registros recientes de sincronización.</p>}
      {records.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left" aria-label="Estados de audios incorporados">
            <thead>
              <tr className="border-b border-[#23252e]">
                <th className="p-2">Feedback / Predicción</th>
                <th className="p-2">Dataset / Clase</th>
                <th className="p-2">Estado local</th>
                <th className="p-2">Copia cloud</th>
                <th className="p-2">Intentos</th>
              </tr>
            </thead>
            <tbody>
              {records.map(record => (
                <tr key={record.id_retroalimentacion} className="border-b border-[#23252e]">
                  <td className="p-2">Feedback #{record.id_retroalimentacion}<br />Predicción #{record.id_prediccion}</td>
                  <td className="p-2"><p>{record.dataset_name}</p><p>{record.class_label}</p><p className="text-gray-400">Directorio: {record.storage_class}</p></td>
                  <td className="p-2 text-emerald-300">Incorporado localmente</td>
                  <td className="p-2">
                    <p>{record.sync_status === "synced" ? "Copia cloud confirmada" : "Pendiente de copia cloud"}</p>
                    {record.sync_status === "pending" && (
                      <p className="text-amber-300">
                        {record.error_code === "integrity_mismatch"
                          ? "Integridad inconsistente: requiere atención manual; el reintento no repara los archivos."
                          : record.error_code === "upload_failed"
                            ? "Subida fallida: reintento automático del backend."
                            : "Sincronización automática a cargo del backend."}
                      </p>
                    )}
                  </td>
                  <td className="p-2">{record.attempts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
