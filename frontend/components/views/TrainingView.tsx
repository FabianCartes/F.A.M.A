"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";

// ============================================================================
// INTERFACES DEL DOMINIO DE ENTRENAMIENTO (RF_04, CU_INV_02, CU_INV_03)
// ============================================================================
interface HardwareStatus {
  cuda_available: boolean;
  device_name: string;
  vram_total_gb: number;
  vram_used_gb: number;
  vram_percent: number;
  cpu_percent?: number;
  load_status?: string;
  load_level?: "normal" | "warning" | "danger";
  temperature_c?: number;
  status: string;
}

interface TrainingDataset {
  id: string;
  name: string;
  audio_count: number;
  class_count?: number;
  classes?: string[];
  size_mb?: number;
  estado?: string;
  db_id?: number | null;
}

interface MetricPoint {
  epoca: number;
  train_loss: number;
  val_loss: number;
  train_acc: number;
  val_acc: number;
  tiempo_epoca: number;
}

interface LogEntry {
  id: string;
  timestamp: string;
  level: string;
  message: string;
}

interface ModelHistoryItem {
  id: number;
  architecture: string;
  epochs: number;
  accuracy: number;
  loss: number;
  active: boolean;
  status: string;
  filename: string;
  created_at: string | null;
}

const ARCHITECTURE_PRESETS: Record<
  string,
  { lr: string; epochs: string; batch: string; desc: string }
> = {
  "EfficientNet-B0": {
    lr: "0.001",
    epochs: "10",
    batch: "16",
    desc: "Transfer Learning & Pitch Shift (Recomendada)",
  },
  "ConvNeXt-Nano": {
    lr: "0.0005",
    epochs: "12",
    batch: "16",
    desc: "Gradiente fino y regularización moderna",
  },
  "ResNet-34d": {
    lr: "0.0003",
    epochs: "15",
    batch: "8",
    desc: "Batches moderados para estabilidad profunda",
  },
  "PANNs-CNN14": {
    lr: "0.0005",
    epochs: "15",
    batch: "16",
    desc: "Red pre-entrenada para acústica industrial y patrones armónicos",
  },
  "AudioCNN": {
    lr: "0.001",
    epochs: "20",
    batch: "32",
    desc: "Baseline convolucional clásico F.A.M.A.",
  },
};

