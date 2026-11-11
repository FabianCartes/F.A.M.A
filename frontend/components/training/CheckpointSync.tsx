"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";
import { API_BASE_URL, apiFetch } from "@/lib/api";
import DatasetConfirmationDialog from "@/components/ingestion/DatasetConfirmationDialog";

const syncSchema = z.object({
  model_id: z.number().int(),
  action: z.enum(["already_synced", "uploaded", "restored"]),
  local: z.literal("valid"),
  cloud: z.literal("available"),
  transfer_verified: z.literal(true),
});
const statusSchema = z.object({ models: z.array(z.object({ model_id: z.number().int(), synced: z.boolean() })) });

export type SyncAction = z.infer<typeof syncSchema>["action"];

const SUCCESS: Record<SyncAction, string> = {
  already_synced: "Las copias local y en GCS ya estaban sincronizadas. Se verificaron su tamaño y SHA-256.",
  uploaded: "Se respaldó el checkpoint en GCS y se verificaron su tamaño y SHA-256.",
  restored: "Se recuperó el checkpoint desde GCS en este equipo y se verificaron su tamaño y SHA-256. El modelo conserva su activación anterior.",
};
const FALLBACK = "No se pudo sincronizar el checkpoint. Revisa GCS, la conexión y el espacio local; puedes reintentar.";

/**
 * Batch "synced" flags for the listed models. The flag only means both copies exist with the
 * registered size; when GCS cannot be queried every model keeps the "Sincronizar en GCS" label.
 */
export function useCheckpointSyncStatus(modelIds: number[]) {
  const key = modelIds.join(",");
  const [synced, setSynced] = useState<ReadonlySet<number>>(new Set());
  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await apiFetch(`${API_BASE_URL}/api/training/models/checkpoints/sync-status`, { signal: controller.signal });
        const parsed = statusSchema.safeParse(response.ok ? await response.json() : null);
        if (!controller.signal.aborted) {
          setSynced(new Set(parsed.success ? parsed.data.models.filter(model => model.synced).map(model => model.model_id) : []));
        }
      } catch {
        if (!controller.signal.aborted) setSynced(new Set());
      }
    })();
    return () => controller.abort();
  }, [key]);
  const markSynced = useCallback((modelId: number) => setSynced(previous => new Set(previous).add(modelId)), []);
  return { synced, markSynced };
}

type Outcome = { ok: true; message: string } | { ok: false; message: string };

export function CheckpointSyncButton({ modelId, synced, onSynced }: {
  modelId: number;
  synced: boolean;
  onSynced: (action: SyncAction) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  const close = useCallback(() => setOutcome(null), []);

  async function synchronize() {
    if (busy) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    let result: Outcome;
    try {
      const response = await apiFetch(`${API_BASE_URL}/api/training/models/${modelId}/checkpoint/sync`, {
        method: "POST", signal: controller.signal,
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = typeof payload === "object" && payload !== null && "detail" in payload ? payload.detail : null;
        throw new Error(typeof detail === "string" ? detail : FALLBACK);
      }
      const parsed = syncSchema.safeParse(payload);
      if (!parsed.success || parsed.data.model_id !== modelId) {
        throw new Error("La sincronización no quedó confirmada. Vuelve a sincronizar para comprobar las copias.");
      }
      result = { ok: true, message: SUCCESS[parsed.data.action] };
      onSynced(parsed.data.action);
    } catch (failure: unknown) {
      result = { ok: false, message: failure instanceof Error && failure.message ? failure.message : FALLBACK };
    }
    if (controller.signal.aborted) return;
    setBusy(false);
    setOutcome(result);
  }

  const style = synced
    ? "bg-emerald-950/60 text-emerald-300 border-emerald-800/60 hover:border-emerald-600"
    : "bg-[#1c1e24] text-gray-200 border-[#2d303b] hover:bg-[#252832]";
  return <>
    <button ref={trigger} type="button" disabled={busy} onClick={() => void synchronize()}
      title={synced ? "Ambas copias registradas; presiona para verificarlas de nuevo." : "Comprueba las copias y sincroniza el checkpoint con GCS."}
      className={`text-[11px] px-2.5 py-1 rounded border transition-colors disabled:opacity-50 disabled:cursor-wait ${style}`}>
      {busy ? "Sincronizando…" : synced ? "Sincronizado" : "Sincronizar en GCS"}
    </button>
    {outcome && <DatasetConfirmationDialog title={outcome.ok ? "Checkpoint sincronizado" : "No se pudo sincronizar"}
      onClose={close} returnFocus={trigger}>
      <p role={outcome.ok ? "status" : "alert"} className={outcome.ok ? "text-emerald-300" : "text-red-300"}>{outcome.message}</p>
      <div className="flex justify-end">
        <button type="button" onClick={close}
          className="text-xs px-3 py-2 rounded-lg border border-[#2d303b] bg-[#1c1e24] text-gray-200 hover:bg-[#252832]">Cerrar</button>
      </div>
    </DatasetConfirmationDialog>}
  </>;
}
