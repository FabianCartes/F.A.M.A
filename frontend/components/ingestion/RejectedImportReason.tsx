"use client";

import { useEffect, useState } from "react";
import { importBase, importRequest, issuesPageSchema, type ImportJob } from "@/lib/api/datasetImports";

const folderReason = "Coloca cada audio WAV dentro de una carpeta con el nombre de su clase, directamente en la raíz del ZIP. No incluyas audios sueltos, una carpeta contenedora ni subcarpetas.";
const unavailableReason = "No se pudo consultar la razón del rechazo.";

/** Resolve every diagnostic page without exposing transport details or file paths. */
export default function RejectedImportReason({ job }: { job: ImportJob }) {
  const [result, setResult] = useState<{ reasons: string[] } | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      const reasons = new Set<string>();
      const visited = new Set<string>();
      let cursor: string | null = null;
      let remainingPages: number | undefined;
      let snapshot: string | number | null | undefined = job.preview_token ?? undefined;
      do {
        const url = `${importBase}/${job.id}/issues${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`;
        const response = await importRequest(url, { signal: controller.signal });
        if (controller.signal.aborted) return;
        const page = issuesPageSchema.parse(await response.json());
        if (controller.signal.aborted) return;
        if (snapshot !== undefined && page.snapshot !== snapshot) throw new Error("Changed snapshot");
        snapshot = page.snapshot;
        // A nonempty page must account for at least one issue in the initial total.
        remainingPages ??= page.total + 1;
        if (--remainingPages < 0) throw new Error("Invalid page count");
        for (const issue of page.issues) {
          if (issue.severity !== "error") continue;
          reasons.add(issue.code === "class_folders_required" ? folderReason : issue.action?.trim() || "No se pudo consultar el detalle de una de las razones del rechazo.");
        }
        cursor = page.next_cursor;
        if (cursor !== null) {
          if (!cursor || visited.has(cursor) || page.issues.length === 0) throw new Error("Invalid cursor");
          visited.add(cursor);
        }
      } while (cursor !== null);
      if (!controller.signal.aborted) setResult({ reasons: [...reasons] });
    }
    void load().catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [job.id, job.preview_token, attempt]);

  return <section aria-label="Razón del rechazo" className="space-y-2">
    {failed ? <><p role="alert">{unavailableReason}</p><button type="button" onClick={() => { setFailed(false); setResult(null); setAttempt(value => value + 1); }}>Reintentar consulta</button></>
      : result ? result.reasons.length ? result.reasons.map(reason => <p key={reason}>{reason}</p>)
        : <p>No hay una razón del rechazo disponible. Vuelve a consultar la importación.</p>
        : <p role="status">Consultando la razón del rechazo…</p>}
  </section>;
}
