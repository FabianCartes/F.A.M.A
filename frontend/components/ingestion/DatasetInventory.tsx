"use client";

import { useState } from "react";

export interface DatasetItem {
  id: string;
  name: string;
  classes?: string[];
  file_count: number;
  total_size_bytes: number;
  last_modified: string | null;
  local_file_count?: number | null;
  local_size_bytes?: number | null;
  gcs_file_count?: number | null;
  gcs_size_bytes?: number | null;
  is_synced?: boolean | null;
  sync_state?: string;
  source?: "gcs" | "local" | "database";
  gcs_available?: boolean | null;
  domain?: string;
}

function bytes(value: number | null | undefined): string {
  if (value == null) return "Sin consultar";
  if (value === 0) return "0 B";
  const index = Math.min(4, Math.floor(Math.log(value) / Math.log(1024)));
  return `${Number((value / 1024 ** index).toFixed(2))} ${["B", "KB", "MB", "GB", "TB"][index]}`;
}

export function cloudCount(item: DatasetItem): number | null {
  if (item.gcs_available === false) return null;
  if (item.gcs_file_count != null) return item.gcs_file_count;
  if (item.source === "gcs") return item.file_count;
  if (item.source === "local" && item.gcs_available === true) return 0;
  return null;
}

function state(item: DatasetItem): string {
  const cloud = cloudCount(item);
  const local = item.local_file_count;
  if (cloud == null) return "GCS sin consultar";
  if (cloud === 0 && local != null && local > 0) return "Solo local";
  if (cloud > 0 && local === 0) return "Solo en GCS";
  if (cloud > 0 && local != null && local > 0) return "Local y GCS";
  if (cloud === 0 && local === 0) return "Sin audios";
  return "Local sin consultar";
}

interface Props {
  datasets: DatasetItem[];
  loading: boolean;
  busy: boolean;
  onRefresh: () => void;
  onDownload: (names: string[]) => void;
  onInspect: (name: string) => void;
  onPreprocess?: (names: string[]) => void;
}

