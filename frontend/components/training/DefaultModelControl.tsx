"use client";

import { useState } from "react";
import { apiFetch, API_BASE_URL } from "@/lib/api";

const FALLBACK = "No se pudo activar como predeterminado. Actualiza el historial y vuelve a intentarlo.";

/**
 * Installation default for Prediction: a badge for everyone, and for an administrator
 * the action that designates this model or triad. Activating never grants access.
 */
export default function DefaultModelControl({ kind, id, active, administrator, onActivated }: {
  kind: "model" | "triad"; id: number; active: boolean; administrator: boolean; onActivated: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (active) {
    return <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-950/60 text-emerald-300 border border-emerald-800/60">Predeterminado</span>;
  }
  if (!administrator) return null;
  async function activate() {
    setBusy(true); setError("");
    const path = kind === "model" ? `/api/training/models/${id}/activate` : `/api/triad-compositions/${id}/activate`;
    try {
      const response = await apiFetch(`${API_BASE_URL}${path}`, { method: "POST" });
      const body = await response.json().catch(() => null);
      if (!response.ok || (kind === "model" && body?.success !== true)) {
        // Model activation reports refusals as success=false; triads use HTTP status and detail.
        const reason = kind === "model" ? body?.error : body?.detail;
        setError(typeof reason === "string" && reason ? reason : FALLBACK);
        return;
      }
      await onActivated();
    } catch {
      setError(FALLBACK);
    } finally {
      setBusy(false);
    }
  }
  return <span className="inline-flex flex-col items-end gap-1">
    <button type="button" disabled={busy} onClick={() => void activate()}
      className="text-[11px] text-emerald-300 hover:text-white px-2.5 py-1 rounded bg-emerald-950/60 hover:bg-emerald-900/60 border border-emerald-800/60 disabled:opacity-60">
      {busy ? "Activando…" : "Activar como predeterminado"}
    </button>
    {error && <span role="alert" className="text-[11px] text-amber-400 max-w-[16rem] text-right">{error}</span>}
  </span>;
}
