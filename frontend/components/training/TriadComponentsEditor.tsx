'use client';

export const TRIAD_ARCHITECTURES = [
  ['EfficientNet-B0', 'EfficientNet-B0 (Transfer Learning · Pitch Shift)'],
  ['ConvNeXt-Nano', 'ConvNeXt-Nano (Arquitectura Moderna)'],
  ['ResNet-34d', 'ResNet-34d (ResNet Profunda)'],
  ['PANNs-CNN14', 'PANNs-CNN14 (Audio industrial)'],
  ['AudioCNN', 'AudioCNN (Baseline Convolucional FAMA)'],
] as const;

export interface TriadComponentDraft { architecture: string; weight: number | string }

/**
 * Percentages -> weights. Weights are plain floats (p / 100) and are never rescaled:
 * a total other than exactly 100 % is invalid, not silently corrected.
 */
export function triadWeightsFromPercents(percents: Array<number | string>) {
  const parsed = percents.map(p => (String(p).trim() === '' ? NaN : Number(p)));
  const total = parsed.reduce((acc, p) => acc + p, 0);
  const weights = parsed.map(p => p / 100);
  const sum = weights.reduce((acc, w) => acc + w, 0);
  const valid = parsed.length === 3 && parsed.every(p => Number.isFinite(p) && p >= 0)
    && Math.abs(total - 100) <= 1e-9 && Math.abs(sum - 1) <= 1e-9;
  return { total, weights, valid };
}

export default function TriadComponentsEditor({models, disabled, onArchitecture, onPercent}: {
  models: TriadComponentDraft[]; disabled?: boolean;
  onArchitecture: (index: number, architecture: string) => void; onPercent: (index: number, value: string) => void;
}) {
  const {total, valid} = triadWeightsFromPercents(models.map(m => m.weight));
  const shown = Number.isFinite(total) ? Math.round(total * 1e6) / 1e6 : NaN;
  return <div className="space-y-2" aria-label="Componentes de la tríada" role="group">
    {models.map((m, i) => <div key={i} className="grid grid-cols-[1fr_6rem] gap-2 items-end">
      <label className="text-[11px] text-gray-400 block font-medium">Arquitectura del componente {i + 1}
        <select className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 mt-1 font-mono disabled:opacity-60"
          disabled={disabled} value={m.architecture} onChange={e => onArchitecture(i, e.target.value)}>
          {TRIAD_ARCHITECTURES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <label className="text-[11px] text-gray-400 block font-medium">Porcentaje del componente {i + 1}
        <input type="number" min="0" max="100" step="any" className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-2 py-2 text-xs text-gray-200 mt-1 font-mono disabled:opacity-60"
          disabled={disabled} value={m.weight} onChange={e => onPercent(i, e.target.value)} />
      </label>
    </div>)}
    <p role="status" className={`text-xs font-mono ${valid ? 'text-emerald-400' : 'text-amber-400'}`}>
      {valid ? 'Total: 100 %' : `Total: ${Number.isNaN(shown) ? '—' : shown} % · debe sumar exactamente 100 % para continuar`}
    </p>
  </div>;
}

export interface TriadProgressState {
  status: string; phase?: string; currentIndex: number; total: number; currentArchitecture: string;
  components: Array<{ model_index?: number; architecture?: string }>; available: boolean;
}

/** Phase and availability only; per-component metrics are never merged into triad metrics. */
export function TriadProgressSummary({state}: {state: TriadProgressState}) {
  const terminal = ['completed', 'failed', 'stopped'].includes(state.status);
  const joint = state.phase === 'joint_evaluation';
  return <section aria-label="Progreso de la tríada" className="space-y-1 text-xs text-gray-300">
    {state.status === 'training' && !joint && <p>Componente {state.currentIndex} de {state.total}{state.currentArchitecture ? ` · ${state.currentArchitecture}` : ''}</p>}
    {joint && state.status === 'evaluating' && <p>Evaluación conjunta de la tríada en curso.</p>}
    {state.components.map((c, i) => <p key={i} className="text-gray-400">Componente {c.model_index ?? i + 1}: {c.architecture ?? 'sin arquitectura'} · completado</p>)}
    {state.available && <p role="status" className="text-emerald-400">Tríada disponible para inferencia</p>}
    {!state.available && terminal && <p role="alert" className="text-amber-400">La tríada no está disponible para inferencia. Los resultados individuales se conservan según lo reportado.</p>}
  </section>;
}
