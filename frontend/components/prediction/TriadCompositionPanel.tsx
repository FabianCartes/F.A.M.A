"use client";

import { useEffect, useState } from "react";
import { getTriadComposition, triadCompositionId, type TriadComposition } from "@/lib/api/triadCompositions";

const percent = (weight: number) => `${Number((weight * 100).toFixed(6))} %`;

/** Standard triad as one model: its three components and the weights fixed at training (ADR 0082). */
export default function TriadCompositionPanel({ modelId }: { modelId: string }) {
  const id = triadCompositionId(modelId);
  const [loaded, setLoaded] = useState<{ modelId: string; composition?: TriadComposition; error?: string } | null>(null);

  useEffect(() => {
    if (id === null) return;
    const controller = new AbortController();
    getTriadComposition(id, controller.signal).then(composition => {
      setLoaded({ modelId, composition });
    }, (failure: unknown) => {
      if (!controller.signal.aborted) setLoaded({ modelId, error: failure instanceof Error ? failure.message : "No se pudo cargar la tríada." });
    });
    return () => controller.abort();
  }, [id, modelId]);

  if (id === null) return null;
  const current = loaded?.modelId === modelId ? loaded : null;
  const composition = current?.composition;

  return <section role="region" aria-label="Composición de la tríada" className="mt-5 border-t border-[#23252e]/70 pt-4 space-y-3">
    <h3 className="text-xs font-semibold text-gray-200">Composición de la tríada</h3>
    {!current && <p role="status" className="text-xs text-gray-400">Cargando la composición…</p>}
    {current?.error && <p role="alert" className="text-xs text-amber-300">{current.error}</p>}
    {composition && <>
      <p className="text-[11px] text-gray-400">Porcentajes fijados en el entrenamiento.</p>
      <ul className="space-y-1.5">
        {composition.components.map((component, index) => <li key={component.id_modelo}
          className="flex items-center justify-between gap-3 text-xs text-gray-300">
          <span>Componente {index + 1} · {component.catalogue_id}</span>
          <span className="text-gray-100 font-semibold">{percent(component.weight)}</span>
        </li>)}
      </ul>
    </>}
  </section>;
}
