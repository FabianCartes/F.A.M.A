"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { z } from "zod";
import { importBase, importRequest, jsonRequest, saveDownload, jobSchema, limitsSchema,
  audioSchema, issueSchema, jobsPageSchema, executionSchema,
  type ImportJob, type ImportLimits } from "@/lib/api/datasetImports";
import ImportDetailPage from "./ImportDetailPage";
import { uploadImportReceipt, type ReceiptProgress } from "@/lib/api/datasetImportReceipt";

const classSchema = z.string();

const statusLabels: Record<string, string> = {
  receiving: "recibiendo", validating: "validando", needs_correction: "requiere corrección",
  ready: "lista para confirmar", committing: "confirmando; reintento recuperable", imported: "importada",
  failed: "fallida", cancelled: "cancelada", pending: "pendiente", running: "en curso", synced: "sincronizada", error: "error",
};
const inputClass = "mt-1 block w-full rounded-lg border border-[#2d303b] bg-[#111215] px-3 py-2 text-xs text-white focus:outline-none focus:border-emerald-500";
const buttonClass = "rounded-lg border border-emerald-800/60 bg-emerald-950/40 px-3 py-2 text-xs font-semibold text-emerald-400 hover:bg-emerald-900/50 transition-colors focus-visible:outline-2 focus-visible:outline-emerald-300 disabled:opacity-40 disabled:cursor-not-allowed";