export default function DatasetInventory({ datasets, loading, busy, onRefresh, onDownload, onInspect, onPreprocess }: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  const selection = datasets.filter(item => selected.includes(item.id));
  const anySelected = selection.length > 0;
  const downloadable = anySelected && selection.every(item => (cloudCount(item) ?? 0) > 0);
  const local = anySelected && selection.every(item => (item.local_file_count ?? 0) > 0);

  return <section aria-label="Datasets locales y en GCS" className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4 shadow-sm">
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="text-sm font-semibold text-gray-200">Datasets locales y en GCS</h2>
        <span className="text-[10px] px-2 py-0.5 rounded bg-[#1c1e24] text-gray-400 font-mono">{datasets.length} colecciones</span>
      </div>
      <button type="button" onClick={onRefresh} disabled={loading || busy} className="text-xs text-gray-400 hover:text-white disabled:opacity-40">Actualizar</button>
    </div>
    <p className="text-xs text-gray-400">El equipo y el bucket se consultan por separado. Tener audios en ambos lugares no confirma que su contenido coincida.</p>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] text-left text-xs" aria-label="Inventario de datasets">
        <thead><tr className="border-b border-[#23252e] text-gray-400">
          <th className="p-2 w-8"><input type="checkbox" aria-label="Seleccionar todos los datasets" disabled={busy || !datasets.length}
            checked={datasets.length > 0 && selection.length === datasets.length}
            onChange={() => setSelected(selection.length === datasets.length ? [] : datasets.map(item => item.id))} /></th>
          <th className="p-2 font-medium">Dataset / Clases</th>
          <th className="p-2 font-medium">En este equipo</th>
          <th className="p-2 font-medium">En GCS</th>
          <th className="p-2 font-medium">Disponibilidad</th>
          <th className="p-2 font-medium text-right">Acción</th>
        </tr></thead>
        <tbody className="divide-y divide-[#23252e]/60">
          {loading ? <tr><td colSpan={6} className="p-6 text-center text-gray-400">Consultando datasets…</td></tr>
            : datasets.length === 0 ? <tr><td colSpan={6} className="p-6 text-center text-gray-400">No hay datasets disponibles para esta cuenta.</td></tr>
              : datasets.map(item => {
                const cloud = cloudCount(item);
                const localBytes = item.local_size_bytes ?? (item.source === "local" ? item.total_size_bytes : null);
                const cloudBytes = item.gcs_size_bytes ?? (item.source === "gcs" ? item.total_size_bytes : cloud === 0 ? 0 : null);
                return <tr key={item.id} className="hover:bg-[#1c1e24]/40">
                  <td className="p-2 align-top"><input type="checkbox" aria-label={`Seleccionar ${item.name}`} disabled={busy}
                    checked={selected.includes(item.id)} onChange={() => setSelected(previous => previous.includes(item.id) ? previous.filter(id => id !== item.id) : [...previous, item.id])} /></td>
                  <td className="p-2 max-w-56">
                    <p className="font-semibold text-gray-200 break-words">{item.name}</p>
                    {item.source === "local" && <span className="text-[10px] text-gray-400">Local</span>}
                    <p className="text-[10px] text-gray-400 mt-1">{item.domain === "industrial" ? "Industrial" : item.domain === "bioacoustic" ? "Bioacústica" : "Colección de audios"}</p>
                    <div className="flex flex-wrap gap-1 mt-2">{item.classes?.slice(0, 3).map(label => <span key={label} className="px-1.5 py-0.5 rounded bg-[#222530] text-gray-300 text-[10px]">{label}</span>)}
                      {(item.classes?.length ?? 0) > 3 && <span className="text-gray-500">+{item.classes!.length - 3} más</span>}</div>
                  </td>
                  <td className="p-2 align-top whitespace-nowrap"><p>{item.local_file_count == null ? "Sin consultar" : `${item.local_file_count} audios`}</p><p className="text-gray-500 mt-1">{bytes(localBytes)}</p></td>
                  <td className="p-2 align-top whitespace-nowrap"><p>{cloud == null ? "Sin consultar" : `${cloud} audios`}</p><p className="text-gray-500 mt-1">{bytes(cloudBytes)}</p></td>
                  <td className="p-2 align-top"><span className="inline-block px-2 py-1 rounded border border-[#373a46] bg-[#1c1e24] text-gray-300">{state(item)}</span>
                    {state(item) === "Local y GCS" && <p className="mt-2 text-[10px] text-amber-300">Contenido sin comparar</p>}</td>
                  <td className="p-2 align-top text-right"><button type="button" onClick={() => onInspect(item.id)} className="px-2 py-1 rounded bg-[#1c1e24] border border-[#2d303b] text-gray-300 hover:text-white whitespace-nowrap">Ver archivos</button></td>
                </tr>;
              })}
        </tbody>
      </table>
    </div>
    <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-[#23252e]">
      <span className="text-xs text-gray-400">{selection.length} dataset(s) seleccionado(s)</span>
      <div className="flex gap-2 flex-wrap">
        <button type="button" disabled={busy || !local} onClick={() => onPreprocess?.(selection.map(item => item.id))} className="px-3 py-2 rounded-lg border border-[#373a46] text-xs font-semibold text-gray-200 hover:bg-[#23252e] disabled:opacity-40 disabled:cursor-not-allowed">Preprocesar audios locales</button>
        <button type="button" disabled={busy || !downloadable} onClick={() => onDownload(selection.map(item => item.id))} className="px-3 py-2 rounded-lg bg-emerald-600 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed">Descargar desde GCS</button>
      </div>
    </div>
    {anySelected && !downloadable && <p className="text-xs text-gray-500">Para descargar, selecciona únicamente colecciones con audios en el bucket actual.</p>}
  </section>;
}
