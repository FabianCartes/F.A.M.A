"use client";

import { useState } from "react";

interface DatasetItem {
  id: string;
  nombre: string;
  tamano: string;
  fecha: string;
  estado: "Sincronizado" | "Pendiente" | "Error";
}

export default function IngestionView() {
  const [datasets, setDatasets] = useState<DatasetItem[]>([
    { id: "1", nombre: "ESC-50", tamano: "1.8 GB", fecha: "2025-03-15", estado: "Sincronizado" },
    { id: "2", nombre: "UrbanSound8K", tamano: "6.2 GB", fecha: "2025-04-02", estado: "Pendiente" },
    { id: "3", nombre: "AudioSet Balanced", tamano: "24.5 GB", fecha: "2025-04-10", estado: "Error" },
    { id: "4", nombre: "FMA Small", tamano: "3.1 GB", fecha: "2025-05-01", estado: "Sincronizado" },
    { id: "5", nombre: "LibriSpeech Clean", tamano: "12.4 GB", fecha: "2025-05-20", estado: "Pendiente" },
    { id: "6", nombre: "VoxCeleb2", tamano: "48 GB", fecha: "2025-06-01", estado: "Pendiente" },
  ]);

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [syncing, setSyncing] = useState(false);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const handleSync = () => {
    if (selectedIds.length === 0) return;
    setSyncing(true);
    setTimeout(() => {
      setDatasets((prev) =>
        prev.map((d) => (selectedIds.includes(d.id) ? { ...d, estado: "Sincronizado" } : d))
      );
      setSelectedIds([]);
      setSyncing(false);
    }, 1500);
  };

  return (
    <div className="space-y-5">
      {/* Header de la Vista (Figura 6.6) */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <svg className="w-5 h-5 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
          </svg>
          <h1 className="text-xl font-bold text-white tracking-tight font-heading">
            Ingesta y Procesamiento
          </h1>
        </div>

        {/* Indicadores Derecha */}
        <div className="flex items-center gap-3 text-xs">
          <span className="font-mono text-gray-400">12.4 GB / 50 GB</span>
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-950/60 border border-green-800/60 text-green-400 font-medium text-[11px]">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
            GCP: Conectado
          </span>
        </div>
      </div>

      {/* Tarjeta: Datasets Disponibles en GCS (Figura 6.6) */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4">
        <span className="text-xs text-gray-300 font-semibold block">
          Datasets Disponibles en GCS
        </span>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-[#23252e] text-gray-400">
                <th className="pb-3 w-8" />
                <th className="pb-3 font-medium">Nombre</th>
                <th className="pb-3 font-medium">Tamaño</th>
                <th className="pb-3 font-medium">Fecha</th>
                <th className="pb-3 font-medium text-right pr-2">Estado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#23252e]/60">
              {datasets.map((d) => (
                <tr key={d.id} className="hover:bg-[#1c1e24]/40 transition-colors">
                  <td className="py-2.5">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(d.id)}
                      onChange={() => toggleSelect(d.id)}
                      className="rounded bg-[#121316] border-[#2d303b] text-blue-600 focus:ring-0 cursor-pointer"
                    />
                  </td>
                  <td className="py-2.5 font-medium text-gray-200">{d.nombre}</td>
                  <td className="py-2.5 text-gray-400 font-mono">{d.tamano}</td>
                  <td className="py-2.5 text-gray-400 font-mono">{d.fecha}</td>
                  <td className="py-2.5 text-right pr-2">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                        d.estado === "Sincronizado"
                          ? "bg-gray-800 text-gray-300 border border-gray-700"
                          : d.estado === "Error"
                          ? "bg-red-950/70 text-red-400 border border-red-800/60"
                          : "bg-[#1f2128] text-gray-400 border border-[#2e323e]"
                      }`}
                    >
                      {d.estado}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Footer de Tabla con Acción */}
        <div className="flex items-center justify-between pt-2 border-t border-[#23252e]/70">
          <span className="text-xs text-gray-500">
            {selectedIds.length} dataset(s) seleccionados
          </span>
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing || selectedIds.length === 0}
            className="py-1.5 px-3 rounded-lg text-xs font-medium text-gray-200 bg-[#262831] hover:bg-[#31343f] active:bg-[#1d1f26] disabled:opacity-40 disabled:cursor-not-allowed border border-[#373a46] transition-all flex items-center gap-1.5 shadow-sm"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
            <span>{syncing ? "Sincronizando..." : "Sincronizar y procesar"}</span>
          </button>
        </div>
      </div>

      {/* Tarjeta: Progreso de Operación (Figura 6.6) */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3">
        <span className="text-xs text-gray-300 font-semibold block">
          Progreso de Operación
        </span>

        <div className="space-y-2.5 text-xs">
          <div>
            <div className="flex justify-between items-center text-gray-400 mb-1">
              <span className="flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Descarga
              </span>
              <span className="font-mono text-[11px]">0/15 archivos</span>
            </div>
            <div className="w-full bg-[#111215] rounded-full h-1.5 overflow-hidden">
              <div className="bg-blue-600 h-1.5 rounded-full" style={{ width: "0%" }} />
            </div>
          </div>

          <div>
            <div className="flex justify-between items-center text-gray-400 mb-1">
              <span className="flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                Procesamiento
              </span>
              <span className="font-mono text-[11px]">0/15 archivos</span>
            </div>
            <div className="w-full bg-[#111215] rounded-full h-1.5 overflow-hidden">
              <div className="bg-emerald-600 h-1.5 rounded-full" style={{ width: "0%" }} />
            </div>
          </div>
        </div>
      </div>

      {/* Tarjeta: Consola de Logs (Figura 6.6) */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-2.5">
        <span className="text-xs text-gray-300 font-semibold block">
          Consola de Logs
        </span>

        <div className="bg-[#0f1013] rounded-lg p-3.5 font-mono text-[11px] leading-relaxed text-gray-300 border border-[#1f2128] space-y-1 overflow-x-auto max-h-56">
          <p><span className="text-gray-500">2025-06-28T10:00:00.000Z</span> <span className="text-blue-400 bg-blue-950/70 px-1 rounded text-[10px]">INFO</span> Inicializando módulo de ingesta...</p>
          <p><span className="text-gray-500">2025-06-28T10:00:01.200Z</span> <span className="text-blue-400 bg-blue-950/70 px-1 rounded text-[10px]">INFO</span> Conectando con Google Cloud Storage...</p>
          <p><span className="text-gray-500">2025-06-28T10:00:02.500Z</span> <span className="text-yellow-400 bg-yellow-950/70 px-1 rounded text-[10px]">WARN</span> El bucket &apos;fama-audio-datasets&apos; contiene archivos sin metadatos.</p>
          <p><span className="text-gray-500">2025-06-28T10:00:03.100Z</span> <span className="text-blue-400 bg-blue-950/70 px-1 rounded text-[10px]">INFO</span> GCP: Conexión establecida correctamente.</p>
          <p><span className="text-gray-500">2025-06-28T10:00:04.800Z</span> <span className="text-blue-400 bg-blue-950/70 px-1 rounded text-[10px]">INFO</span> Listando datasets disponibles...</p>
          <p><span className="text-gray-500">2025-06-28T10:00:05.500Z</span> <span className="text-blue-400 bg-blue-950/70 px-1 rounded text-[10px]">INFO</span> 6 datasets encontrados en el bucket.</p>
          <p><span className="text-gray-500">2025-06-28T10:00:06.200Z</span> <span className="text-red-400 bg-red-950/70 px-1 rounded text-[10px]">ERROR</span> Dataset &apos;AudioSet Balanced&apos;: error de checksum en archivos parciales.</p>
          <p><span className="text-gray-500">2025-06-28T10:00:07.000Z</span> <span className="text-blue-400 bg-blue-950/70 px-1 rounded text-[10px]">INFO</span> Listo para operación. Seleccione datasets y presione &apos;Sincronizar&apos;.</p>
          <p><span className="text-gray-500">2025-06-28T10:00:08.100Z</span> <span className="text-blue-400 bg-blue-950/70 px-1 rounded text-[10px]">INFO</span> Sistema ocioso — esperando instrucción del usuario.</p>
        </div>
      </div>
    </div>
  );
}
