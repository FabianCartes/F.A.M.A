"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useOptionalWebSession } from "@/components/auth/SessionBoundary";
import { z } from "zod";
import { importBase, importRequest, jsonRequest, saveDownload, jobSchema, limitsSchema,
  audioSchema, issueSchema, jobsPageSchema, executionSchema, classesPageSchema,
  type ImportJob, type ImportLimits } from "@/lib/api/datasetImports";
import ImportDetailPage from "./ImportDetailPage";
import RejectedImportReason from "./RejectedImportReason";
import { uploadImportReceipt, type ReceiptProgress } from "@/lib/api/datasetImportReceipt";

const classSchema = z.string();

function formatWeightLimit(bytes: number) {
  const megabytes = bytes / 1_000_000;
  const useGigabytes = megabytes > 1000;
  const value = useGigabytes ? megabytes / 1000 : megabytes;
  // Truncate rather than advertise a rounded maximum above the server limit.
  const display = Math.floor(value * 100) / 100;
  return `${display.toLocaleString('es', { maximumFractionDigits: 2 })} ${useGigabytes ? 'GB' : 'MB'}`;
}

function CompletedImportSummary({ job, datasetName }: { job: ImportJob; datasetName?: string }) {
  const [classes, setClasses] = useState<string[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      const response = await importRequest(`${importBase}/${job.id}/classes`, { signal: controller.signal });
      const page = classesPageSchema.parse(await response.json());
      if (job.preview_token && page.snapshot !== job.preview_token) throw new Error("Las clases cambiaron. Vuelve a consultar la importación.");
      if (!controller.signal.aborted) setClasses(page.classes);
    }
    void load().catch(reason => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "No se pudieron consultar las clases.");
    });
    return () => controller.abort();
  }, [job.id, job.preview_token]);
  return <section aria-label="Resumen de importación" className="space-y-2 rounded-lg border border-[#2d303b] bg-[#111215] p-4">
    <h3 className="font-semibold text-white">{datasetName || "Nombre del dataset no disponible"}</h3>
    <p>Importada localmente: {job.added_count} archivo(s) nuevo(s).</p>
    {job.added_count > 0 && job.execution && (job.execution.status === "succeeded"
      ? <p>Publicada en GCS y en el inventario compartido; quedas asignado a este dataset.</p>
      : ["queued", "running"].includes(job.execution.status)
        ? <p>Publicando en GCS y en el inventario compartido…</p>
        : <p>La publicación en GCS no terminó; los audios siguen guardados en local. Usa «Reintentar trabajo» para completarla.</p>)}
    <p>Tamaño: {formatWeightLimit(job.preview.total_size_bytes)}</p>
    <p>Clases: {job.preview.class_count}</p>
    {classes.length > 0 && <p className="break-words">{classes.join(", ")}</p>}
    {job.preview.class_count > classes.length && classes.length > 0 && <p>Y {job.preview.class_count - classes.length} clases más.</p>}
    {job.preview.warning_count > 0 && <p>{job.preview.warning_count} advertencia(s) durante la validación.</p>}
    {job.added_count === 0 && <p>Sin audios nuevos; no se creó un dataset vacío.</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}

const statusLabels: Record<string, string> = {
  receiving: "recibiendo", validating: "validando", needs_correction: "requiere corrección",
  ready: "lista para confirmar", committing: "confirmando; reintento recuperable", imported: "importada",
  failed: "fallida", cancelled: "cancelada",
};
const inputClass = "mt-1 block w-full rounded-lg border border-[#2d303b] bg-[#111215] px-3 py-2 text-xs text-white focus:outline-none focus:border-emerald-500";
const buttonClass = "rounded-lg border border-emerald-800/60 bg-emerald-950/40 px-3 py-2 text-xs font-semibold text-emerald-400 hover:bg-emerald-900/50 transition-colors focus-visible:outline-2 focus-visible:outline-emerald-300 disabled:opacity-40 disabled:cursor-not-allowed";

