"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { API_BASE_URL, apiFetch } from "@/lib/api";
import type { DatasetItem } from "./DatasetInventory";
import { z } from "zod";

const uploadResultSchema = z.object({
  status: z.enum(["completed", "partial", "failed"]), uploaded: z.number().int().nonnegative(),
  skipped: z.number().int().nonnegative().default(0), failed: z.number().int().nonnegative(),
  db_persisted: z.boolean(), files: z.array(z.string()),
  errors: z.array(z.object({ filename: z.string(), error: z.string(), code: z.string().optional() })),
});

export interface UploadLimits { max_file_bytes: number; max_batch_bytes: number; }

interface Props {
  datasets: DatasetItem[];
  canCreate: boolean;
  busy: boolean;
  onUploaded: () => Promise<void>;
  onBusyChange: (value: boolean) => void;
  limits?: UploadLimits | null;
}

export default function DatasetUpload({ datasets, canCreate, busy, onUploaded, onBusyChange, limits }: Props) {
  const [target, setTarget] = useState("");
  const [newName, setNewName] = useState("");
  const [label, setLabel] = useState("");
  const [selectedClass, setSelectedClass] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const dataset = target === ":new:" && canCreate ? newName.trim() : target;
  const allowed = canCreate || datasets.some(item => item.id === target);
  const classes = datasets.find(item => item.id === target)?.classes ?? [];
  const requestedClass = classes.length > 0 && selectedClass !== ":new:"
    ? (classes.includes(selectedClass) ? selectedClass : "")
    : label.trim();
  const classLabel = classes.includes(requestedClass) ? requestedClass
    : classes.find(name => name.toLocaleLowerCase("es") === requestedClass.toLocaleLowerCase("es")) ?? requestedClass;

  useEffect(() => () => { request.current?.abort(); }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || busy || !allowed || !dataset || !classLabel || files.length === 0) return;
    if (limits && files.some(file => file.size > limits.max_file_bytes)) {
      setError("Uno de los audios supera el límite por archivo. Elige archivos más pequeños.");
      return;
    }
    if (limits && files.reduce((total, file) => total + file.size, 0) > limits.max_batch_bytes) {
      setError("La selección supera el límite total del envío. Divide los audios en varios envíos.");
      return;
    }
    const body = new FormData();
    body.set("dataset_name", dataset);
    body.set("class_label", classLabel);
    for (const file of files) body.append("files", file);
    submitting.current = true;
    setUploading(true); onBusyChange(true); setMessage(""); setError("");
    const controller = new AbortController();
    request.current = controller;
    try {
      const response = await apiFetch(`${API_BASE_URL}/api/ingestion/upload`, { method: "POST", body, signal: controller.signal });
      const value = await response.json().catch(() => null);
      if (!response.ok) throw new Error(value && typeof value.detail === "string" ? value.detail : "No se pudo confirmar la subida.");
      const decoded = uploadResultSchema.safeParse(value);
      if (!decoded.success) throw new Error("No se pudo confirmar la subida. Actualiza el inventario antes de reintentar.");
      const result = decoded.data;
      if (controller.signal.aborted) return;
      const summary = `${result.uploaded ?? 0} archivo(s) subido(s), ${result.skipped ?? 0} ya existente(s), ${result.failed ?? 0} con error.`;
      const persisted = result.db_persisted === true;
      setMessage(`${summary} ${persisted ? "Registro en la base de datos confirmado." : "Registro en la base de datos sin confirmar; revisa el resultado antes de reintentar."}`);
      const failures: { filename?: string; error?: string }[] = Array.isArray(result.errors) ? result.errors : [];
      if (failures.length) setError(failures.map(item => `${item.filename ?? "Audio"}: ${item.error ?? "No se pudo confirmar su subida."}`).join(" "));
      if (result.status === "completed" && persisted && result.failed === 0) {
        setFiles([]);
        if (fileInput.current) fileInput.current.value = "";
      } else if (persisted && failures.length) {
        const rejected = new Set(failures.map(item => item.filename));
        setFiles(files.filter(file => rejected.has(file.name)));
      }
      await onUploaded();
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "No se pudo confirmar la subida. Revisa el inventario antes de reintentar.");
    } finally {
      submitting.current = false;
      if (!controller.signal.aborted) { setUploading(false); onBusyChange(false); }
    }
  }

  const inputStyle = "w-full mt-1 rounded-lg border border-[#373a46] bg-[#111215] p-2 text-sm text-gray-200 disabled:opacity-50";
  return <section aria-label="Subir audios" className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4 shadow-sm">
    <div><h2 className="text-sm font-semibold text-gray-200">Subir audios</h2>
      <p className="text-xs text-gray-400 mt-2">Elige el dataset y la clase de los audios que incorporarás al bucket de esta instalación.</p></div>
    {limits && <p className="text-xs text-gray-500">Máximo por archivo: {limits.max_file_bytes >= 1048576 ? `${limits.max_file_bytes / 1048576} MiB` : `${limits.max_file_bytes} bytes`}. Máximo por envío: {limits.max_batch_bytes >= 1048576 ? `${limits.max_batch_bytes / 1048576} MiB` : `${limits.max_batch_bytes} bytes`}.</p>}
    {limits === null && <p role="alert" className="text-xs text-amber-300">La subida no está disponible en este momento. Solicita al administrador revisar su configuración.</p>}
    {!canCreate && datasets.length === 0 && <p className="text-xs text-amber-300">Necesitas un dataset asignado para subir audios.</p>}
    <form onSubmit={submit} className="space-y-4">
      <fieldset disabled={busy || uploading || limits === null || (!canCreate && datasets.length === 0)} className="grid gap-4 sm:grid-cols-2 text-xs text-gray-300">
        <label>Dataset de destino<select aria-label="Dataset de destino" value={target} onChange={event => { setTarget(event.target.value); setLabel(""); setSelectedClass(""); setMessage(""); setError(""); }} required className={inputStyle}>
          <option value="">Selecciona un dataset</option>
          {datasets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          {canCreate && <option value=":new:">Crear un dataset nuevo</option>}
        </select></label>
        {classes.length > 0 ? <label>Clase de los audios<select aria-label="Clase de los audios" value={selectedClass} onChange={event => { setSelectedClass(event.target.value); setLabel(""); }} required className={inputStyle}>
          <option value="">Selecciona una clase</option>
          {classes.map(name => <option key={name} value={name}>{name}</option>)}
          <option value=":new:">Añadir una clase nueva…</option>
        </select></label> : <label>Clase de los audios<input value={label} onChange={event => setLabel(event.target.value)} disabled={!dataset} required maxLength={100} className={inputStyle} placeholder="Nombre de la primera clase" /></label>}
        {classes.length > 0 && selectedClass === ":new:" && <label>Nombre de la nueva clase<input value={label} onChange={event => setLabel(event.target.value)} required maxLength={100} className={inputStyle} placeholder="Escribe solo si esta clase aún no existe" /></label>}
        {target === ":new:" && canCreate && <label>Nombre del nuevo dataset<input value={newName} onChange={event => setNewName(event.target.value)} required maxLength={100} className={inputStyle} /></label>}
        <label className="sm:col-span-2">Audios<input ref={fileInput} type="file" multiple accept=".wav,.mp3,.flac,.ogg" onChange={event => { setFiles(Array.from(event.target.files ?? [])); setError(""); setMessage(""); }} className={inputStyle} /></label>
      </fieldset>
      {files.length > 0 && <p className="text-xs text-gray-400">{files.length} archivo(s) seleccionado(s): {files.map(file => file.name).join(", ")}</p>}
      <button type="submit" disabled={busy || uploading || limits === null || !allowed || !dataset || !classLabel || files.length === 0} className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed">{uploading ? "Subiendo audios…" : "Subir audios a GCS"}</button>
      {uploading && <p role="status" className="text-xs text-gray-400">Enviando los archivos seleccionados. La confirmación aparecerá al terminar.</p>}
      {message && <p role="status" className="text-xs text-gray-300">{message}</p>}
      {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
    </form>
  </section>;
}
