"use client";

import { useEffect, useState } from "react";
import { z } from "zod";
import { API_BASE_URL, apiFetch } from "@/lib/api";

const reviewSchema = z.object({
  total: z.number().int().nonnegative(),
  classes: z.record(z.string(), z.number().int().nonnegative()),
  not_local: z.object({ count: z.number().int().nonnegative() }),
  duplicates: z.object({ count: z.number().int().nonnegative() }),
  small_classes: z.array(z.object({ clase: z.string(), count: z.number().int().nonnegative() })),
  window_seconds: z.number().positive(),
  short_audios: z.object({ count: z.number().int().nonnegative(), threshold_seconds: z.number() }),
  long_audios: z.object({ count: z.number().int().nonnegative() }),
  class_median_seconds: z.record(z.string(), z.number()),
  duration_imbalance: z.boolean(),
  unknown_durations: z.number().int().nonnegative(),
});
type Review = z.infer<typeof reviewSchema>;

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;
const seconds = (value: number) => `${value.toLocaleString("es-CL", { maximumFractionDigits: 2 })} s`;

/** Informative dataset summary before partitioning; it never blocks a preview. */
export default function DatasetReview({ dataset, windowSeconds = 5 }: { dataset: string; windowSeconds?: number }) {
  const [review, setReview] = useState<Review | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const url = `${API_BASE_URL}/api/training/datasets/${encodeURIComponent(dataset)}/partitions/review?window_seconds=${windowSeconds}`;
    // Debounced: the window field changes on every keystroke.
    const timer = setTimeout(() => void apiFetch(url, { signal: controller.signal })
      .then(async response => {
        const parsed = reviewSchema.safeParse(response.ok ? await response.json() : null);
        if (controller.signal.aborted) return;
        if (parsed.success) { setReview(parsed.data); setFailed(false); } else setFailed(true);
      })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); }), 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [dataset, windowSeconds]);

  if (!review) return failed ? <p className="text-xs text-gray-500">No se pudo revisar el dataset en este momento.</p> : null;
  const classCount = Object.keys(review.classes).length;
  const clean = !review.not_local.count && !review.duplicates.count && !review.small_classes.length
    && !review.short_audios.count && !review.duration_imbalance;
  const windowText = seconds(review.window_seconds);
  return (
    <section aria-label="Revisión del dataset" className="rounded-lg bg-[#111215] border border-[#23252e] p-4 space-y-2 text-xs text-gray-300">
      <h3 className="font-semibold text-gray-200">Revisión del dataset</h3>
      <p>{plural(review.total, "audio registrado", "audios registrados")} en {plural(classCount, "clase", "clases")}.</p>
      {clean && <p className="text-emerald-300">Sin observaciones.</p>}
      {review.not_local.count > 0 && <p className="text-amber-200">{review.not_local.count === 1 ? "1 audio no está descargado en este equipo." : `${review.not_local.count} audios no están descargados en este equipo.`}</p>}
      {review.duplicates.count > 0 && <p className="text-amber-200">{plural(review.duplicates.count, "grupo", "grupos")} de audios duplicados.</p>}
      {review.small_classes.length > 0 && <p className="text-amber-200">Clases con pocos audios (menos de 10): {review.small_classes.map(item => `${item.clase} (${item.count})`).join(", ")}.</p>}
      {review.short_audios.count > 0 && <p className="text-amber-200">{`${review.short_audios.count === 1 ? "1 audio dura" : `${review.short_audios.count} audios duran`} menos de ${seconds(review.short_audios.threshold_seconds)} (la mitad de la ventana de ${windowText}) y se completarán con silencio.`}</p>}
      {review.long_audios.count > 0 && <p>{`${review.long_audios.count === 1 ? "1 audio dura" : `${review.long_audios.count} audios duran`} más de ${windowText}; se usa su tramo más activo.`}</p>}
      {review.duration_imbalance && <p className="text-amber-200">{`Las clases tienen duraciones muy distintas (${Object.entries(review.class_median_seconds)
        .map(([label, value]) => `${label} ${seconds(value)}`).join(", ")}); el modelo podría aprender la duración en vez del sonido.`}</p>}
      {review.unknown_durations > 0 && <p className="text-gray-500">{plural(review.unknown_durations, "audio", "audios")} sin duración registrada.</p>}
      <p className="text-gray-500">Es informativo: no impide previsualizar ni guardar una versión.</p>
    </section>
  );
}
