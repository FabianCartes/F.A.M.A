"use client";

import { useEffect, useState } from "react";
import { z } from "zod";
import { API_BASE_URL, apiFetch } from "@/lib/api";

const reviewSchema = z.object({
  total: z.number().int().nonnegative(),
  classes: z.record(z.string(), z.number().int().nonnegative()),
  not_local: z.object({ count: z.number().int().nonnegative(), files: z.array(z.string()) }),
  duplicates: z.object({ count: z.number().int().nonnegative(), groups: z.array(z.array(z.string())) }),
  small_classes: z.array(z.object({ clase: z.string(), count: z.number().int().nonnegative() })),
  atypical_durations: z.object({ count: z.number().int().nonnegative(), files: z.array(z.object({
    file_path: z.string(), clase: z.string(), duration_seconds: z.number(), class_median_seconds: z.number(),
  })) }),
  unknown_durations: z.number().int().nonnegative(),
});
type Review = z.infer<typeof reviewSchema>;

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;
const seconds = (value: number) => `${Number(value.toFixed(2))} s`;

/** Informative dataset summary before partitioning; it never blocks a preview. */
export default function DatasetReview({ dataset }: { dataset: string }) {
  const [review, setReview] = useState<Review | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void apiFetch(`${API_BASE_URL}/api/training/datasets/${encodeURIComponent(dataset)}/partitions/review`, { signal: controller.signal })
      .then(async response => {
        const parsed = reviewSchema.safeParse(response.ok ? await response.json() : null);
        if (controller.signal.aborted) return;
        if (parsed.success) { setReview(parsed.data); setFailed(false); } else setFailed(true);
      })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [dataset]);

  if (!review) return failed ? <p className="text-xs text-gray-500">No se pudo revisar el dataset en este momento.</p> : null;
  const classCount = Object.keys(review.classes).length;
  const clean = !review.not_local.count && !review.duplicates.count && !review.small_classes.length && !review.atypical_durations.count;
  return (
    <section aria-label="Revisión del dataset" className="rounded-lg bg-[#111215] border border-[#23252e] p-4 space-y-2 text-xs text-gray-300">
      <h3 className="font-semibold text-gray-200">Revisión del dataset</h3>
      <p>{plural(review.total, "audio registrado", "audios registrados")} en {plural(classCount, "clase", "clases")}.</p>
      {clean && <p className="text-emerald-300">Sin observaciones.</p>}
      {review.not_local.count > 0 && <details>
        <summary className="cursor-pointer text-amber-200">{review.not_local.count === 1 ? "1 audio no está descargado en este equipo." : `${review.not_local.count} audios no están descargados en este equipo.`}</summary>
        <ul className="mt-1 space-y-1 font-mono break-words text-gray-400">{review.not_local.files.map(path => <li key={path}>{path}</li>)}</ul>
      </details>}
      {review.duplicates.count > 0 && <details>
        <summary className="cursor-pointer text-amber-200">{plural(review.duplicates.count, "grupo", "grupos")} de audios duplicados.</summary>
        <ul className="mt-1 space-y-1 font-mono break-words text-gray-400">{review.duplicates.groups.map(group => <li key={group.join("|")}>{group.join(" = ")}</li>)}</ul>
      </details>}
      {review.small_classes.length > 0 && <p className="text-amber-200">Clases con pocos audios (menos de 10): {review.small_classes.map(item => `${item.clase} (${item.count})`).join(", ")}.</p>}
      {review.atypical_durations.count > 0 && <details>
        <summary className="cursor-pointer text-amber-200">{plural(review.atypical_durations.count, "audio", "audios")} con duración atípica para su clase.</summary>
        <ul className="mt-1 space-y-1 break-words text-gray-400">{review.atypical_durations.files.map(item => <li key={item.file_path}>
          {`${item.file_path} · ${seconds(item.duration_seconds)} (mediana de la clase: ${seconds(item.class_median_seconds)})`}</li>)}</ul>
      </details>}
      {review.unknown_durations > 0 && <p className="text-gray-500">{plural(review.unknown_durations, "audio", "audios")} sin duración registrada.</p>}
      <p className="text-gray-500">Es informativo: no impide previsualizar ni guardar una versión.</p>
    </section>
  );
}