export default function DatasetImportPanel({ onCatalogChange, triggerLabel = "Importar dataset", datasetNames = {} }: {
  onCatalogChange?: () => void; triggerLabel?: string; datasetNames?: Record<string, string>;
} = {}) {
  const [open, setOpen] = useState(false);
  const [started, setStarted] = useState(false);
  const [developmentMode, setDevelopmentMode] = useState(false);
  const [sessionRequired, setSessionRequired] = useState(false);
  // Reuse the confirmed opaque session; never embed another login here.
  const webUser = useOptionalWebSession();
  const titleId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [limits, setLimits] = useState<ImportLimits | null>(null);
  const [history, setHistory] = useState<ImportJob[]>([]);
  const [job, setJob] = useState<ImportJob | null>(null);
  const rejected = job?.status === "cancelled" && job.preview.error_count > 0;
  const [name, setName] = useState("");
  const [createdImport, setCreatedImport] = useState<{ id: string; name: string } | null>(null);
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState("");
  const [receiptProgress, setReceiptProgress] = useState<ReceiptProgress | null>(null);
  const [error, setError] = useState("");
  const active = useRef(false);
  const requestKey = useRef("");
  const operationKey = useRef({ signature: "", key: "" });
  const localDataset = job?.status === "imported" ? job.dataset_id : null;
  const localDatasetName = localDataset ? datasetNames[localDataset] : undefined;
  useEffect(() => {
    if (localDataset) onCatalogChange?.();
  }, [localDataset, onCatalogChange]);
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
        const response = await importRequest(endpoint, { signal: controller.signal });
        const execution = executionSchema.parse(await response.json());
        if (controller.signal.aborted) return;
        if (execution.status === "queued" || execution.status === "running") {
          setJob(current => current && current.id === importId && current.execution?.id === executionId
            ? { ...current, execution } : current);
          timer = setTimeout(poll, 1000);
        } else {
          const response = await importRequest(`${importBase}/${importId}`, { signal: controller.signal });
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
  }, [importId, executionId, executionStatus]);

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

  async function refresh() {
    const jobs = await importRequest(`${importBase}?latest=true`).then(r => r.json());
    const jobPage = jobsPageSchema.parse(jobs);
    setHistory(jobPage.imports.slice(0, 10));
  }

  async function initialize() {
    const response = await importRequest(`${importBase}/access`);
    const access = z.object({ development_mode: z.boolean(), authenticated: z.boolean().default(false), available: z.boolean().default(true), reason: z.string().optional() }).parse(await response.json());
    if (!access.available) throw new Error(access.reason ?? "El servicio ZIP no está disponible en este equipo.");
    setDevelopmentMode(access.development_mode);
    setSessionRequired(!access.development_mode && !access.authenticated && !webUser);
    if (!access.development_mode && !access.authenticated && !webUser) return;
    const configured = await importRequest(`${importBase}/limits`);
    const parsed = limitsSchema.parse(await configured.json());
    await refresh();
    setLimits(parsed);
  }

  async function validate() {
    let current = job;
    if (!current) {
      if (!file) throw new Error("Selecciona un archivo ZIP.");
      if (!requestKey.current) requestKey.current = crypto.randomUUID();
      const response = await importRequest(importBase, jsonRequest({ request_key: requestKey.current,
        name, description, target_id: null, layout: "class_folders", auto_import: true }));
      current = jobSchema.parse(await response.json());
      setJob(current);
      setCreatedImport({ id: current.id, name });
    }
    if (current.status === "receiving") {
      if (!file) throw new Error("Selecciona el ZIP original para reintentar la recepción.");
      await uploadImportReceipt(current.id, file, setReceiptProgress);
      const response = await importRequest(`${importBase}/${current.id}`);
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
    const response = await importRequest(`${importBase}/${current.id}/${suffix}`,
      jsonRequest({ ...body, request_key: operationKey.current.key }));
    const execution = executionSchema.parse(await response.json());
    setJob({ ...current, execution });
    operationKey.current = { signature: "", key: "" };
  }

  async function action(suffix: string, body?: Record<string, unknown>) {
    if (!job) return;
    if (suffix !== "cancel") return admit(job, suffix, body);
    const response = await importRequest(`${importBase}/${job.id}/${suffix}`, jsonRequest(body ?? {}));
    setJob(jobSchema.parse(await response.json()));
    await refresh();
  }

  function reset() {
    setJob(null); setFile(null); setReceiptProgress(null); setError(""); requestKey.current = "";
  }

  return <>
    <button ref={triggerRef} className={buttonClass + " w-full sm:w-auto inline-flex items-center justify-center gap-2"} type="button" onClick={() => {
      setOpen(true);
      if (!limits) void act("Consultando configuración…", initialize);
    }} aria-haspopup="dialog" aria-expanded={open}>
      <svg aria-hidden="true" className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1M12 16V4m-4 4l4-4 4 4" /></svg>
      {triggerLabel}
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
      <>
      <h3 className="text-sm font-semibold text-white">Instrucciones del archivo ZIP</h3>
      <ul aria-label="Cómo preparar el ZIP" className="list-disc space-y-2 pl-5">
        <li>Una carpeta por clase en la raíz del ZIP, con audios WAV dentro; sin carpeta contenedora ni subcarpetas.</li>
        <li>Incluye al menos un WAV válido y único. Las clases vacías o pequeñas generan advertencias.</li>
        <li>Los duplicados de la misma clase se omiten; el mismo audio en clases distintas bloquea la importación. Se comparan bytes, no similitud acústica.</li>
        <li>El ZIP se importará automáticamente solo si supera la validación del servidor, sin una segunda confirmación. No necesitas mantener esta ventana abierta.</li>
        <li>Importar no inicia preparación ni entrenamiento. Al confirmar, los audios se publican en GCS y en el inventario compartido con un nombre único, y quedas asignado al dataset; el administrador lo asigna a los demás.</li>
      </ul>
      <pre className="overflow-x-auto rounded-lg border border-[#23252e] bg-[#111215] p-3 text-xs text-emerald-300">{"chucao/audio_01.wav\ncolilarga/audio_01.wav"}</pre>
      {developmentMode && <p role="status" className="rounded-lg border border-amber-800/60 bg-amber-950/40 p-3 text-amber-300">Modo de desarrollo local: identidad de pruebas compartida en este equipo, sin acceso a colecciones de otros usuarios. No exponer este modo públicamente.</p>}
      {sessionRequired && <p role="status" className="rounded-lg border border-amber-800/60 bg-amber-950/40 p-3 text-amber-300">Inicia sesión para acceder a tus importaciones. <Link href="/login" className="underline">Abrir acceso</Link>. El modo de desarrollo local conserva su alcance separado según la guía de importación.</p>}
      {!limits && error && <button className={buttonClass} disabled={!!busy} onClick={() => void act("Consultando configuración…", initialize)}>Reintentar conexión</button>}
        {limits && <>
          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-white">Límites de peso</h3>
            <ul aria-label="Límites de peso" className="list-disc space-y-1 pl-5">
              <li>ZIP: hasta {formatWeightLimit(limits.received_bytes)}</li>
              <li>Contenido descomprimido: hasta {formatWeightLimit(limits.expanded_bytes)}</li>
              <li>Cada audio WAV: hasta {formatWeightLimit(limits.audio_bytes)}</li>
            </ul>
          </div>
          <button className={buttonClass} disabled={!!busy} onClick={() => void act("Descargando ejemplo…", async () => {
            await saveDownload(await importRequest(`${importBase}/example.zip`), "dataset-example.zip");
          })}>Descargar ZIP de ejemplo sintético</button>
        </>}
        </>
        {!started ? <div className="border-t border-[#23252e] pt-4"><button className={buttonClass} disabled={!!busy || !limits} onClick={() => setStarted(true)}>Importar dataset</button></div> : <div className="space-y-4 border-t border-[#23252e] pt-4">
          <button className={buttonClass} disabled={!!busy} onClick={() => void act("Actualizando…", () => refresh())}>Actualizar importaciones</button>
          {limits && <>
          {!job && <div className="grid gap-3 sm:grid-cols-2">
            <label>Nombre del dataset<input className={inputClass} value={name} onChange={e => setName(e.target.value)} maxLength={100} disabled={!!busy} /></label>
            <label>Descripción<textarea className={inputClass} value={description} onChange={e => setDescription(e.target.value)} maxLength={2000} disabled={!!busy} /></label>
          </div>}
          {(!job || job.status === "receiving") && <label className="block">Archivo ZIP<input ref={fileInputRef} type="file" accept=".zip,application/zip" disabled={!!busy} onChange={e => {
            const selected = e.target.files?.[0] ?? null;
            if (selected && (selected.size > limits.received_bytes || !selected.name.toLowerCase().endsWith(".zip"))) {
              setError("Selecciona un ZIP dentro del límite recibido."); setFile(null);
            } else { setFile(selected); setError(""); }
          }} className={inputClass} /></label>}
          {file && !rejected && <p className="text-gray-400">Archivo seleccionado: {file.name}</p>}
          {job?.status === "receiving" && <p>Para reanudar, selecciona el ZIP original y pulsa {automatic ? "Importar ZIP" : "Validar ZIP"}. Se comprobarán todos los fragmentos ya reconocidos antes de continuar; el nombre y el tamaño no prueban que sea el mismo archivo.</p>}
          {receiptProgress && !rejected && job?.status !== "imported" && <div role="status" aria-label="Progreso del ZIP">
            <p>Subido: {formatWeightLimit(receiptProgress.receipt.received_bytes)} de {formatWeightLimit(receiptProgress.receipt.size_bytes)}</p>
            <p>{receiptProgress.phase === "verifying"
              ? `Verificando el ZIP para reanudar: ${formatWeightLimit(receiptProgress.verified)} de ${formatWeightLimit(receiptProgress.receipt.received_bytes)}`
              : receiptProgress.phase === "sealed" ? "ZIP recibido. Preparando la validación de los audios."
                : receiptProgress.phase === "sealing" ? "Comprobando el ZIP recibido…" : "Subiendo el ZIP…"}</p>
          </div>}
          {(!job || ["receiving", "validating", "needs_correction", "ready"].includes(job.status)) && <>
            <button className={buttonClass} disabled={!!busy || executing || (!job && (!file || !name.trim()))} onClick={() => void act(automatic ? "Importando ZIP…" : "Validando ZIP…", validate)}>{automatic ? "Importar ZIP" : "Validar ZIP"}</button>
          </>}
        </>}
        {job && <div className="space-y-3">
          {job.status === "cancelled" && job.preview.error_count > 0 ? <>
            <p className="font-semibold text-white">ZIP rechazado</p>
            <RejectedImportReason key={`${job.id}:${job.preview_token}`} job={job} />
          </> : <>
          {job.status !== "imported" && <section aria-label="Importación en curso" className="space-y-2 rounded-lg border border-[#2d303b] bg-[#111215] p-4">
            <h3 className="font-semibold text-white">{(job.dataset_id && datasetNames[job.dataset_id]) || (createdImport?.id === job.id ? createdImport.name : job.archive_name) || "Importación de ZIP"}</h3>
            <p role="status">{executionStatus === "queued" ? "En espera para importar" : executionStatus === "running"
              ? (job.execution?.kind === "confirm" ? "Guardando el dataset…" : "Validando los audios…")
              : job.status === "receiving" ? "Subiendo el ZIP…" : job.status === "validating" ? "Validando los audios…"
                : job.status === "committing" ? "Guardando el dataset…" : `Estado: ${statusLabels[job.status] || "pendiente de consulta"}`}</p>
            {job.preview.file_count > 0 && <p>Audios: {job.preview.file_count} · Clases: {job.preview.class_count}</p>}
            {job.preview.total_size_bytes > 0 && <p>Tamaño: {formatWeightLimit(job.preview.total_size_bytes)}</p>}
          </section>}
          {job.execution?.error && <p role="alert">{job.status === "cancelled" ? "La importación falló y quedó cancelada. Crea una nueva importación con el ZIP corregido." : "No se pudo completar la importación. Consulta su estado antes de reintentar."}</p>}
          {job.execution?.status === "queued" && <button className={buttonClass} disabled={!!busy} onClick={() => void act("Cancelando trabajo…", async () => {
            const response = await importRequest(`${importBase}/${job.id}/jobs/${job.execution!.id}/cancel`, jsonRequest({}));
            setJob({ ...job, execution: executionSchema.parse(await response.json()) });
          })}>Cancelar trabajo pendiente</button>}
          {job.status !== "cancelled" && job.execution && ["failed", "cancelled"].includes(job.execution.status) && <button className={buttonClass} disabled={!!busy} onClick={() => void act("Admitiendo reintento…", () => admit(job, `jobs/${job.execution!.id}/retry`))}>Reintentar trabajo</button>}
          {job.status === "imported" ? <CompletedImportSummary key={`${job.id}:${job.preview_token}`} job={job} datasetName={localDatasetName || (createdImport?.id === job.id ? createdImport.name : job.archive_name ?? undefined)} /> : !executing && ["ready", "needs_correction", "failed", "cancelled"].includes(job.status) ? <>
          <p>Clases propuestas: {job.preview.class_count} · Archivos: {job.preview.file_count} · Nuevos: {job.preview.new_count ?? 0} · Duplicados internos: {job.preview.duplicate_count ?? 0} · Errores: {job.preview.error_count} · Advertencias: {job.preview.warning_count}</p>
          {job.status === "cancelled" && job.preview.error_count > 0 && <p role="alert">ZIP rechazado: la importación quedó cancelada. Revisa las incidencias y crea una nueva importación con el ZIP corregido. No se publicó contenido de este ZIP.</p>}
          {automatic && job.status === "needs_correction" && <p role="alert">ZIP rechazado: revisa las incidencias, cancela esta solicitud y crea una nueva importación con el ZIP corregido. No se publicó contenido de este ZIP.</p>}
          {job.preview.quota && <section aria-label="Cuota del dataset">
            <p>Espacio del dataset tras importar: {formatWeightLimit(job.preview.quota.projected_bytes)} de {formatWeightLimit(job.preview.quota.limit_bytes)} disponibles.</p>
            <p>Audios del dataset tras importar: {job.preview.quota.projected_files} de {job.preview.quota.limit_files} permitidos.</p>
            <p>La confirmación vuelve a comprobar la cuota y la revisión del destino.</p>
          </section>}
          {job.preview.duplicate_collection && <p>Colección ya importada: se detectó el mismo contenido y etiquetas.</p>}
          {job.preview_token && <div key={`${job.id}:${job.preview_token}`}>
            <ImportDetailPage endpoint={`${importBase}/${job.id}/files`} collection="files" label="archivos" schema={audioSchema} snapshot={job.preview_token}
              renderItem={f => <>{f.original_path} → {f.class_name}{f.duplicate || f.existing ? " (omitido)" : ""}{f.relative_path !== f.original_path ? ` · Ruta local: ${f.relative_path}` : ""}</>} />
            <ImportDetailPage endpoint={`${importBase}/${job.id}/classes`} collection="classes" label="clases" schema={classSchema} snapshot={job.preview_token} renderItem={value => value} />
            <ImportDetailPage endpoint={`${importBase}/${job.id}/issues`} collection="issues" label="incidencias" schema={issueSchema} snapshot={job.preview_token}
              renderItem={issue => <span role={issue.severity === "error" ? "alert" : undefined}>{issue.severity === "warning" ? "Advertencia: " : ""}{issue.path}: {issue.code}. {issue.action}</span>} />
          </div>}
          </> : null}
          {job.error && <p role="alert">{job.error === "expired" ? "La importación venció." : job.status === "cancelled" ? "La importación quedó cancelada por un error. Puedes iniciar una nueva importación; sus diagnósticos se conservan." : "No se pudo completar la importación. Consulta su estado antes de reintentar."}</p>}
          {!automatic && ["ready", "committing"].includes(job.status) && <button className={buttonClass} disabled={!!busy || executing || !!quotaExceeded || job.preview.error_count > 0} onClick={() => void act("Admitiendo confirmación local…", () => action("confirm", { preview_token: job.preview_token }))}>Confirmar importación local</button>}
          {!["imported", "committing", "cancelled"].includes(job.status) && <button className={buttonClass} disabled={!!busy || executing} onClick={() => void act("Cancelando…", () => action("cancel"))}>Cancelar importación</button>}
          </>}
          <button className={buttonClass} disabled={!!busy} onClick={reset}>Nueva importación</button>
        </div>}
        {history.length > 0 && <details><summary>Recuperar importaciones anteriores</summary><ul aria-label="Últimas 10 importaciones">{history.map(item => <li key={item.id}>
          <button disabled={!!busy} className="underline text-xs" onClick={() => {
            setFile(null); setReceiptProgress(null); setError("");
            if (fileInputRef.current) fileInputRef.current.value = "";
            setJob(item);
          }}>{item.archive_name || 'Nombre del ZIP no disponible'} — {item.created_at != null && Number.isFinite(item.created_at) && !Number.isNaN(new Date(item.created_at * 1000).getTime()) ? new Date(item.created_at * 1000).toLocaleString('es-CL', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : 'Fecha no disponible'} — {statusLabels[item.status] || item.status}</button>
        </li>)}</ul>
        </details>}
      </div>}
      {busy && <p role="status" aria-live="polite">{busy}</p>}
      {error && <p role="alert" className="rounded-lg border border-red-800/60 bg-red-950/40 p-3 text-red-300 break-words">{error}</p>}
      </div>
      </div>
    </div>, document.body)}
  </>;
}
