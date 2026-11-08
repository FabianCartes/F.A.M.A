"use client";

import { useState, useEffect, useRef, useCallback, type ReactNode } from "react";
import DatasetConfirmationDialog from "@/components/ingestion/DatasetConfirmationDialog";
import { API_BASE_URL } from "@/lib/api";
import { useOptionalWebSession } from "@/components/auth/SessionBoundary";
import {
  getPendingFeedback,
  approveFeedback,
  rejectFeedback,
} from "@/lib/api/feedbackApi";
import { PendingFeedbackItem } from "@/lib/schemas/feedback";
import FeedbackSyncPanel from "@/components/feedback/FeedbackSyncPanel";
import DatasetImportPanel from "@/components/ingestion/DatasetImportPanel";
import DatasetExportDialog from "@/components/ingestion/DatasetExportDialog";
import ImportDetailPage from "@/components/ingestion/ImportDetailPage";
import { importBase, importRequest, catalogPageSchema, audioSchema, saveDownload,
  jobsPageSchema, executionSchema, jsonRequest, deletePrivateDataset, type CatalogDataset } from "@/lib/api/datasetImports";

// ============================================================================
// INTERFACES DEL MODELO DE DOMINIO DE INGESTA (RF_02 / RF_06 / ADR 0013)
// ============================================================================
export interface IngestionViewProps {
  onNavigate?: (view: string) => void;
  sessionToken?: string;
}

interface StorageStatus {
  connected: boolean;
  bucket: string;
  total_objects: number;
  total_bytes: number;
  error?: string | null;
}

interface DatasetItem {
  id: string;
  name: string;
  classes?: string[];
  class_count?: number;
  file_count: number;
  total_size_bytes: number;
  last_modified: string | null;
  local_file_count: number;
  gcs_file_count?: number | null;
  is_synced: boolean;
  domain?: "bioacoustic" | "industrial";
  domain_label?: string;
  source?: "gcs" | "local";
  gcs_available?: boolean;
}

interface DatasetFile {
  name: string;
  class_name: string;
  path: string;
  size_bytes: number;
  updated: string | null;
}

interface SyncDatasetResult {
  dataset: string;
  downloaded: number;
  skipped: number;
  failed: number;
  preprocessed: number;
  db_persisted?: boolean;
  preprocess_info?: { failed?: number } | null;
  files?: { cleanup_pending?: boolean }[];
}

interface LogEntry {
  id: string;
  timestamp: string;
  level: "INFO" | "WARN" | "SUCCESS" | "ERROR";
  message: string;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

function uploadDateLabel(value?: string | null): string {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "Fecha de carga no disponible";
  return `Cargado el ${date.toLocaleString("es-CL", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  })}`;
}

function DatasetFolderIcon() {
  return <svg aria-hidden="true" focusable="false" data-dataset-folder className="w-3.5 h-3.5 text-emerald-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
  </svg>;
}

type UploadExecution = ReturnType<typeof executionSchema.parse>;
type PrivateUpload = { name: string; execution: UploadExecution };

// Keyed by session in the view: abort reads/admissions and discard all private
// selection/monitoring state when ownership changes. The server owns execution.
function PrivateDatasetUpload({ token, datasets, selectedIds, loading, onCatalogChange, children }: {
  token: string; datasets: CatalogDataset[]; selectedIds: string[]; loading: boolean;
  onCatalogChange: () => void; children: (busy: boolean) => ReactNode;
}) {
  const [confirmation, setConfirmation] = useState<{ datasets: CatalogDataset[]; ids: string[] } | null>(null);
  const closeConfirmation = useCallback(() => setConfirmation(null), []);
  const triggerRef = useRef<HTMLButtonElement>(null);
  // Catalog replacement invalidates the confirmation, even for unchanged IDs.
  const dialogOpen = confirmation !== null && confirmation.datasets === datasets && confirmation.ids === selectedIds && !loading;
  const [admitting, setAdmitting] = useState(false);
  const [uploads, setUploads] = useState<PrivateUpload[]>([]);
  const [error, setError] = useState("");
  const active = useRef(false);
  const lifetime = useRef<AbortController | null>(null);
  // Preserve the key across ambiguous admission failures. Retrying must not
  // duplicate an operation whose response was lost, including partial batches.
  const operations = useRef(new Map<string, { key: string; source: string; execution?: UploadExecution }>());
  const selected = datasets.filter(dataset => selectedIds.includes(dataset.id));
  const executing = uploads.some(({ execution }) => ["queued", "running"].includes(execution.status));
  const busy = admitting || executing;

  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!executing) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const updates = await Promise.all(uploads.map(async upload => {
          const current = upload.execution;
          if (!["queued", "running"].includes(current.status)) return upload;
          const response = await importRequest(token, `${importBase}/${encodeURIComponent(current.import_id)}/jobs/${encodeURIComponent(current.id)}`, { signal: controller.signal });
          return { ...upload, execution: executionSchema.parse(await response.json()) };
        }));
        if (controller.signal.aborted) return;
        setUploads(updates);
        setError("");
        if (updates.some((upload, index) => upload.execution.status === "succeeded" && uploads[index].execution.status !== "succeeded")) onCatalogChange();
      } catch (reason) {
        if (controller.signal.aborted) return;
        setError(`No se pudo consultar la subida; se reintentará la consulta sin reenviar. ${reason instanceof Error ? reason.message : ""}`);
        timer = setTimeout(poll, 3000);
      }
    }
    timer = setTimeout(poll, 1000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [uploads, executing, token, onCatalogChange]);

  async function uploadSelection() {
    if (active.current || busy || !selected.length || !dialogOpen) return;
    setConfirmation(null);
    const controller = lifetime.current;
    if (!controller || controller.signal.aborted) return;
    active.current = true;
    setAdmitting(true);
    setError("");
    setUploads([]);
    try {
      const sources = new Map<string, string>();
      const cursors = new Set<string>();
      let cursor: string | null = null;
      do {
        const response = await importRequest(token, `${importBase}${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`, { signal: controller.signal });
        const page = jobsPageSchema.parse(await response.json());
        if (controller.signal.aborted) return;
        for (const source of page.imports) {
          if (source.status === "imported" && source.dataset_id && selectedIds.includes(source.dataset_id) && !sources.has(source.dataset_id)) sources.set(source.dataset_id, source.id);
        }
        cursor = page.next_cursor;
        if (cursor && cursors.has(cursor)) throw new Error("El historial no avanzó; actualiza las importaciones antes de reintentar.");
        if (cursor) cursors.add(cursor);
      } while (cursor && sources.size < selected.length);
      const missing = selected.filter(dataset => !sources.has(dataset.id));
      if (missing.length) throw new Error(`No hay una importación confirmada en el historial para: ${missing.map(dataset => dataset.name).join(", ")}. No se inició la selección.`);
      for (const dataset of selected) {
        if (controller.signal.aborted) return;
        const source = sources.get(dataset.id)!;
        const signature = JSON.stringify([dataset.id, dataset.revision]);
        let operation = operations.current.get(signature);
        if (!operation) {
          operation = { key: crypto.randomUUID(), source };
          operations.current.set(signature, operation);
        }
        if (!operation.execution) {
          const response = await importRequest(token, `${importBase}/${encodeURIComponent(operation.source)}/sync`, { ...jsonRequest({ request_key: operation.key }), signal: controller.signal });
          const execution = executionSchema.parse(await response.json());
          if (controller.signal.aborted) return;
          operation.execution = execution;
        }
        const execution = operation.execution;
        setUploads(current => [...current, { name: dataset.name, execution }]);
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError(`No se completó la admisión. Consulta el historial antes de reintentar; los trabajos ya admitidos continúan. ${reason instanceof Error ? reason.message : ""}`);
    } finally {
      if (!controller.signal.aborted) { active.current = false; setAdmitting(false); }
    }
  }

  return <>
    {children(busy)}
    <div className="space-y-2 text-xs text-gray-300">
      <p>{selected.length} dataset(s) privados seleccionados</p>
      {selected.length > 0 && <p>Local → GCS: {selected.map(dataset => dataset.name).join(", ")}</p>}
      <button type="button" className="rounded-lg border border-emerald-800/60 bg-emerald-950/40 px-3 py-2 font-semibold text-emerald-400 disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-emerald-300" ref={triggerRef} aria-haspopup="dialog" aria-expanded={dialogOpen} disabled={loading || busy || !selected.length} onClick={() => setConfirmation({ datasets, ids: selectedIds })}>Subir selección a GCS</button>
      {dialogOpen && <DatasetConfirmationDialog title="Confirmar subida privada a GCS" onClose={closeConfirmation} returnFocus={triggerRef}>
           <p>{selected.length} dataset(s) privados · Local → GCS</p>
          <ul className="max-h-48 overflow-y-auto">{selected.map(dataset => <li key={dataset.id}>{dataset.name}</li>)}</ul>
          <p>Tamaño estimado: {formatBytes(selected.reduce((total, dataset) => total + dataset.total_size_bytes, 0))}</p>
          <p>Se conserva la copia local y no se publica en el catálogo compartido.</p>
          <div className="flex justify-end gap-3">
            <button type="button" className="rounded-lg border border-[#373a46] px-3 py-2 focus-visible:outline-2 focus-visible:outline-emerald-300" onClick={() => setConfirmation(null)}>Cancelar</button>
            <button type="button" className="rounded-lg border border-emerald-800 bg-emerald-950 px-3 py-2 text-emerald-400 focus-visible:outline-2 focus-visible:outline-emerald-300" onClick={() => void uploadSelection()}>Confirmar subida</button>
          </div>
      </DatasetConfirmationDialog>}
      {admitting && <p role="status">Consultando historial y solicitando subida…</p>}
      {uploads.map(({ name, execution }) => <p key={execution.id} role={execution.status === "failed" ? "alert" : "status"}>{name}: {execution.status === "queued" ? "Trabajo admitido; pendiente de ejecución" : execution.status === "running" ? `Subida en curso (${execution.progress}%)` : execution.status === "succeeded" ? "Subida completada para la revisión sincronizada; copia privada en GCS" : `Subida ${execution.status === "cancelled" ? "cancelada" : "fallida"}; consulta el historial antes de reintentar`}</p>)}
      {error && <p role="alert">{error}</p>}
    </div>
  </>;
}

