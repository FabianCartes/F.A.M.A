"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import { API_BASE_URL, apiFetch } from "@/lib/api";

const summarySchema = z.object({
  version: z.string().regex(/^[0-9a-f]{64}$/),
  counts: z.object({ train: z.number().int().positive(), val: z.number().int().positive() }),
  warnings: z.array(z.string()).default([]), created_at: z.string().optional(), created_by: z.number().optional(),
});
const previewSchema = summarySchema.extend({
  entries: z.array(z.object({ clase: z.string(), split: z.enum(["train", "val"]) })),
  excluded: z.array(z.object({ file_path: z.string(), reason: z.string() })).default([]),
});
type Summary = z.infer<typeof summarySchema>;
type Preview = z.infer<typeof previewSchema>;

async function request(url: string, options: RequestInit) {
  const response = await apiFetch(url, options);
  const data: unknown = await response.json().catch(() => null);
  const detail = typeof data === "object" && data !== null && "detail" in data ? data.detail : null;
  if (!response.ok) throw new Error(typeof detail === "string" ? detail : "No se pudo completar la operación de particiones.");
  return data;
}

interface Props { dataset: string; busy: boolean; selected: string; onSelect: (version: string) => void; }

export default function DatasetPartitions({ dataset, busy, selected, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<"idle" | "loading" | "preview" | "saving">("idle");
  const [versions, setVersions] = useState<Summary[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [validation, setValidation] = useState("20");
  const [seed, setSeed] = useState("42");
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const active = useRef<AbortController | null>(null);
  const base = `${API_BASE_URL}/api/training/datasets/${encodeURIComponent(dataset)}/partitions`;
  const locked = busy || phase !== "idle";

  useEffect(() => {
    if (!open || !dataset) return;
    const controller = new AbortController();
    active.current = controller;
    void request(base, { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return;
      const parsed = z.object({ versions: z.array(summarySchema) }).safeParse(data);
      if (!parsed.success) throw new Error("No se pudo interpretar la lista de versiones.");
      setVersions(parsed.data.versions);
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "No se pudieron consultar las versiones.");
    }).finally(() => { if (!controller.signal.aborted) setPhase("idle"); });
    return () => { controller.abort(); active.current?.abort(); };
  }, [open, dataset, base]);

  function changePolicy(value: string, field: "validation" | "seed") {
    if (field === "validation") setValidation(value); else setSeed(value);
    setPreview(null); setAcknowledged(false); setMessage("");
  }

  async function prepare(save = false) {
    if (locked) return;
    const percent = Number(validation), randomSeed = Number(seed);
    if (!validation.trim() || !seed.trim() || !Number.isInteger(percent) || percent < 10 || percent > 40 ||
      !Number.isInteger(randomSeed) || randomSeed < 0 || randomSeed > 2147483647) {
      setError("Usa entre 10 y 40 % para validación y una semilla entera entre 0 y 2147483647.");
      return;
    }
    if (save && (!preview || preview.warnings.length > 0 && !acknowledged)) return;
    active.current?.abort();
    const controller = new AbortController(); active.current = controller;
    setPhase(save ? "saving" : "preview"); setError(""); setMessage("");
    try {
      const data = await request(save ? base : `${base}/preview`, {
        method: "POST", signal: controller.signal, headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ validation_percent: percent, seed: randomSeed,
          ...(save ? { preview_version: preview?.version, acknowledge_warnings: acknowledged } : {}) }),
      });
      if (controller.signal.aborted) return;
      if (save) {
        const parsed = summarySchema.safeParse(data);
        if (!parsed.success) throw new Error("No se pudo confirmar la versión guardada.");
        setVersions(previous => [parsed.data, ...previous.filter(item => item.version !== parsed.data.version)]);
        onSelect(parsed.data.version); setPreview(null); setAcknowledged(false);
        setMessage("Versión guardada. Se usará al iniciar el próximo entrenamiento.");
      } else {
        const parsed = previewSchema.safeParse(data);
        if (!parsed.success) throw new Error("No se pudo interpretar la vista previa.");
        setPreview(parsed.data); setAcknowledged(false);
      }
    } catch (failure: unknown) {
      if (!controller.signal.aborted) {
        setError(failure instanceof Error ? failure.message : "No se pudo preparar la partición.");
        if (save) setPreview(null);
      }
    } finally { if (!controller.signal.aborted) setPhase("idle"); }
  }

  const classes = [...new Set(preview?.entries.map(entry => entry.clase) ?? [])].sort();
  const fieldClass = "w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-emerald-600 disabled:opacity-50";
  return (
    <section aria-label="Particiones de entrenamiento" className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-200">Particiones de entrenamiento</h2>
          <p className="text-xs text-gray-400 mt-1">{selected ? `Versión seleccionada: ${selected.slice(0, 12)}` : "CSV existentes o una versión preparada desde tus audios locales."}</p>
        </div>
        <button type="button" disabled={locked || !dataset} aria-expanded={open} onClick={() => {
          setError(""); if (!open) setPhase("loading"); setOpen(!open);
        }} className="px-3 py-2 text-xs font-semibold bg-[#1c1e24] border border-[#30333e] rounded-lg text-gray-300 disabled:opacity-50 hover:border-emerald-700">
          {open ? "Cerrar particiones" : "Gestionar particiones"}
        </button>
      </div>
      {open && <>
        <p className="text-xs text-gray-400 leading-relaxed">Entrenamiento enseña al modelo; validación comprueba su rendimiento con otros audios. Una versión fija los archivos y su reparto. Añadir audios después no cambia las versiones guardadas. Esta división no reserva una prueba final independiente.</p>
        {error && <p role="alert" className="text-xs text-rose-300 bg-rose-950/30 border border-rose-900 rounded-lg p-3">{error}</p>}
        {message && <p role="status" className="text-xs text-emerald-300">{message}</p>}
        {phase === "loading" && <p role="status" className="text-xs text-gray-400">Consultando versiones…</p>}
        <label className="block text-xs text-gray-400">Versión para entrenar
          <select aria-label="Versión para entrenar" value={selected} disabled={locked} onChange={event => onSelect(event.target.value)} className={`${fieldClass} mt-1`}>
            <option value="">Usar CSV existentes (requiere particiones preparadas)</option>
            {selected && !versions.some(item => item.version === selected) && <option value={selected}>Versión seleccionada {selected.slice(0, 12)}</option>}
            {versions.map(item => <option key={item.version} value={item.version}>{item.version.slice(0, 12)} · {item.counts.train} entrenamiento / {item.counts.val} validación{item.created_at ? ` · ${new Date(item.created_at).toLocaleString("es-CL")}` : ""}</option>)}
          </select>
        </label>
        <div className="border-t border-[#23252e] pt-4 space-y-3">
          <h3 className="text-xs font-semibold text-gray-200">Preparar una nueva versión</h3>
          <p className="text-xs text-gray-400">Solo se incluyen audios registrados y disponibles en este equipo. Se conservan juntos los duplicados y grupos de origen o grabador conocidos. El porcentaje puede variar para respetar esos grupos.</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
            <label className="text-xs text-gray-400">Validación (%)<input aria-label="Validación (%)" type="number" min={10} max={40} step={1} value={validation} disabled={locked} onChange={event => changePolicy(event.target.value, "validation")} className={`${fieldClass} mt-1`} /></label>
            <label className="text-xs text-gray-400">Semilla del reparto<input aria-label="Semilla del reparto" type="number" min={0} max={2147483647} step={1} value={seed} disabled={locked} onChange={event => changePolicy(event.target.value, "seed")} className={`${fieldClass} mt-1`} /></label>
            <button type="button" disabled={locked} onClick={() => void prepare()} className="px-3 py-2 rounded-lg text-xs font-semibold border border-emerald-800 text-emerald-300 bg-emerald-950/30 disabled:opacity-50">{phase === "preview" ? "Calculando reparto…" : "Previsualizar reparto"}</button>
          </div>
          {preview && <div className="rounded-lg bg-[#111215] border border-[#23252e] p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-200">{preview.counts.train} para entrenamiento · {preview.counts.val} para validación</p>
            <p className="text-xs text-gray-400">{preview.excluded.length} audios excluidos de esta propuesta. Los archivos y CSV existentes se conservan.</p>
            {preview.excluded.length > 0 && <details className="text-xs text-gray-400">
              <summary className="cursor-pointer text-gray-300">Ver audios excluidos y sus motivos</summary>
              <ul className="mt-2 space-y-1 break-words">{preview.excluded.map(item => <li key={item.file_path}>
                <span className="font-mono text-gray-300">{item.file_path}</span>{" · "}
                {item.reason === "not_local" ? "no está descargado en este equipo" : item.reason === "feedback_without_source_group"
                  ? "corrección sin grupo de origen registrado" : "requiere revisar su disponibilidad"}
              </li>)}</ul>
            </details>}
            <table aria-label="Reparto por clase" className="w-full text-xs text-left">
              <thead className="text-gray-500"><tr><th className="pb-2">Clase</th><th>Entrenamiento</th><th>Validación</th></tr></thead>
              <tbody className="text-gray-300">{classes.map(label => <tr key={label} className="border-t border-[#23252e]">
                <td className="py-2">{label}</td>{["train", "val"].map(split => <td key={split}>{preview.entries.filter(entry => entry.clase === label && entry.split === split).length}</td>)}
              </tr>)}</tbody>
            </table>
            {preview.warnings.length > 0 && <div className="text-xs text-amber-200 bg-amber-950/20 border border-amber-900/50 rounded-lg p-3 space-y-2">
              <ul className="list-disc pl-4 space-y-1">{preview.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>
              <label className="flex gap-2 items-start"><input type="checkbox" checked={acknowledged} disabled={locked} onChange={event => setAcknowledged(event.target.checked)} />He revisado las advertencias de esta partición</label>
            </div>}
            <button type="button" disabled={locked || preview.warnings.length > 0 && !acknowledged} onClick={() => void prepare(true)} className="px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-700 text-white hover:bg-emerald-600 disabled:opacity-40">{phase === "saving" ? "Guardando versión…" : "Guardar versión y seleccionarla"}</button>
          </div>}
        </div>
      </>}
    </section>
  );
}