export default function DatasetImportPanel({ sessionToken = "" }: { sessionToken?: string } = {}) {
  const [open, setOpen] = useState(false);
  const [started, setStarted] = useState(false);
  const [developmentMode, setDevelopmentMode] = useState(false);
  const [sessionRequired, setSessionRequired] = useState(false);
  // TODO: Receive the session from the dedicated access view; role policy is
  // deferred until that module exists. Never keep a second login in this modal.
  const token = sessionToken;
  const titleId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [limits, setLimits] = useState<ImportLimits | null>(null);
  const [history, setHistory] = useState<ImportJob[]>([]);
  const [job, setJob] = useState<ImportJob | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState("");
  const [receiptProgress, setReceiptProgress] = useState<ReceiptProgress | null>(null);
  const [error, setError] = useState("");
  const [localDataset, setLocalDataset] = useState<string | null>(null);
  const [historyNext, setHistoryNext] = useState<string | null>(null);
  const active = useRef(false);
  const requestKey = useRef("");
  const operationKey = useRef({ signature: "", key: "" });
  const executionId = job?.execution?.id;
  const executionStatus = job?.execution?.status;
  const importId = job?.id;
  const executing = executionStatus === "queued" || executionStatus === "running";
  const automatic = !job || job.preview.auto_import === true;
  const quota = job?.preview.quota;
  const quotaExceeded = quota && (quota.projected_bytes > quota.limit_bytes || quota.projected_files > quota.limit_files);

  useEffect(() => {
    if (!importId || !executionId || !["queued", "running"].includes(executionStatus ?? "")) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const endpoint = `${importBase}/${importId}/jobs/${executionId}`;
    async function poll() {
      try {
        const response = await importRequest(token, endpoint, { signal: controller.signal });
        const execution = executionSchema.parse(await response.json());
        if (controller.signal.aborted) return;
        if (execution.status === "queued" || execution.status === "running") {
          setJob(current => current && current.id === importId && current.execution?.id === executionId
            ? { ...current, execution } : current);
          timer = setTimeout(poll, 1000);
        } else {
          const response = await importRequest(token, `${importBase}/${importId}`, { signal: controller.signal });
          const current = jobSchema.parse(await response.json());
          if (!controller.signal.aborted) setJob(previous => previous && previous.id === importId && previous.execution?.id === executionId
            ? current : previous);
        }
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "No se pudo consultar el trabajo. Reintenta la consulta.");
          // Retry reads only, never re-submit the operation after a poll error.
          timer = setTimeout(poll, 3000);
        }
      }
    }
    void poll();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [importId, executionId, executionStatus, token]);

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previousOverflow = document.body.style.overflow;
    const background = Array.from(document.body.children).filter(element => !element.contains(dialog));
    const inertStates = background.map(element => element.hasAttribute("inert"));
    background.forEach(element => element.setAttribute("inert", ""));
    document.body.style.overflow = "hidden";
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(
      "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex='0']"
    )).filter(element => element.tagName === "SUMMARY" || !element.closest("details:not([open])"));
    focusable()[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
      if (event.key !== "Tab") return;
      const elements = focusable();
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first?.focus();
      }
    };
    const onFocus = (event: FocusEvent) => {
      if (event.target instanceof Node && !dialog.contains(event.target)) focusable()[0]?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("focusin", onFocus);
    const trigger = triggerRef.current;
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("focusin", onFocus);
      background.forEach((element, index) => { if (!inertStates[index]) element.removeAttribute("inert"); });
      document.body.style.overflow = previousOverflow;
      trigger?.focus();
    };
  }, [open]);

  async function act(message: string, operation: () => Promise<void>) {
    if (active.current) return;
    active.current = true;
    setBusy(message);
    setError("");
    try { await operation(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "No se completó la operación."); }
    finally { active.current = false; setBusy(""); }
  }

  async function refresh(sessionToken = token) {
    const jobs = await importRequest(sessionToken, importBase).then(r => r.json());
    const jobPage = jobsPageSchema.parse(jobs);
    setHistory(jobPage.imports); setHistoryNext(jobPage.next_cursor);
  }

  async function historyPage(cursor: string | null) {
    const response = await importRequest(token, `${importBase}${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`);
    const page = jobsPageSchema.parse(await response.json());
    setHistory(page.imports); setHistoryNext(page.next_cursor);
  }

  async function initialize() {
    const response = await importRequest(token, `${importBase}/access`);
    const access = z.object({ development_mode: z.boolean() }).parse(await response.json());
    setDevelopmentMode(access.development_mode);
    setSessionRequired(!access.development_mode && !token);
    if (!access.development_mode && !token) return;
    const configured = await importRequest(token, `${importBase}/limits`);
    const parsed = limitsSchema.parse(await configured.json());
    await refresh();
    setLimits(parsed);
  }

  async function validate() {
    let current = job;
    if (!current) {
      if (!file) throw new Error("Selecciona un archivo ZIP.");
      if (!requestKey.current) requestKey.current = crypto.randomUUID();
      const response = await importRequest(token, importBase, jsonRequest({ request_key: requestKey.current,
        name, description, target_id: null, layout: "class_folders", auto_import: true }));
      current = jobSchema.parse(await response.json());
      setJob(current);
    }
    if (current.status === "receiving") {
      if (!file) throw new Error("Selecciona el ZIP original para reintentar la recepción.");
      await uploadImportReceipt(token, current.id, file, setReceiptProgress);
      const response = await importRequest(token, `${importBase}/${current.id}`);
      current = jobSchema.parse(await response.json());
      setJob(current);
    }
    // Historical previews retain their reviewed root; new requests always use
    // the ZIP root and the server-enforced class-folder layout.
    await admit(current, "preview", { root: current.preview.root ?? "" });
  }

  async function admit(current: ImportJob, suffix: string, body: Record<string, unknown> = {}) {
    const signature = JSON.stringify([current.id, suffix, body]);
    if (operationKey.current.signature !== signature) operationKey.current = { signature, key: crypto.randomUUID() };
    const response = await importRequest(token, `${importBase}/${current.id}/${suffix}`,
      jsonRequest({ ...body, request_key: operationKey.current.key }));
    const execution = executionSchema.parse(await response.json());
    setJob({ ...current, execution });
    operationKey.current = { signature: "", key: "" };
  }

  async function action(suffix: string, body?: Record<string, unknown>) {
    if (!job) return;
    if (suffix !== "cancel") return admit(job, suffix, body);
    const response = await importRequest(token, `${importBase}/${job.id}/${suffix}`, jsonRequest(body ?? {}));
    setJob(jobSchema.parse(await response.json()));
    await refresh();
  }

  function reset() {
    setJob(null); setFile(null); setReceiptProgress(null); setLocalDataset(null); setError(""); requestKey.current = "";
  }

  return <>
    <button ref={triggerRef} className={buttonClass + " w-full sm:w-auto inline-flex items-center justify-center gap-2"} type="button" onClick={() => {
      setOpen(true);
      if (!limits) void act("Consultando configuración…", initialize);
    }} aria-haspopup="dialog" aria-expanded={open}>
      <svg aria-hidden="true" className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1M12 16V4m-4 4l4-4 4 4" /></svg>
      Importar dataset
    </button>
    {open && createPortal(<div data-testid="dataset-import-backdrop" className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={event => {
      if (event.target === event.currentTarget) setOpen(false);
    }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} className="w-full max-w-3xl max-h-[90dvh] overflow-y-auto rounded-2xl border border-[#23252e] bg-[#16171b] text-xs text-gray-300 shadow-2xl">
      <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-[#23252e] bg-[#16171b] px-5 py-4">
        <h2 id={titleId} className="text-sm font-bold text-white tracking-tight">Importar dataset</h2>
        <button type="button" aria-label="Cerrar importación" className="rounded-lg border border-[#2d303b] p-2 text-gray-400 hover:text-white hover:bg-[#252830] focus-visible:outline-2 focus-visible:outline-emerald-300" onClick={() => setOpen(false)}>
          <svg aria-hidden="true" className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 6l12 12M6 18L18 6" /></svg>
        </button>
      </div>
      <div className="p-5 space-y-4 leading-relaxed">
      <h3 className="text-sm font-semibold text-white">Instrucciones del archivo ZIP</h3>
      <p>Una carpeta por clase directamente en la raíz del ZIP, con audios WAV válidos dentro de cada clase, sin carpeta contenedora ni subcarpetas, aunque estén vacías.</p>
      <pre className="overflow-x-auto rounded-lg border border-[#23252e] bg-[#111215] p-3 text-xs text-emerald-300">{"chucao/audio_01.wav\ncolilarga/audio_01.wav"}</pre>
      <p>Organiza el ZIP antes de subirlo. El nombre de cada carpeta determina la clase; el ZIP se importará automáticamente solo si supera la validación del servidor, sin una segunda confirmación. No necesitas mantener esta ventana abierta.</p>
      <p>Se requiere al menos un WAV válido y único y una clase con contenido. Las clases vacías o pequeñas generan advertencias.</p>
      <p>Los duplicados de la misma clase se omiten; el mismo contenido con otra clase bloquea la importación. Se comparan bytes, no similitud acústica.</p>
      <p>Importar no inicia preparación ni entrenamiento. La copia local se conserva aunque falle GCS.</p>
      <p className="text-gray-400">Las colecciones importadas se conservan fuera del catálogo compartido.</p>
      {developmentMode && <p role="status" className="rounded-lg border border-amber-800/60 bg-amber-950/40 p-3 text-amber-300">Modo de desarrollo local: identidad de pruebas compartida en este equipo, sin acceso a colecciones de otros usuarios. No exponer este modo públicamente.</p>}
      {sessionRequired && <p role="status" className="rounded-lg border border-amber-800/60 bg-amber-950/40 p-3 text-amber-300">La vista de acceso está pendiente de integración. Para probar sin sesión, habilita el modo de desarrollo local siguiendo la guía de importación.</p>}
      {!limits && error && <button className={buttonClass} disabled={!!busy} onClick={() => void act("Consultando configuración…", initialize)}>Reintentar conexión</button>}
        {limits && <>
          <p>Límites del servidor: ZIP {limits.received_bytes} bytes; expansión {limits.expanded_bytes} bytes; {limits.entries} entradas; profundidad {limits.depth}; rutas {limits.path_bytes} bytes; WAV {limits.audio_bytes} bytes / {limits.audio_seconds} s; validación {limits.validation_seconds} s. Hasta {limits.concurrent_imports} importaciones activas y una operación de almacenamiento simultánea. Temporales: {limits.ttl_seconds} s; reserva libre: {limits.free_bytes} bytes.</p>
          <button className={buttonClass} disabled={!!busy} onClick={() => void act("Descargando ejemplo…", async () => {
            await saveDownload(await importRequest(token, `${importBase}/example.zip`), "dataset-example.zip");
          })}>Descargar ZIP de ejemplo sintético</button>
        </>}
        {!started ? <div className="border-t border-[#23252e] pt-4"><button className={buttonClass} disabled={!!busy || !limits} onClick={() => setStarted(true)}>Importar dataset</button></div> : <div className="space-y-4 border-t border-[#23252e] pt-4">
          <button className={buttonClass} disabled={!!busy} onClick={() => void act("Actualizando…", () => refresh())}>Actualizar importaciones</button>
          {limits && <>
          {!job && <div className="grid gap-3 sm:grid-cols-2">
            <label>Nombre del dataset<input className={inputClass} value={name} onChange={e => setName(e.target.value)} maxLength={150} disabled={!!busy} /></label>
            <label>Descripción<textarea className={inputClass} value={description} onChange={e => setDescription(e.target.value)} maxLength={2000} disabled={!!busy} /></label>
          </div>}
          {(!job || job.status === "receiving") && <label className="block">Archivo ZIP<input ref={fileInputRef} type="file" accept=".zip,application/zip" disabled={!!busy} onChange={e => {
            const selected = e.target.files?.[0] ?? null;
            if (selected && (selected.size > limits.received_bytes || !selected.name.toLowerCase().endsWith(".zip"))) {
              setError("Selecciona un ZIP dentro del límite recibido."); setFile(null);
            } else { setFile(selected); setError(""); }
          }} className={inputClass} /></label>}
          {file && <p className="text-gray-400">Archivo seleccionado: {file.name}</p>}
          {job?.status === "receiving" && <p>Para reanudar, selecciona el ZIP original y pulsa {automatic ? "Importar ZIP" : "Validar ZIP"}. Se comprobarán todos los fragmentos ya reconocidos antes de continuar; el nombre y el tamaño no prueban que sea el mismo archivo.</p>}
          {receiptProgress && <p role="status">Bytes reconocidos por el servidor: {receiptProgress.receipt.received_bytes} de {receiptProgress.receipt.size_bytes}.
            {receiptProgress.phase === "verifying" ? ` Verificando archivo para reanudar: ${receiptProgress.verified} de ${receiptProgress.receipt.received_bytes} bytes.` :
              receiptProgress.phase === "sealed" ? " Recepción completa; la validación de audios es un trabajo separado." :
                receiptProgress.phase === "sealing" ? " Verificando y finalizando recepción; todavía no valida los audios." : " Subiendo fragmentos secuenciales."}</p>}
          {(!job || ["receiving", "validating", "needs_correction", "ready"].includes(job.status)) && <>
            <button className={buttonClass} disabled={!!busy || executing || (!job && (!file || !name.trim()))} onClick={() => void act(automatic ? "Admitiendo importación…" : "Admitiendo validación…", validate)}>{automatic ? "Importar ZIP" : "Validar ZIP"}</button>
          </>}
        </>}
        {job && <div className="space-y-3">
          {job.execution && <p role="status">{executionStatus === "queued" ? "Trabajo admitido; pendiente de ejecución" : executionStatus === "running" ? "Trabajo en ejecución" : executionStatus === "succeeded" ? (job.status === "needs_correction" ? "Validación rechazada" : "Trabajo completado") : executionStatus === "cancelled" ? "Trabajo cancelado" : "Trabajo fallido"}: {job.execution.stage} · {job.execution.progress}%</p>}
          {job.execution?.error && <p role="alert">No se completó el trabajo ({job.execution.error.code}). Consulta el estado antes de reintentar.</p>}
          {job.execution?.status === "queued" && <button className={buttonClass} disabled={!!busy} onClick={() => void act("Cancelando trabajo…", async () => {
            const response = await importRequest(token, `${importBase}/${job.id}/jobs/${job.execution!.id}/cancel`, jsonRequest({}));
            setJob({ ...job, execution: executionSchema.parse(await response.json()) });
          })}>Cancelar trabajo pendiente</button>}
          {job.execution && ["failed", "cancelled"].includes(job.execution.status) && <button className={buttonClass} disabled={!!busy} onClick={() => void act("Admitiendo reintento…", () => admit(job, `jobs/${job.execution!.id}/retry`))}>Reintentar trabajo</button>}
          <p role="status">Importación {job.id}: {statusLabels[job.status] || job.status}</p>
          <p>Sincronización: {statusLabels[job.sync_status] || job.sync_status}</p>
          <p>Clases propuestas: {job.preview.class_count} · Archivos: {job.preview.file_count} · Nuevos: {job.preview.new_count ?? 0} · Duplicados internos: {job.preview.duplicate_count ?? 0} · Errores: {job.preview.error_count} · Advertencias: {job.preview.warning_count}</p>
          {automatic && job.status === "needs_correction" && <p role="alert">ZIP rechazado: revisa las incidencias, cancela esta solicitud y crea una nueva importación con el ZIP corregido. No se publicó contenido de este ZIP.</p>}
          {job.preview.quota && <section aria-label="Cuota del dataset">
            <p>Bytes únicos: actuales {job.preview.quota.current_bytes} + nuevos {job.preview.quota.new_bytes} = proyectados {job.preview.quota.projected_bytes} / límite {job.preview.quota.limit_bytes}.</p>
            <p>Archivos únicos: actuales {job.preview.quota.current_files} + nuevos {job.preview.quota.new_files} = proyectados {job.preview.quota.projected_files} / límite {job.preview.quota.limit_files}.</p>
            <p>La confirmación vuelve a comprobar la cuota y la revisión del destino.</p>
          </section>}
          {job.preview.duplicate_collection && <p>Colección ya importada: se detectó el mismo contenido y etiquetas.</p>}
          {job.preview_token && <div key={`${token}:${job.id}:${job.preview_token}`}>
            <ImportDetailPage token={token} endpoint={`${importBase}/${job.id}/files`} collection="files" label="archivos" schema={audioSchema} snapshot={job.preview_token}
              renderItem={f => <>{f.original_path} → {f.class_name}{f.duplicate || f.existing ? " (omitido)" : ""}{f.relative_path !== f.original_path ? ` · Ruta de exportación: ${f.relative_path}` : ""}</>} />
            <ImportDetailPage token={token} endpoint={`${importBase}/${job.id}/classes`} collection="classes" label="clases" schema={classSchema} snapshot={job.preview_token} renderItem={value => value} />
            <ImportDetailPage token={token} endpoint={`${importBase}/${job.id}/issues`} collection="issues" label="incidencias" schema={issueSchema} snapshot={job.preview_token}
              renderItem={issue => <span role={issue.severity === "error" ? "alert" : undefined}>{issue.severity === "warning" ? "Advertencia: " : ""}{issue.path}: {issue.code}. {issue.action}</span>} />
          </div>}
          {job.error && <p role="alert">{job.error === "expired" ? "La importación venció." : "La sincronización no está completa. Reintenta; la copia local se conserva."}</p>}
          {!automatic && ["ready", "committing"].includes(job.status) && <button className={buttonClass} disabled={!!busy || executing || !!quotaExceeded || job.preview.error_count > 0} onClick={() => void act("Admitiendo confirmación local…", () => action("confirm", { preview_token: job.preview_token }))}>Confirmar importación local</button>}
          {job.status === "imported" && <>
            <p>Importada localmente: {job.added_count} archivo(s) nuevo(s).{job.added_count === 0 ? " No hay novedades; no se creó un dataset vacío." : ""}</p>
            {job.dataset_id && <>
              <button className={buttonClass} disabled={!!busy || executing} onClick={() => void act("Admitiendo sincronización…", () => action("sync"))}>{job.sync_status === "running" || job.sync_status === "error" ? "Reanudar sincronización con GCS" : "Sincronizar con GCS"}</button>
              <p className="text-xs">Acción remota explícita. Si queda en curso, reanuda el siguiente lote. Verificados: {job.preview.synced_count}.</p>
              <button className={buttonClass} disabled={!!busy} onClick={() => setLocalDataset(job.dataset_id)}>Consultar archivos locales</button>
              {localDataset === job.dataset_id && <ImportDetailPage key={`${token}:${job.dataset_id}`} token={token} endpoint={`${importBase}/datasets/${job.dataset_id}/files`} collection="files" label="archivos locales" schema={audioSchema}
                renderItem={f => <button className="underline text-xs" disabled={!!busy} onClick={() => void act("Descargando audio…", async () => {
                await saveDownload(await importRequest(token, `${importBase}/datasets/${job.dataset_id}/files/${f.sha256}`), f.original_path.split("/").pop() || "audio.wav");
              })}>{f.original_path} ({f.class_name})</button>} />}
            </>}
          </>}
          {!["imported", "committing", "cancelled"].includes(job.status) && <button className={buttonClass} disabled={!!busy || executing} onClick={() => void act("Cancelando…", () => action("cancel"))}>Cancelar importación</button>}
          <button className={buttonClass} disabled={!!busy} onClick={reset}>Nueva importación</button>
        </div>}
        {history.length > 0 && <details><summary>Recuperar importaciones anteriores</summary><ul>{history.map(item => <li key={item.id}>
          <button disabled={!!busy} className="underline text-xs" onClick={() => {
            setFile(null); setReceiptProgress(null); setError("");
            if (fileInputRef.current) fileInputRef.current.value = "";
            setJob(item); setLocalDataset(null);
          }}>{item.id} — {statusLabels[item.status] || item.status}</button>
        </li>)}</ul>
          <button disabled={!!busy} onClick={() => void act("Consultando historial…", () => historyPage(null))}>Primera página de importaciones</button>
          <button disabled={!!busy || !historyNext} onClick={() => void act("Consultando historial…", () => historyPage(historyNext))}>Siguiente página de importaciones</button>
        </details>}
      </div>}
      {busy && <p role="status" aria-live="polite">{busy}</p>}
      {error && <p role="alert" className="rounded-lg border border-red-800/60 bg-red-950/40 p-3 text-red-300 break-words">{error}</p>}
      </div>
      </div>
    </div>, document.body)}
  </>;
}