export default function IngestionView({ onNavigate, sessionToken = "" }: IngestionViewProps = {}) {
  const webUser = useOptionalWebSession();
  const webUserId = webUser?.id;
  const sessionIdentity = sessionToken || (webUserId ? `web:${webUserId}` : "");
  // Estado de almacenamiento GCS
  const [storageStatus, setStorageStatus] = useState<StorageStatus | null>(null);
  const [isLoadingStatus, setIsLoadingStatus] = useState<boolean>(true);

  // Lista de datasets en GCS
  const [datasets, setDatasets] = useState<DatasetItem[]>([]);
  const [isLoadingDatasets, setIsLoadingDatasets] = useState<boolean>(true);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [privateCatalog, setPrivateCatalog] = useState<{ token: string; datasets: CatalogDataset[]; next: string | null; total: number | null }>({ token: sessionIdentity, datasets: [], next: null, total: null });
  const [privateSelection, setPrivateSelection] = useState<{ catalog: typeof privateCatalog; ids: string[] }>({ catalog: privateCatalog, ids: [] });
  const privateSelectedIds = privateSelection.catalog === privateCatalog && privateCatalog.token === sessionIdentity ? privateSelection.ids : [];
  const [privateLoading, setCatalogLoading] = useState(true);
  const [privateError, setCatalogError] = useState("");
  const [privateDetail, setPrivateDetail] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState("");
  const catalogRequest = useRef<AbortController | null>(null);
  const deletionRequest = useRef<AbortController | null>(null);
  const [deletion, setDeletion] = useState({ identity: sessionIdentity, pending: false, message: "", error: false });
  const deleting = deletion.identity === sessionIdentity && deletion.pending;
  const [archiveConfirmation, setArchiveConfirmation] = useState<{ dataset: CatalogDataset; catalog: typeof privateCatalog } | null>(null);
  const archiveTrigger = useRef<HTMLButtonElement>(null);
  const closeArchiveConfirmation = useCallback(() => setArchiveConfirmation(null), []);

  useEffect(() => () => { deletionRequest.current?.abort(); deletionRequest.current = null; }, [sessionIdentity]);
  const catalogMatchesSession = privateCatalog.token === sessionIdentity;
  const importedDatasets = catalogMatchesSession ? privateCatalog.datasets : [];
  const catalogLoading = privateLoading || !catalogMatchesSession;
  const catalogError = catalogMatchesSession ? privateError : "";
  const collectionTotal = catalogMatchesSession && !catalogLoading && !catalogError ? privateCatalog.total : null;

  // Effect-driven loads update state only after real request completion.
  const loadPrivateCatalog = useCallback((cursor: string | null = null, retained?: { ids: string[]; detail: string | null }) => {
    catalogRequest.current?.abort();
    const controller = new AbortController();
    catalogRequest.current = controller;
    return importRequest(sessionToken, `${importBase}/access`, { signal: controller.signal })
      .then(response => response.json())
      .then(access => {
        if (controller.signal.aborted) return;
        if (access.development_mode !== true && !sessionToken && !webUserId) {
          throw new Error("Inicia sesión para consultar el catálogo privado de importaciones.");
        }
        return importRequest(sessionToken, `${importBase}/datasets${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`, { signal: controller.signal })
          .then(response => response.json())
          .then(raw => {
            const page = catalogPageSchema.parse(raw);
            if (controller.signal.aborted) return;
            const catalog = { token: sessionIdentity, datasets: page.datasets, next: page.next_cursor, total: page.total };
            setPrivateCatalog(catalog);
            if (retained) setPrivateSelection({ catalog, ids: retained.ids.filter(id => page.datasets.some(dataset => dataset.id === id)) });
            setCatalogError("");
            setPrivateDetail(retained?.detail && page.datasets.some(dataset => dataset.id === retained.detail) ? retained.detail : null);
            setDownloadError("");
          });
      })
      .catch(reason => {
        if (controller.signal.aborted) return;
        if (!retained) {
          setPrivateCatalog({ token: sessionIdentity, datasets: [], next: null, total: null });
          setPrivateDetail(null);
          setDownloadError("");
        }
        setCatalogError(reason instanceof Error ? reason.message : "No se pudo consultar el catálogo privado.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setCatalogLoading(false);
      });
  }, [sessionToken, sessionIdentity, webUserId]);

  // User events clear the previous page immediately; effects need no synchronous reset.
  const fetchPrivateCatalog = useCallback((cursor: string | null = null) => {
    setCatalogLoading(true);
    setCatalogError("");
    setPrivateCatalog({ token: sessionIdentity, datasets: [], next: null, total: null });
    setPrivateDetail(null);
    setDownloadError("");
    return loadPrivateCatalog(cursor);
  }, [sessionIdentity, loadPrivateCatalog]);

  useEffect(() => {
    void loadPrivateCatalog();
    return () => catalogRequest.current?.abort();
  }, [loadPrivateCatalog]);

  // Descarga bloqueante GCS → Local; la preparación por modelo es independiente.
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [transferStatus, setTransferStatus] = useState<{ message: string; error: boolean } | null>(null);

  const [syncProgress, setSyncProgress] = useState<{
    downloaded: number;
    skipped: number;
    failed: number;
    total: number;
  }>({ downloaded: 0, skipped: 0, failed: 0, total: 0 });

  async function removePrivateDataset(dataset: CatalogDataset) {
    if (deletionRequest.current || catalogLoading || isSyncing) return;
    closeArchiveConfirmation();
    const controller = new AbortController();
    deletionRequest.current = controller;
    setDeletion({ identity: sessionIdentity, pending: true, message: "Archivando dataset…", error: false });
    try {
      await deletePrivateDataset(sessionToken, dataset, controller.signal);
      if (controller.signal.aborted) return;
      const catalog = { ...privateCatalog, datasets: importedDatasets.filter(item => item.id !== dataset.id), total: null };
      const ids = privateSelectedIds.filter(id => id !== dataset.id);
      const detail = privateDetail === dataset.id ? null : privateDetail;
      setPrivateCatalog(catalog);
      setPrivateSelection({ catalog, ids });
      setPrivateDetail(detail);
      if (privateDetail === dataset.id) setDownloadError("");
      setDeletion({ identity: sessionIdentity, pending: true, message: `«${dataset.name}» archivado. Sus archivos locales y las copias en GCS se conservan; esta acción no libera espacio.`, error: false });
      setCatalogLoading(true);
      await loadPrivateCatalog(null, { ids, detail });
    } catch (reason) {
      if (!controller.signal.aborted) setDeletion({ identity: sessionIdentity, pending: false, message: reason instanceof Error ? reason.message : "No se pudo archivar el dataset privado.", error: true });
    } finally {
      if (!controller.signal.aborted) {
        deletionRequest.current = null;
        setDeletion(current => ({ ...current, pending: false }));
      }
    }
  }

  // Curación Supervisada Human-in-the-Loop (RF_06 / ADR 0013)
  const [pendingFeedbacks, setPendingFeedbacks] = useState<PendingFeedbackItem[]>([]);
  const [isLoadingFeedback, setIsLoadingFeedback] = useState<boolean>(true);
  const [processingFeedbackId, setProcessingFeedbackId] = useState<number | null>(null);
  const processingFeedback = useRef(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [queueLoadError, setQueueLoadError] = useState<string | null>(null);
  const [syncRefreshKey, setSyncRefreshKey] = useState(0);
  const queueGeneration = useRef(0);
  const queueRequest = useRef<AbortController | null>(null);

  const reportFeedbackError = (err: unknown) => {
    const detail = err instanceof Error ? err.message : String(err);
    const conflict = typeof err === "object" && err !== null && "statusCode" in err && err.statusCode === 409;
    setFeedbackError(conflict
      ? `Conflicto (409): el audio ya fue finalizado. Actualiza la cola para consultar su estado. ${detail}`
      : `No se completó la acción; el audio sigue pendiente. ${detail}`);
  };

  // Explorador de archivos de un dataset
  const [inspectingDataset, setInspectingDataset] = useState<string | null>(null);
  const [datasetFiles, setDatasetFiles] = useState<DatasetFile[]>([]);
  const [isLoadingFiles, setIsLoadingFiles] = useState<boolean>(false);

  // Consola de Logs reactiva
  const [logs, setLogs] = useState<LogEntry[]>([
    {
      id: "initial-log-lake",
      timestamp: new Date().toISOString(),
      level: "INFO",
      message: "Inicializando módulo de ingesta y bandeja de curación supervisada (ADR 0013)...",
    },
  ]);
  const logsContainerRef = useRef<HTMLDivElement | null>(null);

  const addLog = useCallback((level: LogEntry["level"], message: string) => {
    const newEntry: LogEntry = {
      id: Math.random().toString(36).substring(2, 9),
      timestamp: new Date().toISOString(),
      level,
      message,
    };
    setLogs((prev) => [...prev, newEntry]);
  }, []);

  // Auto-scroll para la consola de logs
  useEffect(() => {
    if (logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
    }
  }, [logs]);

  // Cargar estado de almacenamiento y datasets
  const fetchStatus = useCallback(async () => {
    setIsLoadingStatus(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/ingestion/status`);
      if (res.ok) {
        const data: StorageStatus = await res.json();
        setStorageStatus(data);
        if (data.connected) {
          addLog(
            "INFO",
            `GCS conectado con éxito al bucket: ${data.bucket} (${data.total_objects} objetos, ${formatBytes(data.total_bytes)})`
          );
        } else {
          addLog("ERROR", `Fallo al verificar bucket GCS: ${data.error || "Desconocido"}`);
        }
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      setStorageStatus({
        connected: false,
        bucket: "Desconectado",
        total_objects: 0,
        total_bytes: 0,
        error: errMsg,
      });
      addLog("ERROR", `No fue posible conectar con el endpoint de estado de GCS: ${errMsg}`);
    } finally {
      setIsLoadingStatus(false);
    }
  }, [addLog]);

  const fetchDatasets = useCallback(async () => {
    setIsLoadingDatasets(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/ingestion/datasets`);
      if (res.ok) {
        const data = await res.json();
        setDatasets(data.datasets || []);
        addLog("INFO", `Se listaron ${data.datasets?.length || 0} dataset(s) disponibles.`);
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      addLog("WARN", `Error al cargar la lista de datasets: ${errMsg}`);
    } finally {
      setIsLoadingDatasets(false);
    }
  }, [addLog]);

  const fetchPendingFeedbacks = useCallback(async () => {
    const current = ++queueGeneration.current;
    queueRequest.current?.abort();
    const controller = new AbortController();
    queueRequest.current = controller;
    setIsLoadingFeedback(true);
    try {
      const items = await getPendingFeedback(50, controller.signal);
      if (current !== queueGeneration.current || controller.signal.aborted) return;
      setPendingFeedbacks(items);
      setQueueLoadError(null);
    } catch (err: unknown) {
      if (current !== queueGeneration.current || controller.signal.aborted) return;
      const errMsg = err instanceof Error ? err.message : String(err);
      setQueueLoadError(`No fue posible cargar la cola de revisión: ${errMsg}. Se conserva la última consulta disponible.`);
      addLog("WARN", `Error al consultar la cola de curación: ${errMsg}`);
    } finally {
      if (current === queueGeneration.current && !controller.signal.aborted) setIsLoadingFeedback(false);
    }
  }, [addLog]);

  useEffect(() => {
    let disposed = false;
    void Promise.resolve().then(() => { if (!disposed) void fetchPendingFeedbacks(); });
    const onVisible = () => {
      if (document.visibilityState === "visible") void fetchPendingFeedbacks();
    };
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      disposed = true;
      queueRequest.current?.abort();
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [fetchPendingFeedbacks]);

  useEffect(() => {
    let isCancelled = false;

    async function initializeIngestion() {
      try {
        const [statusResult, datasetsResult] = await Promise.allSettled([
          fetch(`${API_BASE_URL}/api/ingestion/status`),
          fetch(`${API_BASE_URL}/api/ingestion/datasets`),
        ]);

        if (isCancelled) return;

        if (statusResult.status === "fulfilled" && statusResult.value.ok) {
          const data: StorageStatus = await statusResult.value.json();
          setStorageStatus(data);
          if (data.connected) {
            addLog(
              "INFO",
              `GCS conectado con éxito al bucket: ${data.bucket} (${data.total_objects} objetos, ${formatBytes(data.total_bytes)})`
            );
          } else {
            addLog("WARN", `Data Lake operando en modo local (GCS desconectado): ${data.error || "Sin conexión"}`);
          }
        } else if (
          statusResult.status === "rejected" ||
          (statusResult.status === "fulfilled" && !statusResult.value.ok)
        ) {
          setStorageStatus({
            connected: false,
            bucket: "fama-audio-records-2026",
            total_objects: 0,
            total_bytes: 0,
            error: "No fue posible conectar con el servicio de almacenamiento GCS",
          });
          addLog("WARN", "Fallo al consultar estado de GCS. Data Lake operando en modo local.");
        }

        if (datasetsResult.status === "fulfilled" && datasetsResult.value.ok) {
          const dsData = await datasetsResult.value.json();
          setDatasets(dsData.datasets || []);
          addLog("INFO", `Se listaron ${dsData.datasets?.length || 0} dataset(s) disponibles.`);
        } else if (datasetsResult.status === "rejected") {
          addLog("WARN", "Error de red al consultar datasets.");
        }

      } catch (err: unknown) {
        if (!isCancelled) {
          const errMsg = err instanceof Error ? err.message : String(err);
          addLog("WARN", `Error durante la inicialización de ingesta: ${errMsg}`);
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingStatus(false);
          setIsLoadingDatasets(false);
        }
      }
    }

    initializeIngestion();

    return () => {
      isCancelled = true;
    };
  }, [addLog]);

  // Manejo de Selección de Datasets
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const toggleSelectAll = () => {
    if (selectedIds.length === datasets.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(datasets.map((d) => d.id));
    }
  };

  // Confirmar la selección antes de iniciar la descarga existente.
  const handleSync = async () => {
    if (selectedIds.length === 0 || isSyncing) return;
    const targets = datasets.filter(dataset => selectedIds.includes(dataset.id));
    if (targets.length === 0) return;
    const hasEstimate = targets.every(dataset => Number.isFinite(dataset.total_size_bytes) && dataset.total_size_bytes >= 0);
    const estimatedSize = hasEstimate ? formatBytes(targets.reduce((total, dataset) => total + dataset.total_size_bytes, 0)) : "no disponible";
    if (!window.confirm(`Descargar de GCS al entorno local: ${targets.map(dataset => `${dataset.name} (${dataset.id})`).join(", ")}. Tamaño estimado: ${estimatedSize}; los archivos ya presentes pueden omitirse. No inicia entrenamiento. ¿Continuar?`)) return;
    setIsSyncing(true);
    setTransferStatus({ message: `Descarga en curso · GCS → Local: ${targets.map(dataset => dataset.name).join(", ")}. Esperando respuesta del servidor.`, error: false });
    addLog("INFO", `Descargando [GCS → Local]: ${targets.map(dataset => dataset.name).join(", ")}.`);

    let totalDownload = 0;
    let totalSkip = 0;
    let totalFail = 0;

    try {
      const res = await fetch(`${API_BASE_URL}/api/ingestion/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          datasets: targets.map(dataset => dataset.id),
          preprocess: false,
        }),
      });

      if (!res.ok) {
        throw new Error(`Error en el servidor: HTTP ${res.status}`);
      }

      const data = await res.json();
      totalDownload = data.total_downloaded || 0;
      totalSkip = data.total_skipped || 0;
      totalFail = data.total_failed || 0;

      setSyncProgress({
        downloaded: totalDownload,
        skipped: totalSkip,
        failed: totalFail,
        total: totalDownload + totalSkip + totalFail,
      });

      const results: SyncDatasetResult[] = data.results || [];
      for (const item of results) {
        if (item.failed > 0) {
          addLog("ERROR", `Dataset '${item.dataset}': ${item.failed} error(es) en la descarga.`);
        }
        addLog(
          "INFO",
          `Dataset '${item.dataset}': ${item.downloaded} descargados nuevos, ${item.skipped} omitidos (ya actualizados localmente).`
        );
        if ((item.preprocess_info?.failed || 0) > 0) {
          addLog("ERROR", `Dataset '${item.dataset}': ${item.preprocess_info?.failed} error(es) en preprocesamiento.`);
        }
        if (item.files?.some(file => file.cleanup_pending)) {
          addLog("WARN", `Dataset '${item.dataset}': limpieza de temporales pendiente.`);
        }
        if (item.db_persisted) {
          addLog(
            "INFO",
            `Dataset '${item.dataset}': Registrado y actualizado en PostgreSQL (tablas conjunto_datos y audio).`
          );
        } else {
          addLog("WARN", `Dataset '${item.dataset}': persistencia en BD no confirmada.`);
        }
      }

      const hasStageErrors = totalFail > 0 || results.some(item =>
        item.failed > 0 || item.db_persisted !== true || (item.preprocess_info?.failed || 0) > 0
      );
      const complete = data.status === "completed" && !hasStageErrors;
      const failed = data.status === "failed";
      addLog(failed ? "ERROR" : complete ? "SUCCESS" : "WARN",
        `Sincronización ${failed ? "fallida" : complete ? "completada" : "parcial"}: ${totalDownload} archivo(s) descargados, ${totalSkip} omitidos, ${totalFail} errores de descarga.`
      );

      setTransferStatus({ message: `Descarga ${failed ? "fallida" : complete ? "completada" : "parcial"} · GCS → Local: ${targets.map(dataset => dataset.name).join(", ")}. ${totalDownload} descargados, ${totalSkip} omitidos, ${totalFail} errores. Consulta el detalle en la consola.`, error: !complete });
      await fetchDatasets();
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      setTransferStatus({ message: `No se confirmó la descarga · GCS → Local: ${targets.map(dataset => dataset.name).join(", ")}. ${errMsg}`, error: true });
      addLog("ERROR", `Fallo en el proceso de sincronización: ${errMsg}`);
    } finally {
      setIsSyncing(false);
      setSelectedIds([]);
    }
  };

  // Acciones de Curación Human-in-the-Loop (RF_06 / ADR 0013)
  const handleApprove = async (item: PendingFeedbackItem) => {
    if (processingFeedback.current) return;
    const datasetName = item.dataset_name;
    const validatedClass = item.fue_correcta ? item.etiqueta_predicha : item.etiqueta_corregida;
    if (!datasetName || !validatedClass) return;
    processingFeedback.current = true;
    setFeedbackError(null);
    setProcessingFeedbackId(item.id_retroalimentacion);
    try {
      const res = await approveFeedback(item.id_retroalimentacion);
      addLog(
        "SUCCESS",
        `Audio incorporado al dataset local '${datasetName}' (Clase: ${res.clase}). ${res.sync_status === "synced" ? "Copia cloud confirmada." : "Copia cloud pendiente; la sincronización automática no bloquea la preparación de entrenamiento."}`
      );
      setPendingFeedbacks(previous => previous.filter(pending => pending.id_retroalimentacion !== item.id_retroalimentacion));
      setSyncRefreshKey(previous => previous + 1);
      await Promise.all([fetchDatasets(), fetchPrivateCatalog(), fetchPendingFeedbacks()]);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      reportFeedbackError(err);
      addLog("ERROR", `Error al incorporar audio: ${errMsg}`);
    } finally {
      processingFeedback.current = false;
      setProcessingFeedbackId(null);
    }
  };

  const handleReject = async (idRetroalimentacion: number) => {
    if (processingFeedback.current) return;
    processingFeedback.current = true;
    setFeedbackError(null);
    setProcessingFeedbackId(idRetroalimentacion);
    try {
      const res = await rejectFeedback(idRetroalimentacion);
      addLog(
        "INFO",
        `Audio descartado de la cola sin borrar físicamente el audio ni modificar los datasets (${res.message || "Descartado"}).`
      );
      await fetchPendingFeedbacks();
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      reportFeedbackError(err);
      addLog("ERROR", `Error al descartar audio: ${errMsg}`);
    } finally {
      processingFeedback.current = false;
      setProcessingFeedbackId(null);
    }
  };

  // Inspeccionar archivos de un dataset
  const handleInspectDataset = async (datasetName: string) => {
    setInspectingDataset(datasetName);
    setIsLoadingFiles(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/ingestion/datasets/${datasetName}/files`);
      if (res.ok) {
        const data = await res.json();
        setDatasetFiles(data.files || []);
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      addLog("WARN", `No fue posible cargar los archivos de ${datasetName}: ${errMsg}`);
    } finally {
      setIsLoadingFiles(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* ==================================================================== */}
      {/* 1. HEADER DE LA VISTA: ESTADO DE NUBE GCS REAL */}
      {/* ==================================================================== */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500/20 to-blue-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shadow-inner">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-bold text-white tracking-tight font-heading">
              Gestión de audios
            </h1>
            <p className="text-xs text-gray-400">
              Importaciones privadas, catálogo compartido y transferencias explícitas
            </p>
          </div>
        </div>

        {/* Indicadores de Conexión en Tiempo Real */}
        <div className="flex items-center gap-2.5 flex-wrap">
          <button
            type="button"
            onClick={() => {
              fetchStatus();
              fetchDatasets();
              void fetchPrivateCatalog();
              fetchPendingFeedbacks();
              setSyncRefreshKey(previous => previous + 1);
            }}
            title="Refrescar estado de GCS y datos"
            className="p-1.5 rounded-lg text-gray-400 hover:text-white bg-[#16171b] border border-[#23252e] hover:border-[#373a46] transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>

          {isLoadingStatus ? (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#16171b] border border-[#23252e] text-gray-400 text-xs">
              <span className="w-2 h-2 rounded-full bg-gray-500 animate-pulse" />
              Verificando GCS...
            </span>
          ) : storageStatus?.connected ? (
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-gray-400 hidden sm:inline">
                {formatBytes(storageStatus.total_bytes)} ({storageStatus.total_objects} objetos)
              </span>
              <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-950/60 border border-emerald-800/60 text-emerald-400 font-medium text-xs shadow-sm">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                GCP: Conectado ({storageStatus.bucket})
              </span>
            </div>
          ) : (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-red-950/60 border border-red-800/60 text-red-400 font-medium text-xs">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              GCP: Desconectado
            </span>
          )}
        </div>
      </div>

      {/* Banner Informativo de Modo Offline / Local */}
      {storageStatus && !storageStatus.connected && (
        <div
          data-testid="offline-mode-banner"
          role="status"
          className="bg-amber-950/40 border border-amber-800/60 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-lg"
        >
          <div className="flex items-start sm:items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-amber-400 shrink-0 mt-0.5 sm:mt-0">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <div>
              <p className="text-xs font-semibold text-amber-300">
                Data Lake en modo local (Offline-First)
              </p>
              <p className="text-[11px] text-amber-200/80">
                Google Cloud Storage no está disponible o las credenciales no están configuradas. Los datos mostrados provienen del disco local (<span className="font-mono">data/raw/</span>).
              </p>
            </div>
          </div>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-900/60 border border-amber-700/60 text-amber-300 self-start sm:self-auto shrink-0">
            Almacenamiento Local Activo
          </span>
        </div>
      )}

      {/* ==================================================================== */}
      {/* Importaciones privadas: identidades independientes del catálogo compartido. */}
      <section aria-label="Catálogo" className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold text-white tracking-tight font-heading">Catálogo datasets privados</h2>
          <DatasetImportPanel key={sessionIdentity} sessionToken={sessionToken} onCatalogChange={fetchPrivateCatalog} triggerLabel="Importar ZIP" datasetNames={Object.fromEntries(importedDatasets.map(dataset => [dataset.id, dataset.name]))} />
        </div>
        <p className="text-xs text-gray-400">Importa un ZIP al entorno local y selecciona los datasets para guardar una copia privada en GCS. La copia local se conserva; no se publica en el catálogo compartido.</p>
        <p className="text-[11px] text-gray-400">{collectionTotal === null ? "Catálogo privado pendiente de consulta" : `${collectionTotal} importaciones privadas`}</p>
        <button type="button" className="text-xs text-gray-300 hover:text-white focus-visible:outline-2 focus-visible:outline-emerald-300" disabled={catalogLoading || deleting} onClick={() => void fetchPrivateCatalog()}>Actualizar estados</button>
        <PrivateDatasetUpload key={sessionIdentity} token={sessionToken} datasets={importedDatasets} selectedIds={privateSelectedIds} loading={catalogLoading || deleting} onCatalogChange={fetchPrivateCatalog}>
        {uploadBusy => <>
        <div className="overflow-x-auto">
          {archiveConfirmation && archiveConfirmation.catalog === privateCatalog && catalogMatchesSession && !catalogLoading && !deleting && !uploadBusy && !isSyncing &&
            <DatasetConfirmationDialog title="Confirmar archivado de dataset" onClose={closeArchiveConfirmation} returnFocus={archiveTrigger}>
              <p>¿Eliminar «{archiveConfirmation.dataset.name}» del catálogo?</p>
              <p>El dataset quedará archivado y no estará disponible para nuevas operaciones.</p>
              <p>Sus archivos locales y las copias en GCS se conservan. Esta acción no libera espacio.</p>
              <div className="flex justify-end gap-2">
                <button type="button" className="rounded-lg border border-[#373a46] px-3 py-2 transition-colors hover:bg-[#252830] hover:border-[#515565] hover:text-white focus-visible:outline-2 focus-visible:outline-emerald-300" onClick={closeArchiveConfirmation}>Cancelar</button>
                <button type="button" className="rounded-lg border border-red-900 bg-red-950 px-3 py-2 text-red-300 transition-colors hover:bg-red-900 hover:border-red-700 hover:text-red-100 focus-visible:outline-2 focus-visible:outline-red-300" onClick={() => void removePrivateDataset(archiveConfirmation.dataset)}>Confirmar archivado</button>
              </div>
            </DatasetConfirmationDialog>}
          <table aria-label="Catálogo" className="w-full min-w-[760px] text-left text-xs [&_th]:pr-4 [&_td]:pr-4">
            <thead><tr className="border-b border-[#23252e] text-gray-400">
              <th className="pb-3">{importedDatasets.length > 0 && <input className="rounded bg-[#121316] border-[#2d303b] text-emerald-600 focus:ring-0 cursor-pointer" type="checkbox" aria-label="Seleccionar todos los datasets privados" disabled={catalogLoading || deleting || uploadBusy || !importedDatasets.length} checked={importedDatasets.length > 0 && privateSelectedIds.length === importedDatasets.length} onChange={event => setPrivateSelection({ catalog: privateCatalog, ids: event.target.checked ? importedDatasets.map(dataset => dataset.id) : [] })} />}</th>
              <th className="pb-3 font-medium">Dataset</th><th className="pb-3 font-medium">Ámbito</th><th className="pb-3 font-medium">Disponibilidad</th><th className="pb-3 font-medium">Clases</th><th className="pb-3 font-medium">Acuses de subida</th><th className="pb-3 font-medium">Archivos Locales</th><th className="pb-3 font-medium">Tamaño</th><th className="pb-3 font-medium">Acción</th><th className="pb-3 font-medium">Eliminar</th>
            </tr></thead>
            <tbody className="divide-y divide-[#23252e]/60">{importedDatasets.map(dataset => (
              <tr key={`import:${dataset.id}`} className="hover:bg-[#1c1e24]/40 transition-colors">
                <td className="py-2.5"><input className="rounded bg-[#121316] border-[#2d303b] text-emerald-600 focus:ring-0 cursor-pointer" type="checkbox" aria-label={`Seleccionar dataset privado ${dataset.name}`} disabled={catalogLoading || deleting || uploadBusy} checked={privateSelectedIds.includes(dataset.id)} onChange={event => setPrivateSelection({ catalog: privateCatalog, ids: event.target.checked ? [...privateSelectedIds, dataset.id] : privateSelectedIds.filter(id => id !== dataset.id) })} /></td>
                <td className="py-2.5 font-medium text-gray-200"><div className="flex items-center gap-2"><DatasetFolderIcon /><span className="font-semibold">{dataset.name}</span></div></td>
                <td className="py-2.5 text-gray-300">Privado</td>
                <td className="py-2.5 text-gray-400">Copia local catalogada · {dataset.synced_file_count > 0 ? `Subida a GCS registrada (${dataset.synced_file_count}/${dataset.file_count})` : "Sin subida a GCS registrada"}</td>
                <td className="py-2.5 text-gray-300">{dataset.class_count} clase(s)</td>
                <td className="py-2.5 font-mono text-gray-300" title="Acuses durables históricos de subida; no verifica la existencia actual en GCS.">{dataset.synced_file_count}</td>
                <td className="py-2.5 font-mono text-gray-300">{dataset.file_count}</td>
                <td className="py-2.5 text-gray-400">{formatBytes(dataset.total_size_bytes)}</td>
                <td className="py-2.5"><button type="button" className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded bg-[#1c1e24] hover:bg-[#252830] border border-[#2d303b] transition-colors" disabled={deleting} onClick={() => { setPrivateDetail(dataset.id); setDownloadError(""); }}>Consultar audios</button></td>
                <td className="py-2.5">
                  <button type="button" aria-label={`Eliminar ${dataset.name}`}
                    className="rounded border border-red-900 bg-red-950/30 px-2 py-1 text-red-300 transition-colors enabled:hover:bg-red-900/50 enabled:hover:border-red-700 enabled:hover:text-red-100 disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-red-300"
                    disabled={catalogLoading || deleting || uploadBusy || isSyncing}
                    aria-haspopup="dialog"
                     onClick={event => { archiveTrigger.current = event.currentTarget; setArchiveConfirmation({ dataset, catalog: privateCatalog }); }}>Eliminar</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        <div className="space-y-4 py-4 text-xs text-gray-400">
          {deletion.identity === sessionIdentity && deletion.message && <p role={deletion.error ? "alert" : "status"}>{deletion.message}</p>}
          {catalogLoading && <p role="status">Consultando catálogo privado…</p>}
          {catalogError && <p role="alert">Catálogo privado no disponible: {catalogError}</p>}
          {!catalogLoading && !catalogError && importedDatasets.length === 0 && <p>No hay importaciones privadas en esta página.</p>}
          <p>Acuses de subida: confirmaciones históricas, no una verificación actual del bucket. Los archivos locales son metadatos del catálogo, no un escaneo actual del disco.</p>
          <div className="flex flex-wrap gap-3">
            <button type="button" disabled={catalogLoading || deleting} onClick={() => void fetchPrivateCatalog()}>Primera página de importaciones</button>
            <button type="button" disabled={catalogLoading || deleting || !catalogMatchesSession || !privateCatalog.next} onClick={() => void fetchPrivateCatalog(privateCatalog.next)}>Siguiente página de importaciones</button>
          </div>
          {privateDetail && importedDatasets.some(dataset => dataset.id === privateDetail) && <div>
            <button type="button" onClick={() => setPrivateDetail(null)}>Cerrar consulta de audios</button>
            <ImportDetailPage key={`${sessionToken}:${privateDetail}`} token={sessionToken}
              endpoint={`${importBase}/datasets/${encodeURIComponent(privateDetail)}/files`} collection="files" label="audios importados" schema={audioSchema}
              renderItem={file => <button type="button" disabled={deleting} className="underline" onClick={() => {
                setDownloadError("");
                void importRequest(sessionToken, `${importBase}/datasets/${encodeURIComponent(privateDetail)}/files/${file.sha256}`)
                  .then(response => saveDownload(response, file.original_path.split("/").pop() || "audio.wav"))
                  .catch(reason => setDownloadError(reason instanceof Error ? reason.message : "No se pudo descargar el audio."));
              }}>{file.original_path} ({file.class_name})</button>} />
            {downloadError && <p role="alert">{downloadError}</p>}
          </div>}
        </div>
        </>}
        </PrivateDatasetUpload>

        <h2 className="text-xl font-bold text-white tracking-tight font-heading">Catálogo datasets públicos</h2>
        <p className="text-xs text-gray-400">Colecciones compartidas en la aplicación, no públicas en Internet. Los conteos reflejan la última consulta, no garantizan disponibilidad en tiempo real.</p>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm text-gray-200 font-semibold font-heading">Compartidos en GCS</h3>
            <span className="text-[10px] px-2 py-0.5 rounded bg-[#1c1e24] text-gray-400 font-mono">
              {datasets.length} colecciones compartidas
            </span>
          </div>

          <button
            type="button"
            onClick={() => { void fetchDatasets(); }}
            disabled={isLoadingDatasets}
            className="text-[11px] text-gray-400 hover:text-gray-200 transition-colors flex items-center gap-1"
          >
            <svg className={`w-3 h-3 ${isLoadingDatasets ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            <span>Actualizar catálogo</span>
          </button>
        </div>

        <div className="flex items-center gap-2 text-xs text-gray-300">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    aria-label="Seleccionar todos los datasets compartidos"
                    checked={datasets.length > 0 && selectedIds.length === datasets.length}
                    onChange={toggleSelectAll}
                    disabled={datasets.length === 0}
                    className="rounded bg-[#121316] border-[#2d303b] text-emerald-600 focus:ring-0 cursor-pointer"
                  />
                Seleccionar todos los compartidos</label>
        </div>
        <div className="overflow-x-auto">
          <table aria-label="Catálogo compartido" className="w-full min-w-[760px] text-left text-xs [&_th]:pr-4 [&_td]:pr-4">
            <thead><tr className="border-b border-[#23252e] text-gray-400">
              <th className="pb-3" aria-label="Selección" />
              {['Dataset', 'Ámbito', 'Disponibilidad', 'Clases', 'Archivos en GCS', 'Archivos Locales', 'Tamaño', 'Última Modificación', 'Acción'].map(label => <th key={label} className="pb-3 font-medium">{label}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-[#23252e]/60">
              {isLoadingDatasets ? (
                <tr>
                  <td colSpan={10} className="py-8 text-center text-gray-400">
                    <div className="flex items-center justify-center gap-2">
                      <svg className="w-4 h-4 animate-spin text-emerald-400" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                      </svg>
                      <span>Consultando datasets en Google Cloud Storage...</span>
                    </div>
                  </td>
                </tr>
              ) : datasets.length === 0 ? (
                <tr>
                  <td colSpan={10} className="py-8 text-center">
                    <div className="max-w-md mx-auto space-y-2">
                      <div className="w-10 h-10 mx-auto rounded-full bg-[#1c1e24] flex items-center justify-center text-gray-500">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
                        </svg>
                      </div>
                      <p className="text-gray-300 font-medium">
                        No hay datasets cargados bajo el prefijo &apos;datasets/&apos;
                      </p>
                      <p className="text-xs text-gray-500">
                        Realiza inferencias y valida grabaciones en el clasificador acústico para incorporar audios curados al dataset.
                      </p>
                      {onNavigate && (
                        <button
                          type="button"
                          onClick={() => onNavigate("predict")}
                          className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-emerald-400 bg-emerald-950/40 border border-emerald-800/60 hover:bg-emerald-900/50 transition-colors cursor-pointer"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                          </svg>
                          <span>Ir a Inferencia Acústica</span>
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ) : (
                datasets.map((d) => (
                  <tr key={`legacy:${d.id}`} className="hover:bg-[#1c1e24]/40 transition-colors">
                    <td className="py-2.5">
                      <input
                        type="checkbox"
                        aria-label={`Seleccionar ${d.name}`}
                        checked={selectedIds.includes(d.id)}
                        onChange={() => toggleSelect(d.id)}
                        className="rounded bg-[#121316] border-[#2d303b] text-emerald-600 focus:ring-0 cursor-pointer"
                      />
                    </td>
                    <td className="py-2.5 font-medium text-gray-200">
                      <div className="flex items-center gap-2">
                        <DatasetFolderIcon />
                        <span className="font-semibold">{d.name}</span>
                      </div>
                    </td>
                    <td className="py-2.5 text-gray-300">Compartido</td>
                    <td className="py-2.5 text-gray-400">{d.local_file_count > 0 ? "Local" : "Sin copia local"} · {d.gcs_available === false || d.gcs_file_count == null ? "GCS desconocido" : d.gcs_file_count === 0 ? "Sin archivos en GCS" : "GCS listado"}</td>
                    <td className="py-2.5 text-gray-300">
                      {typeof d.class_count === "number" && Number.isInteger(d.class_count) && d.class_count >= 0
                        ? `${d.class_count} clase(s)`
                        : Array.isArray(d.classes) ? `${d.classes.length} clase(s)` : "Desconocido"}
                    </td>
                    <td className="py-2.5 text-gray-300 font-mono" title="Conteo del listado remoto; desconocido si no fue posible consultar GCS.">{d.gcs_file_count ?? "Desconocido"}</td>
                    <td className="py-2.5 text-gray-400 font-mono">
                      {d.local_file_count}
                    </td>
                    <td className="py-2.5 text-gray-400 font-mono">{formatBytes(d.total_size_bytes)}</td>
                    <td className="py-2.5 text-gray-400 font-mono text-[11px]">
                      {d.last_modified
                        ? new Date(d.last_modified).toLocaleDateString("es-CL", {
                            year: "numeric",
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—"}
                    </td>
                    <td className="py-2.5 text-right pr-2">
                      <button
                        type="button"
                        onClick={() => handleInspectDataset(d.name)}
                        className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded bg-[#1c1e24] hover:bg-[#252830] border border-[#2d303b] transition-colors"
                      >
                        Ver archivos
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {transferStatus && <p role={transferStatus.error ? "alert" : "status"} className={`text-xs break-words ${transferStatus.error ? "text-amber-300" : "text-gray-300"}`}>{transferStatus.message}</p>}
        {/* Descarga explícita GCS → Local. */}
        <div className="flex flex-col lg:flex-row items-center justify-between gap-3 pt-3 border-t border-[#23252e]/70">
          <div className="flex items-center gap-3 flex-wrap w-full lg:w-auto justify-between sm:justify-start">
            <span className="text-xs text-gray-400">
              {selectedIds.length} dataset(s) seleccionado(s)
            </span>

            <span className="text-xs text-gray-400 break-words">GCS → Local: {datasets.filter(dataset => selectedIds.includes(dataset.id)).map(dataset => dataset.name).join(", ") || "Sin selección"}</span>
          </div>

          <div className="flex flex-col sm:flex-row gap-2 w-full lg:w-auto">
          <button
            type="button"
            onClick={handleSync}
            disabled={isSyncing || selectedIds.length === 0}
            className="w-full lg:w-auto py-2 px-4 rounded-lg text-xs font-semibold text-white bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 active:from-emerald-700 active:to-teal-700 disabled:opacity-40 disabled:cursor-not-allowed border border-emerald-500/30 transition-all flex items-center justify-center gap-2 shadow-lg shadow-emerald-950/30"
          >
            {isSyncing ? (
              <>
                <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                <span>
                  Descargando desde GCS…
                </span>
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                <span>Descargar seleccionados</span>
              </>
            )}
          </button>
          <DatasetExportDialog />

          </div>
        </div>
        <p className="text-[11px] text-gray-400">
          Guarda los archivos en el entorno donde se ejecuta F.A.M.A.; no inicia el entrenamiento.
        </p>
      </section>

      {/* ==================================================================== */}
      {/* 3. BANDEJA DE CURACIÓN E INCORPORACIÓN DE AUDIOS AL DATASET (RF_06 / ADR 0013) */}
      {/* ==================================================================== */}
      <section
        id="seccion-curacion-feedback"
        aria-label="Revisar audios"
        className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4 shadow-sm"
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-[#23252e] pb-3">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <h2 className="text-sm font-bold text-white tracking-tight">
                Revisar audios
              </h2>
              <p className="text-[11px] text-gray-400">
                Incorporar guarda el audio localmente; puede preparar entrenamiento sin esperar GCS y su copia cloud se sincroniza después. Descartar de la cola no borra físicamente el audio.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#1c1e24] text-emerald-400 border border-emerald-800/40">
              {pendingFeedbacks.length} pendiente(s)
            </span>
            <button
              type="button"
              onClick={fetchPendingFeedbacks}
              disabled={isLoadingFeedback}
              className="text-[11px] text-gray-400 hover:text-gray-200 transition-colors flex items-center gap-1 p-1 rounded hover:bg-[#1f2128]"
              title="Actualizar cola de curación"
            >
              <svg className={`w-3.5 h-3.5 ${isLoadingFeedback ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
          </div>
        </div>

        {feedbackError && <p role="alert" className="text-xs text-red-300">{feedbackError}</p>}
        {queueLoadError && <p role="alert" className="text-xs text-red-300">{queueLoadError}</p>}
        {/* CONTENIDO DE LA BANDEJA: ESTADO DE CARGA / VACÍA / LISTADO */}
        {isLoadingFeedback ? (
          <div className="py-8 text-center text-gray-400">
            <div className="flex items-center justify-center gap-2">
              <svg className="w-4 h-4 animate-spin text-emerald-400" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              <span className="text-xs">Consultando audios pendientes de curación...</span>
            </div>
          </div>
        ) : queueLoadError && pendingFeedbacks.length === 0 ? null : pendingFeedbacks.length === 0 ? (
          <div
            data-testid="curation-queue-empty"
            role="status"
            aria-live="polite"
            className="bg-[#101114]/70 border border-dashed border-[#23252e] rounded-xl p-6 text-center space-y-3"
          >
            <div className="w-10 h-10 mx-auto rounded-full bg-emerald-950/40 border border-emerald-800/40 flex items-center justify-center text-emerald-400">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-semibold text-gray-200">
                Cola de curación vacía (0 audios pendientes de incorporación)
              </p>
              <p className="text-[11px] text-gray-400 max-w-lg mx-auto">
                No hay audios enviados a revisión pendientes. Ejecuta una inferencia, confirma o corrige la clase y pulsa «Enviar a revisión».
              </p>
            </div>
            <div>
              <button
                type="button"
                onClick={() => onNavigate?.("predict")}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-emerald-400 bg-emerald-950/40 border border-emerald-800/60 hover:bg-emerald-900/50 transition-colors cursor-pointer shadow-sm"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                </svg>
                <span>Ir a Inferencia Acústica</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[#23252e] text-gray-400">
                  <th className="pb-2.5 font-medium">Audio</th>
                  <th className="pb-2.5 font-medium">Etiqueta Predicha</th>
                  <th className="pb-2.5 font-medium">Etiqueta Validada / Corregida</th>
                  <th className="pb-2.5 font-medium">Confianza</th>
                  <th className="pb-2.5 font-medium text-right pr-2">Acciones Human-in-the-Loop</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#23252e]/60">
                {pendingFeedbacks.map((item) => {
                  const filename = item.audio_filename?.trim() || "Nombre original no disponible";
                  const label = item.fue_correcta ? item.etiqueta_predicha : item.etiqueta_corregida;
                  const canIncorporate = Boolean(item.dataset_name && label);
                  const isCorrected = !item.fue_correcta && Boolean(item.etiqueta_corregida);
                  const isProcessing = processingFeedbackId === item.id_retroalimentacion;

                  return (
                    <tr key={item.id_retroalimentacion} className="hover:bg-[#1c1e24]/40 transition-colors">
                      <td className="py-3 font-medium text-gray-200">
                        <span className="block font-mono text-gray-300 text-xs truncate max-w-xs" title={filename}>
                          {filename}
                        </span>
                        <span className="text-[10px] text-gray-500 font-mono block mt-0.5">
                          {uploadDateLabel(item.fecha_carga)}
                        </span>
                      </td>
                      <td className="py-3 text-gray-400 font-mono text-xs">
                        {item.etiqueta_predicha}
                      </td>
                      <td className="py-3">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span
                            className={`px-2 py-0.5 rounded text-[11px] font-mono font-medium border ${
                              isCorrected
                                ? "bg-amber-950/70 text-amber-300 border-amber-800/60"
                                : "bg-emerald-950/70 text-emerald-400 border-emerald-800/60"
                            }`}
                          >
                            {label}
                          </span>
                          {isCorrected && (
                            <span className="text-[10px] text-amber-400 font-sans">
                              (Corrección Humana)
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-3 font-mono text-gray-300 text-xs">
                        {(item.confianza * 100).toFixed(1)}%
                      </td>
                      <td className="py-3 text-right pr-2">
                        <div className="mb-2 space-y-1 text-left">
                          <span className="block text-gray-400">Dataset de inferencia</span>
                          {item.dataset_name ? (
                            <p className="font-mono text-emerald-300">{item.dataset_name}</p>
                          ) : (
                            <p className="text-[11px] text-amber-300">Sin dataset de inferencia asociado. No se puede incorporar este audio sin una asociación verificable; permanece pendiente o puedes descartarlo de la cola.</p>
                          )}
                          {!label && <p className="text-[11px] text-amber-300">No hay una clase validada disponible para incorporar este audio.</p>}
                        </div>
                        <div className="flex items-center justify-end gap-2">
                          <button
                            type="button"
                            onClick={() => handleApprove(item)}
                            disabled={processingFeedbackId !== null || !canIncorporate}
                            className="px-2.5 py-1 rounded-lg text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 transition-colors shadow-sm flex items-center gap-1 cursor-pointer"
                          >
                            {isProcessing ? (
                              <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                              </svg>
                            ) : (
                              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                              </svg>
                            )}
                            <span>Incorporar al dataset</span>
                          </button>

                          <button
                            type="button"
                            onClick={() => handleReject(item.id_retroalimentacion)}
                            disabled={processingFeedbackId !== null}
                            className="px-2.5 py-1 rounded-lg text-xs font-semibold text-red-400 hover:text-red-300 bg-red-950/40 hover:bg-red-900/50 border border-red-800/60 disabled:opacity-40 transition-colors flex items-center gap-1 cursor-pointer"
                          >
                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                            <span>Descartar de la cola</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <FeedbackSyncPanel refreshKey={syncRefreshKey} />

      {/* ==================================================================== */}
      {/* 4. MODAL EXPLORADOR DE ARCHIVOS POR CLASE */}
      {/* ==================================================================== */}
      {inspectingDataset && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#16171b] border border-[#2d303b] rounded-2xl w-full max-w-2xl max-h-[80vh] flex flex-col shadow-2xl transition-all duration-150">
            <div className="flex items-center justify-between p-4 border-b border-[#23252e]">
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                </svg>
                <h2 className="text-sm font-bold text-white">
                  Contenido de: datasets/{inspectingDataset}/
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setInspectingDataset(null)}
                className="text-gray-400 hover:text-white p-1 rounded-lg hover:bg-[#23252e] transition-colors"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-2 text-xs">
              {isLoadingFiles ? (
                <div className="py-12 text-center text-gray-400">
                  <svg className="w-5 h-5 animate-spin mx-auto text-emerald-400 mb-2" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  <span>Cargando archivos desde GCS...</span>
                </div>
              ) : datasetFiles.length === 0 ? (
                <p className="text-center text-gray-500 py-8">
                  No se encontraron archivos en este dataset.
                </p>
              ) : (
                <div className="divide-y divide-[#23252e]">
                  {datasetFiles.map((file, idx) => (
                    <div key={idx} className="py-2 flex items-center justify-between hover:bg-[#1c1e24] px-2 rounded">
                      <div className="flex items-center gap-2 overflow-hidden">
                        <span className="px-1.5 py-0.5 rounded text-[10px] bg-[#1f2128] text-emerald-400 border border-[#2e323e] font-mono flex-shrink-0">
                          {file.class_name}
                        </span>
                        <span className="font-mono text-gray-200 truncate">{file.name}</span>
                      </div>
                      <div className="flex items-center gap-3 text-[11px] text-gray-400 font-mono flex-shrink-0">
                        <span>{formatBytes(file.size_bytes)}</span>
                        <span>{file.updated ? new Date(file.updated).toLocaleDateString() : ""}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="p-3 border-t border-[#23252e] flex justify-between items-center bg-[#111215] rounded-b-2xl text-xs text-gray-400">
              <span>Total: {datasetFiles.length} archivo(s)</span>
              <button
                type="button"
                onClick={() => setInspectingDataset(null)}
                className="px-3 py-1 bg-[#1f2128] hover:bg-[#2a2d37] text-gray-200 rounded-lg transition-colors"
              >
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ==================================================================== */}
      {/* 5. TARJETA: MÉTRICAS DE SINCRONIZACIÓN (RF_02) Y TENSORES (RF_03) */}
      {/* ==================================================================== */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1">
          <span className="text-xs text-gray-300 font-semibold block flex items-center gap-1.5">
            Resultados de la última descarga GCS → Local
          </span>
          <span className="text-[11px] text-gray-500 font-mono">
            Conteos informados por el servidor
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
          <div className="bg-[#111215] border border-[#1f2128] rounded-lg p-3">
            <span className="text-gray-400 text-[11px] block">Nuevos Descargados</span>
            <span className="text-lg font-bold text-emerald-400 font-mono">
              {syncProgress.downloaded}
            </span>
          </div>
          <div className="bg-[#111215] border border-[#1f2128] rounded-lg p-3">
            <span className="text-gray-400 text-[11px] block">Omitidos (Ya al día)</span>
            <span className="text-lg font-bold text-blue-400 font-mono">
              {syncProgress.skipped}
            </span>
          </div>
          <div className="bg-[#111215] border border-[#1f2128] rounded-lg p-3">
            <span className="text-gray-400 text-[11px] block">Errores Transferencia</span>
            <span className="text-lg font-bold text-red-400 font-mono">
              {syncProgress.failed}
            </span>
          </div>
        </div>
      </div>

      {/* ==================================================================== */}
      {/* 6. CONSOLA DE LOGS EN VIVO */}
      {/* ==================================================================== */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-300 font-semibold block">
              Consola de Logs en Tiempo Real
            </span>
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          </div>
          <button
            type="button"
            onClick={() => setLogs([])}
            className="text-[11px] text-gray-500 hover:text-gray-300 transition-colors"
          >
            Limpiar consola
          </button>
        </div>

        <div
          ref={logsContainerRef}
          className="bg-[#0f1013] rounded-lg p-3.5 font-mono text-[11px] leading-relaxed text-gray-300 border border-[#1f2128] space-y-1 overflow-y-auto max-h-56"
        >
          {logs.length === 0 ? (
            <p className="text-gray-600 italic">No hay registros aún.</p>
          ) : (
            logs.map((log) => {
              let badgeColor = "text-blue-400 bg-blue-950/70";
              if (log.level === "WARN") badgeColor = "text-yellow-400 bg-yellow-950/70";
              if (log.level === "ERROR") badgeColor = "text-red-400 bg-red-950/70";
              if (log.level === "SUCCESS") badgeColor = "text-emerald-400 bg-emerald-950/70";

              return (
                <p key={log.id} className="flex items-baseline gap-2 flex-wrap sm:flex-nowrap">
                  <span className="text-gray-500 flex-shrink-0 text-[10px]">
                    {log.timestamp}
                  </span>
                  <span className={`px-1.5 py-0.2 rounded text-[10px] font-semibold flex-shrink-0 ${badgeColor}`}>
                    {log.level}
                  </span>
                  <span className="text-gray-200">{log.message}</span>
                </p>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