export default function TrainingView() {
  // 1. Estado de Configuración (IE_03)
  const [selectedDataset, setSelectedDataset] = useState<string>("AvesChilenas");
  const [learningRate, setLearningRate] = useState<string>("0.001");
  const [epochs, setEpochs] = useState<string>("10");
  const [batchSize, setBatchSize] = useState<string>("16");
  const [framework, setFramework] = useState<string>("pytorch");
  const [architecture, setArchitecture] = useState<string>("EfficientNet-B0");
  const [trainingMode, setTrainingMode] = useState<"single" | "triad">("single");
  const [triadProgress, setTriadProgress] = useState<{
    isTriad: boolean;
    modelIdx: number;
    totalModels: number;
    currentArch: string;
  }>({
    isTriad: false,
    modelIdx: 1,
    totalModels: 1,
    currentArch: "",
  });

  // 2. Telemetría de Hardware y Datasets
  const [hardware, setHardware] = useState<HardwareStatus | null>(null);
  const [datasets, setDatasets] = useState<TrainingDataset[]>([]);
  const currentDataset = datasets.find((d) => d.id === selectedDataset) || datasets[0] || {
    id: "AvesChilenas",
    name: "AvesChilenas (1211 audios)",
    audio_count: 1211,
    class_count: 15,
    size_mb: 340.5,
  };

  // 3. Ciclo de Vida del Entrenamiento (RF_04 / CU_INV_03)
  const [isTraining, setIsTraining] = useState<boolean>(false);
  const [isStopping, setIsStopping] = useState<boolean>(false);
  const [trainingJobId, setTrainingJobId] = useState<string | null>(null);
  const [currentEpoch, setCurrentEpoch] = useState<number>(0);
  const [totalEpochs, setTotalEpochs] = useState<number>(10);
  const [currentTrainLoss, setCurrentTrainLoss] = useState<number>(0.0);
  const [currentValLoss, setCurrentValLoss] = useState<number>(0.0);
  const [currentTrainAcc, setCurrentTrainAcc] = useState<number>(0.0);
  const [currentValAcc, setCurrentValAcc] = useState<number>(0.0);
  const [metricsHistory, setMetricsHistory] = useState<MetricPoint[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);

  // 4. Historial de Modelos (CU_INV_04 / CU_INV_05)
  const [history, setHistory] = useState<ModelHistoryItem[]>([]);
  const [activatingId, setActivatingId] = useState<number | null>(null);

  const logsContainerRef = useRef<HTMLDivElement | null>(null);

  // Cambio dinámico de arquitectura con auto-rellenado de hiperparámetros recomendados
  const handleArchitectureChange = (newArch: string) => {
    setArchitecture(newArch);
    const preset = ARCHITECTURE_PRESETS[newArch];
    if (preset) {
      setLearningRate(preset.lr);
      setEpochs(preset.epochs);
      setBatchSize(preset.batch);
    }
  };

  // Estimador dinámico de tiempo previo al inicio (CPU vs GPU CUDA)
  const estimatedDuration = useMemo(() => {
    const audios = currentDataset?.audio_count || 1211;
    const numBatch = parseInt(batchSize, 10) || 16;
    const numEpochs = parseInt(epochs, 10) || 10;
    const stepsPerEpoch = Math.max(1, Math.ceil(audios / Math.max(1, numBatch)));
    const isCuda = hardware?.cuda_available ?? false;
    const msPerStep = isCuda ? 25 : 150;
    const singleSec = (stepsPerEpoch * numEpochs * msPerStep) / 1000;
    const totalSec = trainingMode === "triad" ? singleSec * 3 : singleSec;

    if (totalSec < 60) return `~${Math.ceil(totalSec)} seg`;
    const minutes = Math.round(totalSec / 60);
    if (minutes < 60) return `~${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const remMin = minutes % 60;
    return `~${hours}h ${remMin}m`;
  }, [currentDataset, batchSize, epochs, hardware, trainingMode]);

  // Cargar telemetría de hardware
  const fetchHardware = useCallback(async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/api/training/hardware");
      if (res.ok) {
        const data = await res.json();
        setHardware(data);
      }
    } catch {
      // Si el backend no está disponible temporalmente
    }
  }, []);

  // Cargar datasets disponibles
  const fetchDatasets = useCallback(async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/api/training/datasets");
      if (res.ok) {
        const data = await res.json();
        setDatasets(data.datasets || []);
      }
    } catch {
      // Silenciar error transitorio
    }
  }, []);

  // Cargar historial de modelos desde PostgreSQL
  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/api/training/history");
      if (res.ok) {
        const data = await res.json();
        setHistory(data.history || []);
      }
    } catch {
      // Silenciar error transitorio
    }
  }, []);

  // Inicialización de datos
  useEffect(() => {
    fetchHardware();
    fetchDatasets();
    fetchHistory();
  }, [fetchHardware, fetchDatasets, fetchHistory]);

  // Autoscroll de consola
  useEffect(() => {
    if (logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
    }
  }, [logs]);

  // Sondeo de progreso en vivo mientras se entrena
  useEffect(() => {
    let timer: NodeJS.Timeout | null = null;

    if (isTraining) {
      timer = setInterval(async () => {
        try {
          const res = await fetch("http://127.0.0.1:8000/api/training/progress");
          if (res.ok) {
            const data = await res.json();
            setCurrentEpoch(data.epoch || 0);
            setTotalEpochs(data.total_epochs || parseInt(epochs) || 10);
            setCurrentTrainLoss(data.train_loss || 0.0);
            setCurrentValLoss(data.val_loss || 0.0);
            setCurrentTrainAcc(data.train_acc || 0.0);
            setCurrentValAcc(data.val_acc || 0.0);
            setMetricsHistory(data.metrics_history || []);
            setLogs(data.logs || []);

            if (data.is_tri_model) {
              setTriadProgress({
                isTriad: true,
                modelIdx: data.current_model_index || 1,
                totalModels: data.total_models || 3,
                currentArch: data.current_architecture || architecture,
              });
            }

            if (data.status === "completed" || data.status === "failed" || data.status === "stopped") {
              setIsTraining(false);
              setIsStopping(false);
              fetchHistory();
              fetchHardware();
            }
          }
        } catch {
          // Reintento en próximo ciclo
        }
      }, 1000);
    }

    return () => {
      if (timer) clearInterval(timer);
    };
  }, [isTraining, epochs, architecture, fetchHistory, fetchHardware]);

  // Iniciar Entrenamiento (CU_INV_03)
  const handleStartTraining = async () => {
    if (isTraining) return;
    setIsTraining(true);
    setIsStopping(false);
    setMetricsHistory([]);
    setCurrentEpoch(0);
    if (trainingMode === "triad") {
      const isEngine = selectedDataset === "engine_diagnostics";
      setTriadProgress({
        isTriad: true,
        modelIdx: 1,
        totalModels: 3,
        currentArch: isEngine ? "ResNet-34d" : "EfficientNet-B0",
      });
    } else {
      setTriadProgress({
        isTriad: false,
        modelIdx: 1,
        totalModels: 1,
        currentArch: architecture,
      });
    }

    try {
      const res = await fetch("http://127.0.0.1:8000/api/training/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dataset_name: selectedDataset,
          architecture,
          epochs: parseInt(epochs) || 10,
          learning_rate: parseFloat(learningRate) || 0.001,
          batch_size: parseInt(batchSize) || 16,
          framework,
          is_tri_model: trainingMode === "triad",
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || `Error HTTP ${res.status}`);
      }

      const data = await res.json();
      setTrainingJobId(data.job_id);
    } catch (err: unknown) {
      setIsTraining(false);
      const msg = err instanceof Error ? err.message : String(err);
      alert(`No fue posible iniciar el entrenamiento: ${msg}`);
    }
  };

  // Detener Entrenamiento (CU_INV_03 Paso 2.a)
  const handleStopTraining = async () => {
    if (!isTraining || isStopping) return;
    setIsStopping(true);
    try {
      await fetch("http://127.0.0.1:8000/api/training/stop", { method: "POST" });
    } catch {
      setIsStopping(false);
    }
  };

  // Activar Modelo para Inferencia (CU_INV_05)
  const handleActivateModel = async (modelId: number) => {
    setActivatingId(modelId);
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/training/models/${modelId}/activate`, {
        method: "POST",
      });
      if (res.ok) {
        await fetchHistory();
      }
    } finally {
      setActivatingId(null);
    }
  };

  return (
    <div className="space-y-5">
      {/* ==================================================================== */}
      {/* 1. HEADER DE LA VISTA (Figura 6.8) */}
      {/* ==================================================================== */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500/20 to-indigo-500/10 border border-blue-500/30 flex items-center justify-center text-blue-400 shadow-inner">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-bold text-white tracking-tight font-heading">
              Entrenamiento y Métricas
            </h1>
            <p className="text-xs text-gray-400">
              Modelado acústico iterativo, ajuste de hiperparámetros y telemetría de cómputo
            </p>
          </div>
        </div>

        {/* Indicador de Hardware / Dispositivo */}
        <div className="flex items-center gap-2">
          {hardware?.cuda_available ? (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-cyan-950/70 border border-cyan-700/60 text-cyan-300 font-mono text-xs shadow-sm">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
              CUDA: {hardware.device_name}
            </span>
          ) : (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-950/70 border border-blue-700/60 text-blue-300 font-mono text-xs shadow-sm">
              <span className="w-2 h-2 rounded-full bg-blue-400" />
              Host: {hardware?.device_name || "Nodo de Cómputo CPU"}
            </span>
          )}
        </div>
      </div>

      {/* ==================================================================== */}
      {/* 2. FILA 1: SELECCIONAR DATASET + MONITOR GPU/HARDWARE (Figura 6.8) */}
      {/* ==================================================================== */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Tarjeta: Seleccionar Dataset */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-300 font-semibold flex items-center gap-1.5">
              <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
              </svg>
              Seleccionar Conjunto de Datos
            </span>
            {currentDataset ? (
              <span className="text-[10px] text-gray-400 font-mono px-2 py-0.5 rounded bg-[#111215] border border-[#23252e]">
                {currentDataset.audio_count ? currentDataset.audio_count.toLocaleString() : "0"} audios {currentDataset.size_mb ? `· ${currentDataset.size_mb} MB` : ""}
              </span>
            ) : null}
          </div>

          <div>
            <label className="text-[11px] text-gray-400 block mb-1.5 font-medium">
              Dataset para Entrenamiento
            </label>
            <select
              value={selectedDataset}
              onChange={(e) => setSelectedDataset(e.target.value)}
              disabled={isTraining}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-emerald-600 font-mono"
            >
              {datasets.length === 0 ? (
                <option value="AvesChilenas">AvesChilenas (1211 audios)</option>
              ) : (
                datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))
              )}
            </select>
          </div>

          <div className="flex items-center justify-between text-[11px] text-gray-400 pt-1 border-t border-[#23252e]/60">
            <span>Clases objetivo: <strong className="text-gray-200">{currentDataset?.class_count || 15} clases detectadas</strong></span>
            <span className="text-emerald-400 font-mono">Partición Grouped / Stratified</span>
          </div>
        </div>

        {/* Tarjeta: Monitor de Hardware / Cómputo */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-300 font-semibold flex items-center gap-1.5">
              <svg className="w-4 h-4 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
              </svg>
              Telemetría de Cómputo ({hardware?.cuda_available ? "GPU CUDA" : "CPU"})
            </span>
            <span
              className={`px-2 py-0.5 rounded text-[10px] font-mono font-semibold border ${
                hardware?.load_level === "danger"
                  ? "bg-rose-950/70 border-rose-800/60 text-rose-300"
                  : hardware?.load_level === "warning"
                  ? "bg-amber-950/70 border-amber-800/60 text-amber-300"
                  : "bg-emerald-950/70 border-emerald-800/60 text-emerald-300"
              }`}
            >
              {hardware?.load_status || "Carga Normal"}
            </span>
          </div>

          <div className="space-y-2.5 text-xs">
            <div>
              <div className="flex justify-between text-gray-400 text-[11px] mb-1">
                <span>Memoria {hardware?.cuda_available ? "VRAM" : "RAM"} Asignada</span>
                <span className="font-mono text-gray-200">
                  {hardware?.vram_used_gb || 0} / {hardware?.vram_total_gb || 0} GB ({hardware?.vram_percent || 0}%)
                </span>
              </div>
              <div className="w-full bg-[#111215] rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-cyan-500 h-1.5 rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(100, hardware?.vram_percent || 0)}%` }}
                />
              </div>
            </div>

            <div className="flex justify-between items-center text-[11px] pt-1">
              <span className="text-gray-400">Carga de CPU (Uso de Núcleos)</span>
              <span className="font-mono text-cyan-400 font-semibold">
                {hardware?.cpu_percent != null ? `${hardware.cpu_percent}%` : "—"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ==================================================================== */}
      {/* 3. CONFIGURACIÓN DE ENTRENAMIENTO */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4 shadow-sm">
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-300 font-semibold flex items-center gap-1.5">
            <svg className="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            </svg>
            Hiperparámetros de Modelado
          </span>
          <span className="text-[10px] text-gray-500 font-mono">
            PyTorch 2.5 con GeM Pooling y Focal Loss
          </span>
        </div>

        {/* Selector de Modo: Individual vs Tríada Completa */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-lg bg-[#111215] border border-[#23252e]">
          <div>
            <span className="text-xs font-semibold text-gray-200 block">Modo de Entrenamiento</span>
            <span className="text-[11px] text-gray-500">
              {trainingMode === "triad"
                ? selectedDataset === "engine_diagnostics"
                  ? "Entrena secuencialmente los 3 modelos (ResNet-34d ➔ EfficientNet-B0 ➔ PANNs-CNN14) para habilitar el Super-Ensamble industrial de 13 fallas de motor."
                  : "Entrena secuencialmente los 3 modelos (EfficientNet-B0 ➔ ConvNeXt-Nano ➔ ResNet-34d) para habilitar el Super-Ensamble bioacústico de aves chilenas."
                : "Entrena únicamente la arquitectura seleccionada con hiperparámetros personalizados."}
            </span>
          </div>

          <div className="flex items-center gap-1.5 p-1 bg-[#16171b] border border-[#23252e] rounded-lg flex-shrink-0">
            <button
              type="button"
              disabled={isTraining}
              onClick={() => setTrainingMode("single")}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                trainingMode === "single"
                  ? "bg-blue-600 text-white shadow-sm font-semibold"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              Modelo Individual
            </button>
            <button
              type="button"
              disabled={isTraining}
              onClick={() => setTrainingMode("triad")}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                trainingMode === "triad"
                  ? "bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-sm font-semibold"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              <svg className="w-3.5 h-3.5 text-amber-300" fill="currentColor" viewBox="0 0 20 20">
                <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
              </svg>
              <span>
                {selectedDataset === "engine_diagnostics"
                  ? "Tríada Completa (Super-Ensamble Motores)"
                  : "Tríada Completa (Super-Ensamble Aves)"}
              </span>
            </button>
          </div>
        </div>

        {/* Inputs de Hiperparámetros en Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label className="text-[11px] text-gray-400 block mb-1 font-medium">
              Learning Rate (Tasa de Aprendizaje)
            </label>
            <input
              type="text"
              value={learningRate}
              disabled={isTraining || trainingMode === "triad"}
              onChange={(e) => setLearningRate(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500 disabled:opacity-60"
            />
          </div>

          <div>
            <label className="text-[11px] text-gray-400 block mb-1 font-medium">
              Épocas de Entrenamiento
            </label>
            <input
              type="number"
              value={epochs}
              disabled={isTraining || trainingMode === "triad"}
              min="1"
              max="100"
              onChange={(e) => setEpochs(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500 disabled:opacity-60"
            />
          </div>

          <div>
            <label className="text-[11px] text-gray-400 block mb-1 font-medium">
              Batch Size (Tamaño de Lote)
            </label>
            <input
              type="number"
              value={batchSize}
              disabled={isTraining || trainingMode === "triad"}
              min="4"
              max="128"
              onChange={(e) => setBatchSize(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500 disabled:opacity-60"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="text-[11px] text-gray-400 block mb-1 font-medium">Framework</label>
            <select
              value={framework}
              disabled={isTraining}
              onChange={(e) => setFramework(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-blue-500 font-mono disabled:opacity-60"
            >
              <option value="pytorch">PyTorch 2.5 (Nativo C++/CUDA)</option>
              <option value="tensorflow" disabled>TensorFlow 2.16 (Deshabilitado)</option>
            </select>
          </div>

          <div>
            <label className="text-[11px] text-gray-400 block mb-1 font-medium flex items-center justify-between">
              <span>Arquitectura de Red Neuronal</span>
              <span className="text-[10px] text-emerald-400 font-normal">
                {ARCHITECTURE_PRESETS[architecture]?.desc || "Calibrado"}
              </span>
            </label>
            <select
              value={architecture}
              disabled={isTraining || trainingMode === "triad"}
              onChange={(e) => handleArchitectureChange(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-blue-500 font-mono disabled:opacity-60"
            >
              <option value="EfficientNet-B0">EfficientNet-B0 (Transfer Learning · Pitch Shift)</option>
              <option value="ConvNeXt-Nano">ConvNeXt-Nano (Arquitectura Moderna)</option>
              <option value="ResNet-34d">ResNet-34d (ResNet Profunda)</option>
              <option value="PANNs-CNN14">PANNs-CNN14 (Audio Industrial & Pre-trained CNN)</option>
              <option value="AudioCNN">AudioCNN (Baseline Convolucional FAMA)</option>
            </select>
          </div>
        </div>

        {/* Estimación de Tiempo de Cómputo */}
        <div className="flex items-center justify-between pt-1 text-xs text-gray-400 border-t border-[#23252e]/60">
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span>
              Tiempo estimado ({hardware?.cuda_available ? "GPU CUDA" : "CPU"}):{" "}
              <strong className="text-emerald-300 font-mono">{estimatedDuration}</strong>
            </span>
          </div>

          <span className="text-[11px] text-gray-500 font-mono">
            {trainingMode === "triad" ? "3 modelos secuenciales (Pipeline MLOps)" : "1 modelo seleccionado"}
          </span>
        </div>

        {/* Botones de Acción (Entrenar / Detener) */}
        <div className="flex items-center gap-3 pt-1">
          <button
            type="button"
            onClick={handleStartTraining}
            disabled={isTraining}
            className={`flex-1 py-2.5 rounded-lg text-white font-bold text-xs transition-all flex items-center justify-center gap-2 shadow-lg disabled:opacity-40 disabled:cursor-not-allowed ${
              trainingMode === "triad"
                ? "bg-gradient-to-r from-emerald-600 via-teal-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 shadow-emerald-950/40"
                : "bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 shadow-blue-950/40"
            }`}
          >
            {isTraining ? (
              <>
                <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span>
                  {triadProgress.isTriad
                    ? `Tríada [${triadProgress.modelIdx}/3 ${triadProgress.currentArch}] · Época ${currentEpoch}/${totalEpochs}...`
                    : `Entrenando Época ${currentEpoch} / ${totalEpochs}...`}
                </span>
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clipRule="evenodd" />
                </svg>
                <span>
                  {trainingMode === "triad"
                    ? "Iniciar Pipeline de Tríada Completa (3 Modelos)"
                    : "Iniciar Entrenamiento Local"}
                </span>
              </>
            )}
          </button>

          {isTraining && (
            <button
              type="button"
              onClick={handleStopTraining}
              disabled={isStopping}
              className="py-2.5 px-4 rounded-lg bg-red-950/80 hover:bg-red-900 border border-red-800/80 text-red-300 font-bold text-xs transition-all flex items-center gap-1.5 shadow-sm disabled:opacity-50"
            >
              <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8 7a1 1 0 00-1 1v4a1 1 0 001 1h4a1 1 0 001-1V8a1 1 0 00-1-1H8z" clipRule="evenodd" />
              </svg>
              <span>{isStopping ? "Deteniendo..." : "Detener"}</span>
            </button>
          )}
        </div>
      </div>

      {/* ==================================================================== */}
      {/* 4. FILA 2: MÉTRICAS EN TIEMPO REAL + CONSOLA (Figura 6.8 / IS_02) */}
      {/* ==================================================================== */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Tarjeta: Curvas y Métricas en Tiempo Real (IS_02) */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-300 font-semibold flex items-center gap-1.5">
              <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
              </svg>
              Curvas de Precisión y Pérdida en Tiempo Real
          </span>
            <span className="text-[10px] text-gray-500 font-mono">
              Época {currentEpoch} de {totalEpochs}
            </span>
          </div>

          {/* Tarjetas de Métricas Actuales */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <div className="bg-[#111215] border border-[#23252e] rounded-lg p-2 text-center">
              <span className="text-[10px] text-gray-500 block">Train Loss</span>
              <span className="text-xs font-mono font-bold text-amber-400">
                {currentTrainLoss ? currentTrainLoss.toFixed(4) : "—"}
              </span>
            </div>
            <div className="bg-[#111215] border border-[#23252e] rounded-lg p-2 text-center">
              <span className="text-[10px] text-gray-500 block">Val Loss</span>
              <span className="text-xs font-mono font-bold text-rose-400">
                {currentValLoss ? currentValLoss.toFixed(4) : "—"}
              </span>
            </div>
            <div className="bg-[#111215] border border-[#23252e] rounded-lg p-2 text-center">
              <span className="text-[10px] text-gray-500 block">Train Acc</span>
              <span className="text-xs font-mono font-bold text-blue-400">
                {currentTrainAcc ? `${currentTrainAcc.toFixed(1)}%` : "—"}
              </span>
            </div>
            <div className="bg-[#111215] border border-[#23252e] rounded-lg p-2 text-center">
              <span className="text-[10px] text-gray-500 block">Val Acc</span>
              <span className="text-xs font-mono font-bold text-emerald-400">
                {currentValAcc ? `${currentValAcc.toFixed(1)}%` : "—"}
              </span>
            </div>
          </div>

          {/* Gráfico Visual Dinámico SVG */}
          <div className="bg-[#0f1013] border border-[#1f2128] rounded-lg h-44 p-3 flex flex-col justify-between relative overflow-hidden">
            {metricsHistory.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-gray-500 text-xs space-y-1">
                <svg className="w-6 h-6 text-gray-600 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                </svg>
                <span>Inicia un entrenamiento para observar las curvas en vivo</span>
              </div>
            ) : (
              <div className="h-full flex flex-col justify-between">
                <div className="flex justify-between items-center text-[10px] text-gray-500">
                  <div className="flex items-center gap-3">
                    <span className="flex items-center gap-1 text-emerald-400">
                      <span className="w-2 h-0.5 bg-emerald-400 inline-block" /> Val Acc (%)
                    </span>
                    <span className="flex items-center gap-1 text-rose-400">
                      <span className="w-2 h-0.5 bg-rose-400 inline-block" /> Val Loss
                    </span>
                  </div>
                  <span className="font-mono">Punto {metricsHistory.length}/{totalEpochs}</span>
                </div>

                {/* SVG Curves */}
                <div className="flex-1 w-full relative mt-2">
                  <svg className="w-full h-full overflow-visible" viewBox="0 0 300 100" preserveAspectRatio="none">
                    {/* Guías de cuadrícula */}
                    <line x1="0" y1="20" x2="300" y2="20" stroke="#1f2128" strokeDasharray="3 3" />
                    <line x1="0" y1="50" x2="300" y2="50" stroke="#1f2128" strokeDasharray="3 3" />
                    <line x1="0" y1="80" x2="300" y2="80" stroke="#1f2128" strokeDasharray="3 3" />

                    {/* Curva de Accuracy (Verde) */}
                    {metricsHistory.length > 1 && (
                      <polyline
                        fill="none"
                        stroke="#10b981"
                        strokeWidth="2.5"
                        points={metricsHistory
                          .map((m, idx) => {
                            const x = (idx / (totalEpochs - 1 || 1)) * 300;
                            // Normalizar acc de 0 a 100 en altura de 100px invertida
                            const y = 95 - (m.val_acc / 100) * 85;
                            return `${x},${y}`;
                          })
                          .join(" ")}
                      />
                    )}

                    {/* Curva de Loss (Rosa/Rojo) */}
                    {metricsHistory.length > 1 && (
                      <polyline
                        fill="none"
                        stroke="#f43f5e"
                        strokeWidth="2"
                        strokeDasharray="2 2"
                        points={metricsHistory
                          .map((m, idx) => {
                            const x = (idx / (totalEpochs - 1 || 1)) * 300;
                            // Normalizar loss de 0 a 2.0 en altura de 100px invertida
                            const y = Math.max(5, Math.min(95, (m.val_loss / 2.0) * 90));
                            return `${x},${y}`;
                          })
                          .join(" ")}
                      />
                    )}

                    {/* Puntos de Época */}
                    {metricsHistory.map((m, idx) => {
                      const x = (idx / (totalEpochs - 1 || 1)) * 300;
                      const y = 95 - (m.val_acc / 100) * 85;
                      return <circle key={idx} cx={x} cy={y} r="3" fill="#10b981" />;
                    })}
                  </svg>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Tarjeta: Consola de Telemetría (Figura 6.8) */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-300 font-semibold flex items-center gap-1.5">
              <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              Consola de Entrenamiento en Vivo
            </span>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${isTraining ? "bg-emerald-400 animate-pulse" : "bg-gray-500"}`} />
              <span className="text-[10px] text-gray-500 font-mono">
                {isTraining ? "Streaming Activo" : "En Espera"}
              </span>
            </div>
          </div>

          <div
            ref={logsContainerRef}
            className="bg-[#0f1013] border border-[#1f2128] rounded-lg p-3 font-mono text-[11px] text-gray-300 h-64 overflow-y-auto space-y-1"
          >
            {logs.length === 0 ? (
              <div className="text-gray-600 italic space-y-1">
                <p>[INFO] Sistema inicializado. Motor PyTorch listo.</p>
                <p>[INFO] Configure los hiperparámetros y presione Iniciar Entrenamiento.</p>
              </div>
            ) : (
              logs.map((log, idx) => {
                let badgeClass = "text-blue-400 bg-blue-950/70";
                if (log.level === "SUCCESS") badgeClass = "text-emerald-400 bg-emerald-950/70";
                if (log.level === "WARN") badgeClass = "text-amber-400 bg-amber-950/70";
                if (log.level === "ERROR") badgeClass = "text-rose-400 bg-rose-950/70";

                return (
                  <p key={log.id || idx} className="leading-relaxed flex items-start gap-2">
                    <span className="text-gray-500 flex-shrink-0 text-[10px]">{log.timestamp}</span>
                    <span className={`px-1 rounded text-[10px] font-semibold flex-shrink-0 ${badgeClass}`}>
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

      {/* ==================================================================== */}
      {/* 5. HISTORIAL DE ENTRENAMIENTOS (CU_INV_04 / CU_INV_05 / Tabla 6.6) */}
      {/* ==================================================================== */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-xs text-gray-200 font-semibold block">
              Historial de Modelos Guardados
            </span>
            <p className="text-[11px] text-gray-500">
              Modelos acústicos indexados y respaldados en disco / Cloud Storage
            </p>
          </div>

          <button
            type="button"
            onClick={fetchHistory}
            className="text-[11px] text-gray-400 hover:text-gray-200 transition-colors flex items-center gap-1"
          >
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            <span>Actualizar</span>
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-[#23252e] text-gray-400">
                <th className="pb-3 font-medium">Arquitectura</th>
                <th className="pb-3 font-medium">Épocas</th>
                <th className="pb-3 font-medium">Precisión (Acc)</th>
                <th className="pb-3 font-medium">Pérdida (Loss)</th>
                <th className="pb-3 font-medium">Archivo Checkpoint</th>
                <th className="pb-3 font-medium">Fecha</th>
                <th className="pb-3 font-medium text-center">Estado</th>
                <th className="pb-3 font-medium text-right pr-2">Acción</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#23252e]/60">
              {history.map((item) => (
                <tr key={item.id} className="hover:bg-[#1c1e24]/40 transition-colors">
                  <td className="py-3 font-medium text-gray-200 flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    {item.architecture}
                  </td>
                  <td className="py-3 text-gray-400 font-mono">{item.epochs}</td>
                  <td className="py-3 text-emerald-400 font-mono font-semibold">
                    {item.accuracy ? `${item.accuracy.toFixed(2)}%` : "—"}
                  </td>
                  <td className="py-3 text-gray-400 font-mono">
                    {item.loss ? item.loss.toFixed(4) : "—"}
                  </td>
                  <td className="py-3 text-gray-400 font-mono text-[11px]">
                    {item.filename}
                  </td>
                  <td className="py-3 text-gray-500 font-mono text-[11px]">
                    {item.created_at
                      ? new Date(item.created_at).toLocaleDateString("es-CL", {
                          day: "numeric",
                          month: "short",
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "—"}
                  </td>
                  <td className="py-3 text-center">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-medium inline-block ${
                        item.active
                          ? "bg-emerald-950/70 text-emerald-400 border border-emerald-800/60"
                          : "bg-[#1c1e24] text-gray-400 border border-[#2b2e38]"
                      }`}
                    >
                      {item.active ? "Activo (Inferencia)" : "Guardado"}
                    </span>
                  </td>
                  <td className="py-3 text-right pr-2">
                    {item.active ? (
                      <span className="text-[11px] text-emerald-400 font-mono font-medium">
                        ✓ En uso
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleActivateModel(item.id)}
                        disabled={activatingId === item.id}
                        className="text-[11px] text-gray-300 hover:text-white px-2.5 py-1 rounded bg-[#1c1e24] hover:bg-emerald-950/60 border border-[#2d303b] hover:border-emerald-700/60 transition-colors"
                      >
                        {activatingId === item.id ? "Activando..." : "Activar"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
