"use client";

import { useState, useEffect, useRef, useCallback } from "react";

// ============================================================================
// INTERFACES DEL MODELO DE DOMINIO DE INGESTA (RF_02)
// Jerarquía: datasets/{dataset_name}/{class_label}/{audio_file.wav}
// ============================================================================
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

const CHILEAN_SPECIES_PRESETS = [
  "Chucao",
  "Canastero",
  "Chercán",
  "Chincol",
  "Churrín de la Mocha",
  "Churrín del sur",
  "Colilarga",
  "Fío-fío",
  "Picaflor chico",
  "Rayadito",
  "Tapaculo",
  "Tijeral",
  "Tordo",
  "Turca",
  "Zorzal patagónico",
];



function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

export default function IngestionView() {
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

  // Subida de audios (Local -> GCS) con Jerarquía Dataset/Clase
  const [showUploadModal, setShowUploadModal] = useState<boolean>(false);
  const [selectedDatasetOption, setSelectedDatasetOption] = useState<string>("AvesChilenas");
  const [customDatasetName, setCustomDatasetName] = useState<string>("");
  const [selectedClassOption, setSelectedClassOption] = useState<string>("Chucao");
  const [customClassName, setCustomClassName] = useState<string>("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadProgressMsg, setUploadProgressMsg] = useState<string>("");

  // Explorador de archivos de un dataset
  const [inspectingDataset, setInspectingDataset] = useState<string | null>(null);
  const [datasetFiles, setDatasetFiles] = useState<DatasetFile[]>([]);
  const [isLoadingFiles, setIsLoadingFiles] = useState<boolean>(false);

  // Consola de Logs reactiva
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const logsContainerRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

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

  // Cargar estado de almacenamiento y datasets al montar
  const fetchStatus = useCallback(async () => {
    setIsLoadingStatus(true);
    try {
      const res = await fetch("http://127.0.0.1:8000/api/ingestion/status");
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
      const res = await fetch("http://127.0.0.1:8000/api/ingestion/datasets");
      if (res.ok) {
        const data = await res.json();
        setDatasets(data.datasets || []);
        addLog("INFO", `Se listaron ${data.datasets?.length || 0} dataset(s) en Google Cloud Storage.`);
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

  useEffect(() => {
    addLog("INFO", "Inicializando módulo de ingesta con arquitectura jerárquica Data Lake...");
    fetchStatus();
    fetchDatasets();
  }, [fetchStatus, fetchDatasets, addLog]);

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
      const res = await fetch("http://127.0.0.1:8000/api/ingestion/sync", {
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

      // Detallar logs por dataset
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

      // Refrescar lista de datasets para actualizar contadores locales
      await fetchDatasets();
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      addLog("ERROR", `Fallo en el proceso de sincronización: ${errMsg}`);
    } finally {
      setIsSyncing(false);
      setSelectedIds([]);
    }
  };

  // Subida de Archivos a GCS con Jerarquía Dataset/Clase
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const validFiles = Array.from(e.target.files).filter((f) =>
        f.name.toLowerCase().endsWith(".wav")
      );
      setUploadFiles(validFiles);
      if (validFiles.length < e.target.files.length) {
        addLog("WARN", "Algunos archivos no tenían formato .wav y fueron omitidos.");
      }
    }
  };

  const getTargetDatasetName = (): string => {
    if (selectedDatasetOption === "custom") {
      return customDatasetName.trim();
    }
    return selectedDatasetOption;
  };

  const getTargetClassName = (): string => {
    if (selectedClassOption === "custom") {
      return customClassName.trim();
    }
    return selectedClassOption;
  };

  const handleUploadToGCS = async () => {
    const targetDataset = getTargetDatasetName();
    const targetClass = getTargetClassName() || "General";

    if (!targetDataset) {
      addLog("WARN", "Debe especificar un nombre de dataset válido.");
      return;
    }
    if (uploadFiles.length === 0) {
      addLog("WARN", "Seleccione al menos un archivo .wav para subir.");
      return;
    }

    setIsUploading(true);
    const destPath = `datasets/${targetDataset}/${targetClass}/`;
    setUploadProgressMsg(`Subiendo ${uploadFiles.length} archivo(s) a ${destPath}...`);
    addLog("INFO", `Subiendo ${uploadFiles.length} archivo(s) a ${destPath} en GCS...`);

    const formData = new FormData();
    formData.append("dataset_name", targetDataset);
    formData.append("class_label", targetClass);
    uploadFiles.forEach((file) => {
      formData.append("files", file);
    });

    try {
      const res = await fetch("http://127.0.0.1:8000/api/ingestion/upload", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: Fallo al subir archivos.`);
      }

      const data = await res.json();
      addLog(
        "SUCCESS",
        `Subida exitosa: ${data.uploaded} archivo(s) almacenados en '${destPath}' en GCS.`
      );
      setUploadFiles([]);
      setShowUploadModal(false);
      // Refrescar estado de GCS y datasets
      await fetchStatus();
      await fetchDatasets();
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      addLog("ERROR", `Error durante la subida a GCS: ${errMsg}`);
    } finally {
      setIsUploading(false);
      setUploadProgressMsg("");
    }
  };

  // Inspeccionar archivos de un dataset
  const handleInspectDataset = async (datasetName: string) => {
    setInspectingDataset(datasetName);
    setIsLoadingFiles(true);
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/ingestion/datasets/${datasetName}/files`);
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
              Ingesta y Data Lake
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
            }}
            title="Refrescar estado de GCS"
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

          {/* Botón Acción: Subir a GCS */}
          <button
            type="button"
            onClick={() => setShowUploadModal(!showUploadModal)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-300 shadow-sm ${
              showUploadModal
                ? "text-gray-300 bg-[#1e2129] hover:bg-[#282c37] border border-[#3a4050]"
                : "text-emerald-300 bg-emerald-950/50 hover:bg-emerald-900/60 border border-emerald-700/60"
            }`}
          >
            <svg
              className={`w-3.5 h-3.5 transition-transform duration-300 ${
                showUploadModal ? "rotate-90 text-gray-400" : "text-emerald-400"
              }`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              {showUploadModal ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              )}
            </svg>
            <span>{showUploadModal ? "Cerrar Panel" : "Subir audios a GCS"}</span>
          </button>
        </div>
      </div>

      {/* ==================================================================== */}
      {/* 2. PANEL DE CARGA MASIVA CON JERARQUÍA DATASET / CLASE */}
      {/* ==================================================================== */}
      <div
        className={`accordion-grid ${
          showUploadModal ? "accordion-grid-open" : "accordion-grid-closed"
        }`}
      >
        <div className="overflow-hidden">
          <div
            className={`transition-all duration-350 ease-out transform ${
              showUploadModal
                ? "translate-y-0 opacity-100 scale-100 pb-1"
                : "-translate-y-3 opacity-0 scale-[0.99]"
            }`}
          >
            <div className="bg-[#14161c] border border-emerald-900/40 rounded-xl p-5 space-y-4 shadow-xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-[#23252e] pb-3">
                <div className="flex items-center gap-2">
                  <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                  <div>
                    <span className="text-xs font-semibold text-white block">
                      Carga Jerárquica al Data Lake (Cloud Storage)
                    </span>
                    <span className="text-[11px] text-gray-400 font-mono">
                      Estructura: datasets / &lt;Dataset&gt; / &lt;Clase&gt; / &lt;audio.wav&gt;
                    </span>
                  </div>
                </div>
                <span className="text-[11px] text-gray-400 font-mono">
                  Bucket: {storageStatus?.bucket || "fama-audio-records-2026"}
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                {/* 1. Selección de Dataset Dinámico (detecta datasets reales en el bucket) */}
                <div className="space-y-1.5">
                  <label className="text-gray-300 font-medium block">
                    1. Dataset de Destino (Colección):
                  </label>
                  <select
                    value={selectedDatasetOption}
                    onChange={(e) => {
                      const val = e.target.value;
                      setSelectedDatasetOption(val);
                      if (val === "AvesChilenas") {
                        setSelectedClassOption("Chucao");
                      } else {
                        const ds = datasets.find((d) => d.name === val);
                        const validClasses = ds?.classes?.filter((c) => c && c !== "General") || [];
                        if (validClasses.length > 0) {
                          setSelectedClassOption(validClasses[0]);
                        } else {
                          setSelectedClassOption("General");
                        }
                      }
                    }}
                    className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-emerald-600 font-mono"
                  >
                    <option value="AvesChilenas">
                      AvesChilenas (Dominio Bioacústico Piloto)
                    </option>
                    {datasets
                      .filter((d) => d.name !== "AvesChilenas")
                      .map((d) => (
                        <option key={d.id} value={d.name}>
                          {d.name} ({d.file_count} audios, {d.class_count || 1} clases)
                        </option>
                      ))}
                    <option value="__custom__">+ Crear Nueva Colección / Dataset...</option>
                  </select>

                  {selectedDatasetOption === "__custom__" && (
                    <input
                      type="text"
                      placeholder="Ej. Murcielagos_Chile o BioacusticaUrbana"
                      value={customDatasetName}
                      onChange={(e) => setCustomDatasetName(e.target.value)}
                      className="w-full bg-[#111215] border border-emerald-700/60 rounded-lg px-3 py-1.5 text-xs text-emerald-300 placeholder-gray-500 focus:outline-none focus:border-emerald-500 font-mono mt-1"
                    />
                  )}
                </div>

                {/* 2. Selección de Clase o Categoría */}
                <div className="space-y-1.5">
                  <label className="text-gray-300 font-medium block">
                    2. Etiqueta de Clase (Especie / Categoría):
                  </label>
                  <select
                    value={selectedClassOption}
                    onChange={(e) => setSelectedClassOption(e.target.value)}
                    className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-emerald-600 font-mono"
                  >
                    {selectedDatasetOption === "AvesChilenas" ? (
                      CHILEAN_SPECIES_PRESETS.map((sp) => (
                        <option key={sp} value={sp}>
                          {sp}
                        </option>
                      ))
                    ) : (
                      <>
                        <option value="General">General (Sin clasificar)</option>
                        {datasets
                          .find((d) => d.name === selectedDatasetOption)
                          ?.classes?.filter((c) => c && c !== "General")
                          .map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                      </>
                    )}
                    <option value="__custom_class__">+ Definir Nueva Clase...</option>
                  </select>

                  {selectedClassOption === "__custom_class__" && (
                    <input
                      type="text"
                      placeholder="Ej. Elaenia_albiceps o Canto_Alarma"
                      value={customClassName}
                      onChange={(e) => setCustomClassName(e.target.value)}
                      className="w-full bg-[#111215] border border-emerald-700/60 rounded-lg px-3 py-1.5 text-xs text-emerald-300 placeholder-gray-500 focus:outline-none focus:border-emerald-500 font-mono mt-1"
                    />
                  )}
                </div>
              </div>

              {/* 3. Dropzone de Archivos .wav */}
              <div
                onClick={() => fileInputRef.current?.click()}
                className="border-2 border-dashed border-[#2d303b] hover:border-emerald-600/70 transition-colors rounded-xl p-5 text-center bg-[#111215]/60 cursor-pointer"
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".wav,audio/wav"
                  onChange={handleFileChange}
                  className="hidden"
                />
                <div className="flex flex-col items-center justify-center space-y-1.5 pointer-events-none">
                  <svg className="w-8 h-8 text-emerald-400/80 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                  </svg>
                  <p className="text-xs font-semibold text-gray-200">
                    Arrastra o haz clic para seleccionar grabaciones .wav
                  </p>
                  <p className="text-[11px] text-gray-500">
                    Destino: <span className="font-mono text-emerald-400">datasets/{selectedDatasetOption === "__custom__" ? customDatasetName || "MiDataset" : selectedDatasetOption}/{selectedClassOption === "__custom_class__" ? customClassName || "MiClase" : selectedClassOption}/</span>
                  </p>
                </div>
              </div>

              {/* Archivos seleccionados en cola */}
              {uploadFiles.length > 0 && (
                <div className="bg-[#101114] border border-[#23252e] rounded-lg p-3 space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-gray-300">
                      Archivos en cola ({uploadFiles.length}):
                    </span>
                    <button
                      type="button"
                      onClick={() => setUploadFiles([])}
                      className="text-[11px] text-red-400 hover:underline"
                    >
                      Limpiar lista
                    </button>
                  </div>
                  <div className="max-h-28 overflow-y-auto space-y-1 pr-1">
                    {uploadFiles.map((f, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between text-[11px] font-mono bg-[#16171b] px-2.5 py-1 rounded text-gray-300"
                      >
                        <span className="truncate max-w-xs">{f.name}</span>
                        <span className="text-gray-500">{formatBytes(f.size)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex items-center justify-between pt-2 border-t border-[#23252e]">
                <span className="text-[11px] text-gray-400">
                  {uploadFiles.length > 0 &&
                    `Tamaño total a transferir: ${formatBytes(
                      uploadFiles.reduce((acc, f) => acc + f.size, 0)
                    )}`}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowUploadModal(false)}
                    className="px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white bg-transparent border border-transparent hover:border-[#2d303b] transition-colors"
                  >
                    Cancelar
                  </button>
                  <button
                    type="button"
                    onClick={handleUploadToGCS}
                    disabled={isUploading || uploadFiles.length === 0}
                    className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-md flex items-center gap-1.5"
                  >
                    {isUploading ? (
                      <>
                        <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                        </svg>
                        <span>{uploadProgressMsg || "Subiendo a GCS..."}</span>
                      </>
                    ) : (
                      <span>Subir al Data Lake</span>
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ==================================================================== */}
      {/* 3. TABLA DE DATASETS REALES EN GCS (RF_02) */}
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
                        Sube audios para crear tu primera colección organizada por especie o categoría acústica.
                      </p>
                      <button
                        type="button"
                        onClick={() => setShowUploadModal(true)}
                        className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-emerald-400 bg-emerald-950/40 border border-emerald-800/60 hover:bg-emerald-900/50 transition-colors"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                        </svg>
                        Cargar primer dataset ahora
                      </button>
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
                    <td className="py-2.5 font-medium text-gray-200 flex items-center gap-2">
                      <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                      </svg>
                      <span className="font-semibold">{d.name}</span>
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
      {/* 4. MODAL EXPLORADOR DE ARCHIVOS POR CLASE */}
      {/* ==================================================================== */}
      {inspectingDataset && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#16171b] border border-[#2d303b] rounded-2xl w-full max-w-2xl max-h-[80vh] flex flex-col shadow-2xl animate-in zoom-in-95 duration-150">
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
