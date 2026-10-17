"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import { importBase, importRequest, jsonRequest, type ImportDataset } from "@/lib/api/datasetImports";

const exportSchema = z.object({
  id: z.string(), dataset_id: z.string(), revision: z.number().int().nonnegative(),
  status: z.enum(["queued", "running", "succeeded", "failed", "deleting", "expired"]),
  progress: z.number().int().min(0).max(100), size_bytes: z.number().nullable(),
  sha256: z.string().nullable(), expires_at: z.number(), error: z.string().nullable(),
});
type ExportJob = z.infer<typeof exportSchema>;
const sessionSchema = z.object({ url: z.url(), expires_at: z.number() });
const buttonClass = "rounded border border-emerald-800 px-3 py-2 text-emerald-300 disabled:opacity-40";

export default function DatasetExportPanel({ token, datasets }: { token: string; datasets: ImportDataset[] }) {
  const [dataset, setDataset] = useState("");
  const [revision, setRevision] = useState("");
  const [job, setJob] = useState<ExportJob | null>(null);
  const [session, setSession] = useState<z.infer<typeof sessionSchema> | null>(null);
  const [history, setHistory] = useState<ExportJob[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(false);
  const epoch = useRef(0);
  const admission = useRef({ signature: "", key: "" });
  const jobId = job?.id, jobStatus = job?.status;

  useEffect(() => {
    if (!jobId || !["queued", "running"].includes(jobStatus ?? "")) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const response = await importRequest(token, `${importBase}/exports/${jobId}`, { signal: controller.signal });
        const value = exportSchema.parse(await response.json());
        if (controller.signal.aborted) return;
        setJob(current => current?.id === jobId ? value : current);
        if (["queued", "running"].includes(value.status)) timer = setTimeout(poll, 1000);
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "No se pudo consultar la exportación.");
          timer = setTimeout(poll, 3000);
        }
      }
    }
    void poll();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [jobId, jobStatus, token]);

  async function act(operation: (generation: number) => Promise<void>) {
    if (active.current) return;
    active.current = true;
    setBusy(true); setError("");
    const generation = epoch.current;
    try { await operation(generation); }
    catch (reason) {
      if (epoch.current === generation) setError(reason instanceof Error ? reason.message : "No se completó la exportación.");
    } finally { active.current = false; setBusy(false); }
  }

  async function admit(generation: number) {
    const signature = JSON.stringify([dataset, revision]);
    if (admission.current.signature !== signature) admission.current = { signature, key: crypto.randomUUID() };
    const response = await importRequest(token, `${importBase}/datasets/${dataset}/revisions/${revision}/exports`,
      jsonRequest({ request_key: admission.current.key }));
    const value = exportSchema.parse(await response.json());
    if (generation === epoch.current) { setJob(value); setSession(null); }
    admission.current = { signature: "", key: "" };
  }

  async function prepare(generation: number) {
    if (!job) return;
    const response = await importRequest(token, `${importBase}/exports/${job.id}/sessions`, jsonRequest({}));
    const value = sessionSchema.parse(await response.json());
    const url = new URL(value.url);
    if (url.protocol !== "https:" || url.username || url.password || url.origin === window.location.origin
        || url.pathname !== `${importBase}/exports/${job.id}/download`) {
      throw new Error("La ruta de descarga debe ser HTTPS y directa, fuera del proxy de Next.");
    }
    if (generation === epoch.current) setSession(value);
  }

  return <section aria-label="Exportaciones de datasets" className="space-y-3 border-t border-[#23252e] pt-4">
    <h3 className="font-semibold">Exportar desde revisión sincronizada</h3>
    <p>Reconstruye los WAV originales desde el manifiesto completo; no necesita el ZIP ni los audios locales.</p>
    <label>Dataset para exportar<select value={dataset} disabled={busy} onChange={event => {
      epoch.current += 1;
      setDataset(event.target.value);
      const selected = datasets.find(item => item.id === event.target.value);
      setRevision(selected?.revision === undefined ? "" : String(selected.revision));
      setJob(null); setSession(null); setHistory([]); setError("");
    }}><option value="">Seleccionar dataset</option>{datasets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    <label>Revisión para exportar<input type="number" min="0" step="1" value={revision} disabled={busy}
      onChange={event => setRevision(event.target.value)} /></label>
    <button className={buttonClass} disabled={busy || !dataset || !/^\d+$/.test(revision) || ["queued", "running"].includes(jobStatus ?? "")}
      onClick={() => void act(admit)}>Exportar revisión</button>
    <button className={buttonClass} disabled={busy || !dataset} onClick={() => void act(async generation => {
      const response = await importRequest(token, `${importBase}/datasets/${dataset}/exports`);
      const value = z.object({ exports: z.array(exportSchema).max(20) }).parse(await response.json());
      if (generation === epoch.current) setHistory(value.exports);
    })}>Recuperar exportaciones</button>
    {history.length > 0 && <ul>{history.map(value => <li key={value.id}><button disabled={busy}
      onClick={() => { setJob(value); setSession(null); }}>{value.id} · revisión {value.revision} · {value.status}</button></li>)}</ul>}
    {job && <>
      <p role="status">{job.status === "queued" ? "Exportación admitida; pendiente de ejecución" : job.status === "running" ? "Exportación en curso" : job.status === "succeeded" ? "Exportación completa" : "Exportación no disponible"}: revisión {job.revision} · {job.progress}%</p>
      {job.error && <p role="alert">No se completó la exportación. No hay un ZIP parcial disponible ({job.error}).</p>}
      {job.status === "succeeded" && <button className={buttonClass} disabled={busy} onClick={() => void act(prepare)}>{session ? "Renovar descarga" : "Preparar descarga"}</button>}
      {job.status === "succeeded" && session && <>
        <a href={session.url} target="_blank" rel="noreferrer" referrerPolicy="no-referrer" className="underline">Descargar ZIP exportado</a>
        <p>Sesión válida hasta {new Date(session.expires_at * 1000).toISOString()}. La descarga nativa admite reanudación; renueva la sesión si vence.</p>
      </>}
    </>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
