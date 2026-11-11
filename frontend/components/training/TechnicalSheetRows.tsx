import type { ModelHistoryItem } from "@/lib/schemas/training";

const MISSING = "No registrado";
type Row = [label: string, value: string];

const present = <T,>(value: T | null | undefined): value is T => value !== null && value !== undefined;
const show = (value: number | string | null | undefined, suffix = "") => present(value) ? `${value}${suffix}` : MISSING;
const toggle = (enabled: boolean | null | undefined, detail = "") =>
  !present(enabled) ? MISSING : enabled ? `Activo${detail}` : "Desactivado";
const INITIALIZATION: Record<string, string> = {
  pretrained_constructor: "Preentrenado",
  constructor_default: "Pesos por defecto del constructor",
};

/** Recorded training parameters beyond the base four; older checkpoints show "No registrado". */
export function hyperparameterRows(item: ModelHistoryItem): Row[] {
  const h = item.hyperparameters ?? null;
  const patience = present(h?.early_stopping_patience) ? ` (paciencia ${h.early_stopping_patience} épocas)` : "";
  const mixup = present(h?.mixup_alpha) ? ` (α ${h.mixup_alpha})` : "";
  return [
    ["Weight Decay:", show(h?.weight_decay)],
    ["Early Stopping:", toggle(h?.early_stopping, patience)],
    ["Focal Gamma:", show(h?.focal_gamma)],
    ["Mixup:", toggle(h?.mixup_enabled, mixup)],
    ["Pitch Shift:", toggle(h?.pitch_shift_enabled)],
    ["Semilla:", show(h?.seed)],
    ["Inicialización:", present(h?.initialization_mode) ? INITIALIZATION[h.initialization_mode] ?? h.initialization_mode : MISSING],
    ["Época del checkpoint:", show(h?.checkpoint_epoch)],
    ["Peso en la tríada:", show(h?.ensemble_weight)],
  ];
}

/** Audio physics not covered by the base rows: STFT hop and dense windowing. */
export function audioPhysicsRows(item: ModelHistoryItem): Row[] {
  const w = item.windowing ?? null;
  const aggregation = present(w?.aggregation_mode)
    ? `${w.aggregation_mode}${present(w.gem_p) ? ` (GeM p ${w.gem_p})` : ""}` : MISSING;
  return [
    ["Hop Length:", show(item.audio_specs?.hop_length, " muestras")],
    ["Salto entre ventanas:", show(w?.hop_seconds, " s")],
    ["Agregación temporal:", aggregation],
    ["Umbral VAD:", show(w?.vad_threshold)],
  ];
}

export function SheetRows({ rows }: { rows: Row[] }) {
  return <>{rows.map(([label, value]) => <div key={label} className="flex justify-between items-center gap-2">
    <span className="text-gray-400 shrink-0">{label}</span>
    <span className={`font-mono font-medium text-right ${value === MISSING ? "text-gray-500" : "text-gray-200"}`}>{value}</span>
  </div>)}</>;
}
