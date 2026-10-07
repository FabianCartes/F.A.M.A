"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE_URL } from "@/lib/api";
import {
  getPendingFeedback,
  approveFeedback,
  rejectFeedback,
} from "@/lib/api/feedbackApi";
import { PendingFeedbackItem } from "@/lib/schemas/feedback";
import FeedbackSyncPanel from "@/components/feedback/FeedbackSyncPanel";

// ============================================================================
// INTERFACES DEL MODELO DE DOMINIO DE INGESTA (RF_02 / RF_06 / ADR 0013)
// ============================================================================
export interface IngestionViewProps {
  onNavigate?: (view: string) => void;
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

export default function IngestionView({ onNavigate }: IngestionViewProps = {}) {
  // Estado de almacenamiento GCS
  const [storageStatus, setStorageStatus] = useState<StorageStatus | null>(null);
  const [isLoadingStatus, setIsLoadingStatus] = useState<boolean>(true);

  // Lista de datasets en GCS
  const [datasets, setDatasets] = useState<DatasetItem[]>([]);
  const [isLoadingDatasets, setIsLoadingDatasets] = useState<boolean>(true);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  // Sincronización masiva (RF_02 GCS -> Local) y Preprocesamiento Tensorial (RF_03)
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [autoPreprocess, setAutoPreprocess] = useState<boolean>(true);
  const [syncProgress, setSyncProgress] = useState<{
    downloaded: number;
    skipped: number;
    failed: number;
    preprocessed: number;
    total: number;
  }>({ downloaded: 0, skipped: 0, failed: 0, preprocessed: 0, total: 0 });

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

  // Sincronización Masiva Bidireccional (RF_02) y Preprocesamiento Tensorial (RF_03)
  const handleSync = async () => {
    if (selectedIds.length === 0 || isSyncing) return;
    setIsSyncing(true);
    addLog(
      "INFO",
      `Iniciando sincronización masiva de ${selectedIds.length} dataset(s) [GCS → Local]${
        autoPreprocess ? " con preprocesamiento tensorial (Librosa)" : ""
      }...`
    );

    let totalDownload = 0;
    let totalSkip = 0;
    let totalFail = 0;
    let totalPrep = 0;

    try {
      const res = await fetch(`${API_BASE_URL}/api/ingestion/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          datasets: selectedIds,
          preprocess: autoPreprocess,
        }),
      });

      if (!res.ok) {
        throw new Error(`Error en el servidor: HTTP ${res.status}`);
      }

      const data = await res.json();
      totalDownload = data.total_downloaded || 0;
      totalSkip = data.total_skipped || 0;
      totalFail = data.total_failed || 0;
      totalPrep = data.total_preprocessed || 0;

      setSyncProgress({
        downloaded: totalDownload,
        skipped: totalSkip,
        failed: totalFail,
        preprocessed: totalPrep,
        total: totalDownload + totalSkip + totalFail,
      });

      for (const item of data.results || []) {
        if (item.failed > 0) {
          addLog("ERROR", `Dataset '${item.dataset}': ${item.failed} error(es) en la descarga.`);
        }
        addLog(
          "SUCCESS",
          `Dataset '${item.dataset}': ${item.downloaded} descargados nuevos, ${item.skipped} omitidos (ya actualizados localmente).`
        );
        if (autoPreprocess && item.preprocessed > 0) {
          addLog(
            "SUCCESS",
            `Dataset '${item.dataset}': ${item.preprocessed} espectrograma(s) Mel generados en backend/data/processed/.`
          );
        }
        if (item.db_persisted) {
          addLog(
            "INFO",
            `Dataset '${item.dataset}': Registrado y actualizado en PostgreSQL (tablas conjunto_datos y audio).`
          );
        }
      }

      addLog(
        "SUCCESS",
        `Sincronización completada: ${totalDownload} archivo(s) descargados, ${totalSkip} omitidos, ${totalPrep} tensores procesados.`
      );

      await fetchDatasets();
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
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
      await Promise.all([fetchDatasets(), fetchPendingFeedbacks()]);
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
              Gestión multi-dataset y sincronización selectiva nube ↔ GPU local
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
      {/* 2. TABLA DE DATASETS REALES EN GCS (RF_02) */}
      {/* ==================================================================== */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-200 font-semibold block">
              Datasets Disponibles en GCS (Data Lake)
            </span>
            <span className="text-[10px] px-2 py-0.5 rounded bg-[#1c1e24] text-gray-400 font-mono">
              {datasets.length} colecciones
            </span>
          </div>

          <button
            type="button"
            onClick={fetchDatasets}
            disabled={isLoadingDatasets}
            className="text-[11px] text-gray-400 hover:text-gray-200 transition-colors flex items-center gap-1"
          >
            <svg className={`w-3 h-3 ${isLoadingDatasets ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            <span>Actualizar</span>
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-[#23252e] text-gray-400">
                <th className="pb-3 w-8">
                  <input
                    type="checkbox"
                    checked={datasets.length > 0 && selectedIds.length === datasets.length}
                    onChange={toggleSelectAll}
                    disabled={datasets.length === 0}
                    className="rounded bg-[#121316] border-[#2d303b] text-emerald-600 focus:ring-0 cursor-pointer"
                  />
                </th>
                <th className="pb-3 font-medium">Dataset (Colección)</th>
                <th className="pb-3 font-medium">Clases / Categorías</th>
                <th className="pb-3 font-medium">Archivos en Nube</th>
                <th className="pb-3 font-medium">Archivos Locales</th>
                <th className="pb-3 font-medium">Tamaño GCS</th>
                <th className="pb-3 font-medium">Última Modificación</th>
                <th className="pb-3 font-medium text-center">Estado</th>
                <th className="pb-3 font-medium text-right pr-2">Acción</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#23252e]/60">
              {isLoadingDatasets ? (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-gray-400">
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
                  <td colSpan={9} className="py-8 text-center">
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
                  <tr key={d.id} className="hover:bg-[#1c1e24]/40 transition-colors">
                    <td className="py-2.5">
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(d.id)}
                        onChange={() => toggleSelect(d.id)}
                        className="rounded bg-[#121316] border-[#2d303b] text-emerald-600 focus:ring-0 cursor-pointer"
                      />
                    </td>
                    <td className="py-2.5 font-medium text-gray-200">
                      <div className="flex items-center gap-2">
                        <svg className="w-3.5 h-3.5 text-emerald-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                        </svg>
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-semibold">{d.name}</span>
                          <span
                            className={`text-[9px] font-mono px-1.5 py-0.2 rounded border ${
                              d.domain === "industrial" || d.name === "engine_diagnostics"
                                ? "bg-amber-950/70 border-amber-800/60 text-amber-300"
                                : "bg-emerald-950/70 border-emerald-800/60 text-emerald-400"
                            }`}
                          >
                            {d.domain === "industrial" || d.name === "engine_diagnostics"
                              ? "Industrial"
                              : "Bioacústica"}
                          </span>
                          <span
                            className={`text-[9px] font-mono px-1.5 py-0.2 rounded border ${
                              d.source === "local" || d.gcs_available === false
                                ? "bg-slate-800/80 border-slate-600/60 text-slate-300"
                                : "bg-sky-950/70 border-sky-800/60 text-sky-400"
                            }`}
                          >
                            {d.source === "local" || d.gcs_available === false ? "Local" : "Cloud GCS"}
                          </span>
                        </div>
                      </div>
                    </td>
                    <td className="py-2.5 text-gray-300">
                      <div className="flex items-center gap-1 flex-wrap max-w-xs">
                        {d.classes && d.classes.length > 0 ? (
                          d.classes.slice(0, 3).map((cls) => (
                            <span
                              key={cls}
                              className="px-1.5 py-0.5 rounded text-[10px] bg-[#222530] text-gray-300 border border-[#2e323e]"
                            >
                              {cls}
                            </span>
                          ))
                        ) : (
                          <span className="text-gray-500 italic">General</span>
                        )}
                        {d.classes && d.classes.length > 3 && (
                          <span className="text-[10px] text-gray-400">
                            +{d.classes.length - 3} más
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-2.5 text-gray-300 font-mono">{d.file_count} audios</td>
                    <td className="py-2.5 text-gray-400 font-mono">
                      <span className={d.local_file_count >= d.file_count ? "text-emerald-400" : "text-amber-400"}>
                        {d.local_file_count}
                      </span>
                      /{d.file_count}
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
                    <td className="py-2.5 text-center">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-medium inline-block ${
                          d.is_synced
                            ? "bg-emerald-950/70 text-emerald-400 border border-emerald-800/60"
                            : "bg-amber-950/70 text-amber-400 border border-amber-800/60"
                        }`}
                      >
                        {d.is_synced ? "Sincronizado" : "Pendiente"}
                      </span>
                    </td>
                    <td className="py-2.5 text-right pr-2">
                      <button
                        type="button"
                        onClick={() => handleInspectDataset(d.name)}
                        className="text-[11px] text-gray-400 hover:text-white px-2 py-1 rounded bg-[#1c1e24] hover:bg-[#252830] border border-[#2d303b] transition-colors"
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

        {/* Footer de Tabla con Acción Principal de Sincronización RF_02 y Disparador RF_03 */}
        <div className="flex flex-col lg:flex-row items-center justify-between gap-3 pt-3 border-t border-[#23252e]/70">
          <div className="flex items-center gap-3 flex-wrap w-full lg:w-auto justify-between sm:justify-start">
            <span className="text-xs text-gray-400">
              {selectedIds.length} dataset(s) seleccionado(s)
            </span>

            {/* Disparador opcional de preprocesamiento */}
            <label className="flex items-center gap-2 cursor-pointer select-none bg-[#111215] hover:bg-[#161820] px-3 py-1.5 rounded-lg border border-[#262833] hover:border-emerald-700/60 transition-colors">
              <input
                type="checkbox"
                checked={autoPreprocess}
                onChange={(e) => setAutoPreprocess(e.target.checked)}
                className="rounded bg-[#1a1c24] border-[#2e323e] text-emerald-500 focus:ring-0 cursor-pointer w-4 h-4"
              />
              <span className="text-xs font-semibold text-gray-200 flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
                </svg>
                Preprocesar a tensores (Librosa)
              </span>
            </label>
          </div>

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
                  {autoPreprocess ? "Sincronizando y extrayendo tensores..." : "Sincronizando desde GCS..."}
                </span>
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                <span>Descargar Dataset al Entorno Local</span>
              </>
            )}
          </button>
        </div>
      </div>

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
            Métricas de Sincronización y Preprocesamiento
          </span>
          <span className="text-[11px] text-gray-500 font-mono">
            Persistencia en PostgreSQL + Tensores Librosa
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
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
            <span className="text-gray-400 text-[11px] block">Tensores Preprocesados</span>
            <span className="text-lg font-bold text-amber-400 font-mono">
              {syncProgress.preprocessed}
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
