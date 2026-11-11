"use client";

import { useEffect, useState } from "react";
import TriadComponentsEditor, { triadWeightsFromPercents } from "@/components/training/TriadComponentsEditor";
import { getTriadComposition, reviseTriadWeights, triadCompositionId, type TriadComposition } from "@/lib/api/triadCompositions";

const percent = (weight: number) => String(Number((weight * 100).toFixed(6)));

/** Standard triad as one model: its three components and weights, plus weights-only revision. */
export default function TriadCompositionPanel({ modelId, onRevised }: {
  modelId: string;
  /** Resolves with an error message when the new version could not be selected. */
  onRevised: (newModelId: string) => Promise<string | null>;
}) {
  const id = triadCompositionId(modelId);
  const [loaded, setLoaded] = useState<{ modelId: string; composition?: TriadComposition; error?: string } | null>(null);
  const [percents, setPercents] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (id === null) return;
    const controller = new AbortController();
    getTriadComposition(id, controller.signal).then(composition => {
      setPercents(composition.components.map(c => percent(c.weight)));
      setError(null);
      setLoaded({ modelId, composition });
    }, (failure: unknown) => {
      if (!controller.signal.aborted) setLoaded({ modelId, error: failure instanceof Error ? failure.message : "No se pudo cargar la tríada." });
    });
    return () => controller.abort();
  }, [id, modelId]);

  if (id === null) return null;
  const current = loaded?.modelId === modelId ? loaded : null;
  const composition = current?.composition;
  const { valid, weights } = triadWeightsFromPercents(percents);

  async function save() {
    if (!composition || !valid || saving) return;
    setSaving(true);
    setError(null);
    try {
      const revision = await reviseTriadWeights(composition.id, weights);
      const problem = await onRevised(revision.model_id);
      if (problem) setError(problem);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "No se pudo revisar los pesos.");
    } finally {
      setSaving(false);
    }
  }

  return <section role="region" aria-label="Composición de la tríada" className="mt-5 border-t border-[#23252e]/70 pt-4 space-y-3">
    <h3 className="text-xs font-semibold text-gray-200">Composición de la tríada</h3>
    {!current && <p role="status" className="text-xs text-gray-400">Cargando la composición…</p>}
    {current?.error && <p role="alert" className="text-xs text-amber-300">{current.error}</p>}
    {composition && <>
      <p className="text-[11px] text-gray-400">Versión v{composition.version}{composition.latest ? " · última versión" : " · versión anterior"}. Revisar los pesos crea una versión nueva sin reentrenar.</p>
      <TriadComponentsEditor componentLabels={composition.components.map(c => c.catalogue_id)} disabled={!composition.latest || saving}
        models={percents.map(weight => ({ architecture: "", weight }))}
        onArchitecture={() => undefined}
        onPercent={(index, value) => setPercents(previous => previous.map((p, i) => i === index ? value : p))} />
      <button type="button" disabled={!composition.latest || !valid || saving} onClick={() => void save()}
        className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-700 text-white disabled:opacity-50 disabled:cursor-not-allowed">
        Guardar nueva versión de pesos
      </button>
      {!composition.latest && <p className="text-[11px] text-gray-400">Solo la última versión admite revisión de pesos.</p>}
      {error && <p role="alert" className="text-xs text-amber-300">{error}</p>}
    </>}
  </section>;
}
