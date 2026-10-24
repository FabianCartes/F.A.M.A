"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import { API_BASE_URL, apiFetch } from "@/lib/api";

const copySchema = z.object({
  model_id: z.number().int(), filename: z.string(), sha256: z.string().regex(/^[0-9a-f]{64}$/),
  size_bytes: z.number().positive(), local: z.enum(["valid", "missing", "conflict"]),
  cloud: z.enum(["available", "missing", "conflict"]),
  generation: z.string().nullable(), transfer_verified: z.boolean(),
});
type Copies = z.infer<typeof copySchema>;
type State = { modelId: number; phase: "idle" | "status" | "backup" | "restore"; copies: Copies | null; error: string; message: string };

export default function CheckpointBackup({ modelId, onRestored }: { modelId: number; onRestored: () => void }) {
  const [state, setState] = useState<State>({ modelId, phase: "idle", copies: null, error: "", message: "" });
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => { active.current?.abort(); }, [modelId]);
  const current = state.modelId === modelId ? state : { modelId, phase: "idle", copies: null, error: "", message: "" };
  const busy = current.phase !== "idle";

  async function request(action: "status" | "backup" | "restore") {
    if (busy) return;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setState({ ...current, modelId, phase: action, error: "", message: "" });
    try {
      const base = `${API_BASE_URL}/api/training/models/${modelId}/checkpoint`;
      const response = await apiFetch(action === "status" ? base : `${base}/${action}`, {
        method: action === "status" ? "GET" : "POST", signal: controller.signal,
      });
      const payload: unknown = await response.json().catch(() => null);
      if (controller.signal.aborted) return;
      if (!response.ok) {
        const detail = typeof payload === "object" && payload !== null && "detail" in payload ? payload.detail : null;
        throw new Error(typeof detail === "string" ? detail : "No se pudo completar la operación de copias.");
      }
      const parsed = copySchema.safeParse(payload);
      if (!parsed.success || parsed.data.model_id !== modelId) throw new Error("No se pudo interpretar el estado de copias de este modelo.");
      const result = parsed.data;
      if (action !== "status" && (!result.transfer_verified || result.cloud !== "available" ||
          (action === "restore" && result.local !== "valid"))) {
        throw new Error("La transferencia no quedó confirmada. Comprueba las copias antes de reintentar.");
      }
      setState({ modelId, phase: "idle", copies: result, error: "", message: action === "status" ? "" : action === "backup"
        ? "Respaldo verificado: tamaño y SHA-256 coinciden."
        : "Checkpoint recuperado y verificado en este equipo. El modelo conserva su activación anterior." });
      if (action === "restore") onRestored();
    } catch (failure: unknown) {
      if (!controller.signal.aborted) setState({ modelId, phase: "idle", copies: null, message: "",
        error: failure instanceof Error ? failure.message : "No se pudo completar la operación de copias." });
    }
  }

  const copies = current.copies;
  const buttonClass = "text-xs px-3 py-2 rounded-lg border border-[#2d303b] bg-[#1c1e24] text-gray-200 hover:bg-[#252832] disabled:opacity-40 disabled:cursor-not-allowed";
  return <section aria-label="Copias del checkpoint" className="rounded-xl border border-[#2d303b] bg-[#111215] p-4 space-y-3">
    <div className="flex items-center justify-between gap-3">
      <h3 className="text-sm font-semibold text-gray-100">Copias del checkpoint</h3>
      <button type="button" className={buttonClass} disabled={busy} onClick={() => void request("status")}>Comprobar copias</button>
    </div>
    <p className="text-xs text-gray-400">Respalda los pesos guardados o recupera una copia perdida en este equipo. Estas acciones conservan los archivos existentes y no cambian la activación del modelo.</p>
    {copies ? <div className="grid sm:grid-cols-2 gap-3 text-xs" aria-live="polite">
      <div className="rounded-lg border border-[#23252e] p-3"><span className="block text-gray-500 mb-1">En este equipo</span>
        <span className={copies.local === "valid" ? "text-emerald-400" : "text-amber-300"}>{
          copies.local === "valid" ? "Copia local íntegra" : copies.local === "missing" ? "Sin copia local" : "Archivo local en conflicto"}</span></div>
      <div className="rounded-lg border border-[#23252e] p-3"><span className="block text-gray-500 mb-1">Google Cloud Storage</span>
        <span className={copies.cloud === "available" ? "text-emerald-400" : "text-amber-300"}>{
          copies.cloud === "available" ? "Respaldo disponible en GCS" : copies.cloud === "missing" ? "Sin respaldo en GCS" : "Respaldo en conflicto"}</span></div>
    </div> : <p className="text-xs text-gray-500">Comprueba las copias para conocer su estado actual.</p>}
    {copies?.cloud === "available" && <p className="text-xs text-gray-500">La consulta confirma la existencia y tamaño del objeto. Los bytes se verifican al respaldar o recuperar.</p>}
    {copies?.local === "conflict" && <p className="text-xs text-amber-300">El archivo local difiere del registro. Pide al operador que lo preserve y revise antes de recuperar.</p>}
    <div className="flex flex-wrap gap-2">
      <button type="button" className={buttonClass} disabled={busy || copies?.local !== "valid" || copies?.cloud === "conflict"} onClick={() => void request("backup")}>Respaldar en GCS</button>
      <button type="button" className={buttonClass} disabled={busy || copies?.local !== "missing" || copies?.cloud !== "available"} onClick={() => void request("restore")}>Recuperar en este equipo</button>
    </div>
    {busy && <p role="status" className="text-xs text-cyan-300">{current.phase === "status" ? "Comprobando copias…" : current.phase === "backup" ? "Respaldando y verificando…" : "Recuperando y verificando…"}</p>}
    {current.error && <p role="alert" className="text-xs text-red-300">{current.error}</p>}
    {current.message && <p role="status" className="text-xs text-emerald-400">{current.message}</p>}
  </section>;
}
