'use client';

import { useState, type FormEvent } from 'react';
import { importedTrainingApi } from '@/lib/api/importedTrainingApi';
import { triadWeightsFromPercents } from '@/components/training/TriadComponentsEditor';

/** True only for a private composition whose catalogue metrics carry its three weights. */
export function triadCompositionWeights(model?: { architecture?: unknown; metrics?: unknown } | null): number[] | null {
  if (model?.architecture !== 'ImportedTriad') return null;
  const weights = (model.metrics as { weights?: unknown } | null | undefined)?.weights;
  return Array.isArray(weights) && weights.length === 3 && weights.every(w => typeof w === 'number' && Number.isFinite(w))
    ? weights as number[] : null;
}

const toPercent = (weight: number) => String(Number((weight * 100).toFixed(6)));

export default function TriadWeightRevision({modelId, weights, onRevised}: {
  modelId: string; weights: number[]; onRevised: (newModelId: string) => void | Promise<void>;
}) {
  const [percents, setPercents] = useState(() => weights.map(toPercent));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const {total, weights: enteredWeights, valid} = triadWeightsFromPercents(percents);
  // Compare against the displayed precision so rounding cannot suggest a new revision.
  const applied = enteredWeights.every((w, i) => Number.isFinite(w)
    && Math.abs(w - Number(toPercent(weights[i])) / 100) <= 1e-9);
  const shown = Number.isFinite(total) ? Math.round(total * 1e6) / 1e6 : NaN;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid || busy || applied) return;
    setBusy(true);
    setError(null);
    try {
      const revised = await importedTrainingApi.reviseTriadWeights(modelId, enteredWeights);
      await onRevised(revised.id);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : 'No se pudo evaluar la nueva combinación.');
    } finally {
      setBusy(false);
    }
  }

  return <form aria-label="Ajustar pesos de la tríada" onSubmit={submit} className="rounded-lg p-3.5 border bg-[#111215] border-[#252834] space-y-2">
    <p className="text-[11px] text-gray-300 font-medium">Pesos actuales: {weights.map(w => `${toPercent(w)} %`).join(' · ')}</p>
    <p className="text-[11px] text-gray-400">Cambiar los pesos crea una nueva versión evaluada y conserva la anterior.</p>
    <div className="grid grid-cols-3 gap-2">
      {percents.map((value, i) => <label key={i} className="text-[11px] text-gray-400 block font-medium">Porcentaje del componente {i + 1}
        <input type="number" min="0" max="100" step="any" disabled={busy} value={value}
          onChange={e => setPercents(prev => prev.map((p, j) => (j === i ? e.target.value : p)))}
          className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-2 py-2 text-xs text-gray-200 mt-1 font-mono disabled:opacity-60" />
      </label>)}
    </div>
    <p role="status" className={`text-xs font-mono ${applied || valid ? 'text-emerald-400' : 'text-amber-400'}`}>
      {applied ? 'Esta versión ya está evaluada con estos pesos.'
        : valid ? 'Estos pesos requieren evaluar una nueva versión.'
        : `Total: ${Number.isNaN(shown) ? '—' : shown} % · debe sumar exactamente 100 %`}
    </p>
    {busy && <p role="status" className="text-xs text-blue-300">Evaluando nueva combinación…</p>}
    {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
    <button type="submit" disabled={!valid || busy || applied}
      className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 text-white disabled:opacity-50">{applied ? 'Pesos aplicados' : 'Evaluar nuevos pesos'}</button>
  </form>;
}
