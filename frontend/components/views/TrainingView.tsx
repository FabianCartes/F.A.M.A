"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { API_BASE_URL } from "@/lib/api";
import { rebalanceWeights } from "@/lib/utils/ensembleWeights";
import {
  AUDIO_DOMAIN_PRESETS,
  AudioDomainPresetKey,
  validateAudioPhysics,
} from "@/lib/utils/audioDomainPresets";
import { getChartPaths, ChartOptions } from "@/lib/utils/trainingChart";

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
  architecture?: string;
  model_index?: number;
}

interface LogEntry {
  id: string;
  timestamp: string;
  level: string;
  message: string;
}

interface ModelHistoryItem {
  id: number;
  name?: string;
  version?: number;
  dataset?: string;
  architecture: string;
  epochs: number;
  accuracy: number;
  loss: number;
  active: boolean;
  status: string;
  filename: string;
  hyperparameters?: {
    learning_rate: number;
    batch_size: number;
    optimizer: string;
    loss_type: string;
  };
  audio_specs?: {
    target_sr: number;
    duration_seconds: number;
    n_mels: number;
    n_fft: number;
    hop_length: number;
    fmin: number;
    fmax: number;
  };
  classes?: string[];
  classes_count?: number;
  file_size_bytes?: number;
  created_at: string | null;
}

const ARCHITECTURE_PRESETS: Record<
  string,
  { lr: string; weightDecay: string; epochs: string; batch: string; desc: string }
> = {
  "EfficientNet-B0": {
    lr: "0.001",
    weightDecay: "0.01",
    epochs: "10",
    batch: "16",
    desc: "Transfer Learning & Pitch Shift (Recomendada)",
  },
  "ConvNeXt-Nano": {
    lr: "0.0005",
    weightDecay: "0.05",
    epochs: "12",
    batch: "16",
    desc: "Gradiente fino y regularización moderna",
  },
  "ResNet-34d": {
    lr: "0.0003",
    weightDecay: "0.01",
    epochs: "15",
    batch: "8",
    desc: "Batches moderados para estabilidad profunda",
  },
  "PANNs-CNN14": {
    lr: "0.0005",
    weightDecay: "0.01",
    epochs: "15",
    batch: "16",
    desc: "Red pre-entrenada para acústica industrial y patrones armónicos",
  },
  "AudioCNN": {
    lr: "0.001",
    weightDecay: "0.001",
    epochs: "20",
    batch: "32",
    desc: "Baseline convolucional clásico F.A.M.A.",
  },
};

export default function TrainingView() {
  // 1. Estado de Configuración (IE_03)
  const [selectedDataset, setSelectedDataset] = useState<string>("AvesChilenas");
  const [learningRate, setLearningRate] = useState<string>("0.001");
  const [weightDecay, setWeightDecay] = useState<string>("0.01");
  const [epochs, setEpochs] = useState<string>("10");
  const [batchSize, setBatchSize] = useState<string>("16");
  const [framework, setFramework] = useState<string>("pytorch");
  const [architecture, setArchitecture] = useState<string>("EfficientNet-B0");
  const [ensembleSize, setEnsembleSize] = useState<1 | 2 | 3>(1);
  const [ensembleModels, setEnsembleModels] = useState<
    Array<{ architecture: string; weight: number }>
  >([
    { architecture: "EfficientNet-B0", weight: 1.0 },
    { architecture: "ConvNeXt-Nano", weight: 0.5 },
    { architecture: "ResNet-34d", weight: 0.33 },
  ]);
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

  // Estado de Física Acústica Multi-Dominio, Ventaneo Denso y Regularización
  const [isPhysicsExpanded, setIsPhysicsExpanded] = useState<boolean>(true);
  const [domainPreset, setDomainPreset] = useState<AudioDomainPresetKey>("bioacoustics");
  const [targetSr, setTargetSr] = useState<number>(22050);
  const [durationSeconds, setDurationSeconds] = useState<number>(5.0);
  const [fMin, setFMin] = useState<number>(800);
  const [fMax, setFMax] = useState<number>(10000);
  const [nMels, setNMels] = useState<number>(128);
  const [nFft, setNFft] = useState<number>(2048);
  const [hopLength, setHopLength] = useState<number>(512);

  // Ventaneo Denso y Captura de Eventos Breves
  const [hopSeconds, setHopSeconds] = useState<number>(1.0);
  const [aggregationMode, setAggregationMode] = useState<"max" | "mean">("max");
  const [gemP, setGemP] = useState<number>(3.0);
  const [vadThreshold, setVadThreshold] = useState<number>(0.0);

  // Regularización y Función de Pérdida
  const [lossType, setLossType] = useState<"focal" | "cross_entropy">("focal");
  const [focalGamma, setFocalGamma] = useState<number>(2.0);
  const [mixupEnabled, setMixupEnabled] = useState<boolean>(true);
  const [mixupAlpha, setMixupAlpha] = useState<number>(0.2);
  const [pitchShiftEnabled, setPitchShiftEnabled] = useState<boolean>(false);

  const handleApplyPreset = (key: AudioDomainPresetKey) => {
    setDomainPreset(key);
    const cfg = AUDIO_DOMAIN_PRESETS[key];
    if (key !== "custom") {
      setTargetSr(cfg.target_sr);
      setDurationSeconds(cfg.duration_seconds);
      setFMin(cfg.f_min);
      setFMax(cfg.f_max);
      setNMels(cfg.n_mels);
      setNFft(cfg.n_fft);
      setHopLength(cfg.hop_length);
      setHopSeconds(cfg.hop_seconds);
      setAggregationMode(cfg.aggregation_mode);
      setGemP(cfg.gem_p);
      setVadThreshold(cfg.vad_threshold);
      setLossType(cfg.loss_type);
      setFocalGamma(cfg.focal_gamma);
      setMixupEnabled(cfg.mixup);
      setMixupAlpha(cfg.mixup_alpha);
      setPitchShiftEnabled(cfg.pitch_shift);
    }
  };

  const physicsValidation = useMemo(() => {
    return validateAudioPhysics({
      target_sr: targetSr,
      f_min: fMin,
      f_max: fMax,
    });
  }, [targetSr, fMin, fMax]);

  const handleEnsembleSizeChange = (newSize: 1 | 2 | 3) => {
    setEnsembleSize(newSize);
    if (newSize === 1) {
      setEnsembleModels((prev) => [
        { architecture: prev[0]?.architecture || architecture, weight: 1.0 },
        { architecture: prev[1]?.architecture || "ConvNeXt-Nano", weight: 0.5 },
        { architecture: prev[2]?.architecture || "ResNet-34d", weight: 0.33 },
      ]);
    } else if (newSize === 2) {
      setEnsembleModels((prev) => [
        { architecture: prev[0]?.architecture || "EfficientNet-B0", weight: 0.5 },
        { architecture: prev[1]?.architecture || "ConvNeXt-Nano", weight: 0.5 },
        { architecture: prev[2]?.architecture || "ResNet-34d", weight: 0.33 },
      ]);
    } else {
      setEnsembleModels((prev) => [
        { architecture: prev[0]?.architecture || "EfficientNet-B0", weight: 0.34 },
        { architecture: prev[1]?.architecture || "ConvNeXt-Nano", weight: 0.33 },
        { architecture: prev[2]?.architecture || "ResNet-34d", weight: 0.33 },
      ]);
    }
  };

  const handleWeightChange = (index: number, newWeight: number) => {
    const currentWeights = ensembleModels.slice(0, ensembleSize).map((m) => m.weight);
    const updatedWeights = rebalanceWeights(currentWeights, index, newWeight);
    setEnsembleModels((prev) =>
      prev.map((m, idx) =>
        idx < ensembleSize ? { ...m, weight: updatedWeights[idx] } : m
      )
    );
  };

  const handleModelArchChange = (index: number, newArch: string) => {
    setEnsembleModels((prev) =>
      prev.map((m, idx) => (idx === index ? { ...m, architecture: newArch } : m))
    );
    if (index === 0) {
      handleArchitectureChange(newArch);
    }
  };

  // 2. Telemetría de Hardware y Datasets
  const [hardware, setHardware] = useState<HardwareStatus | null>(null);
  const [datasets, setDatasets] = useState<TrainingDataset[]>([]);
  const currentDataset = useMemo(() => {
    return (
      datasets.find((d) => d.id === selectedDataset) ||
      datasets[0] || {
        id: "AvesChilenas",
        name: "AvesChilenas (1211 audios)",
        audio_count: 1211,
        class_count: 15,
        size_mb: 340.5,
      }
    );
  }, [datasets, selectedDataset]);

  // 3. Ciclo de Vida del Entrenamiento (RF_04 / CU_INV_03)
  const [isTraining, setIsTraining] = useState<boolean>(false);
  const [isStopping, setIsStopping] = useState<boolean>(false);
  const [currentEpoch, setCurrentEpoch] = useState<number>(0);
  const [totalEpochs, setTotalEpochs] = useState<number>(10);
  const [currentTrainLoss, setCurrentTrainLoss] = useState<number>(0.0);
  const [currentValLoss, setCurrentValLoss] = useState<number>(0.0);
  const [currentTrainAcc, setCurrentTrainAcc] = useState<number>(0.0);
  const [currentValAcc, setCurrentValAcc] = useState<number>(0.0);
  const [metricsHistory, setMetricsHistory] = useState<MetricPoint[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [chartModelFilter, setChartModelFilter] = useState<"current" | "all" | number>("current");

  // Modelos disponibles para el filtro del gráfico en ensambles
  const availableChartModels = useMemo(() => {
    const modelsInHistory = Array.from(
      new Set(metricsHistory.map((m) => m.model_index ?? 1))
    ).sort((a, b) => a - b);

    if (modelsInHistory.length > 1) {
      return modelsInHistory.map((idx) => {
        const point = metricsHistory.find((m) => (m.model_index ?? 1) === idx);
        const arch =
          point?.architecture ||
          ensembleModels[idx - 1]?.architecture ||
          `Modelo ${idx}`;
        return { index: idx, architecture: arch };
      });
    }

    if (ensembleSize > 1 || triadProgress.totalModels > 1) {
      const total = Math.max(ensembleSize, triadProgress.totalModels);
      return Array.from({ length: total }, (_, i) => ({
        index: i + 1,
        architecture: ensembleModels[i]?.architecture || `Modelo ${i + 1}`,
      }));
    }

    return [];
  }, [metricsHistory, ensembleSize, triadProgress.totalModels, ensembleModels]);

  // Cálculo desacoplado y reactivo de curvas y coordenadas SVG
  const chartOptions: ChartOptions = useMemo(() => {
    return {
      width: 300,
      height: 100,
      paddingTop: 14,
      paddingBottom: 14,
      totalEpochs: totalEpochs,
      activeModelFilter: chartModelFilter,
      currentModelIndex: triadProgress.modelIdx,
      modelsConfig: ensembleModels
        .slice(0, Math.max(ensembleSize, triadProgress.totalModels))
        .map((m) => ({
          architecture: m.architecture,
          epochs: parseInt(
            ARCHITECTURE_PRESETS[m.architecture]?.epochs || epochs,
            10
          ),
        })),
    };
  }, [
    totalEpochs,
    chartModelFilter,
    triadProgress.modelIdx,
    ensembleModels,
    ensembleSize,
    triadProgress.totalModels,
    epochs,
  ]);

  const chartData = useMemo(() => {
    return getChartPaths(metricsHistory, chartOptions);
  }, [metricsHistory, chartOptions]);

  const displayMetrics = useMemo(() => {
    if (
      typeof chartModelFilter === "number" &&
      chartData.filteredMetrics.length > 0
    ) {
      const last =
        chartData.filteredMetrics[chartData.filteredMetrics.length - 1];
      return {
        trainLoss: last.train_loss,
        valLoss: last.val_loss,
        trainAcc: last.train_acc,
        valAcc: last.val_acc,
      };
    }
    return {
      trainLoss: currentTrainLoss,
      valLoss: currentValLoss,
      trainAcc: currentTrainAcc,
      valAcc: currentValAcc,
    };
  }, [
    chartModelFilter,
    chartData.filteredMetrics,
    currentTrainLoss,
    currentValLoss,
    currentTrainAcc,
    currentValAcc,
  ]);

  // 4. Historial de Modelos (CU_INV_04 / CU_INV_05)
  const [history, setHistory] = useState<ModelHistoryItem[]>([]);
  const [selectedModelModal, setSelectedModelModal] = useState<ModelHistoryItem | null>(null);

  const logsContainerRef = useRef<HTMLDivElement | null>(null);

  // Cambio dinámico de arquitectura con auto-rellenado de hiperparámetros recomendados
  const handleArchitectureChange = (newArch: string) => {
    setArchitecture(newArch);
    const preset = ARCHITECTURE_PRESETS[newArch];
    if (preset) {
      setLearningRate(preset.lr);
      if (preset.weightDecay) {
        setWeightDecay(preset.weightDecay);
      }
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
    const totalSec = singleSec * ensembleSize;

    if (totalSec < 60) return `~${Math.ceil(totalSec)} seg`;
    const minutes = Math.round(totalSec / 60);
    if (minutes < 60) return `~${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const remMin = minutes % 60;
    return `~${hours}h ${remMin}m`;
  }, [currentDataset, batchSize, epochs, hardware, ensembleSize]);


  // Cargar telemetría de hardware
  const fetchHardware = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/training/hardware`);
      if (res.ok) {
        const data = await res.json();
        setHardware(data);
      }
    } catch {
      // Si el backend no está disponible temporalmente
    }
  }, []);


  // Cargar historial de modelos desde PostgreSQL
  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/training/history`);
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
    let isCancelled = false;

    async function initTrainingData() {
      try {
        const [resHw, resDs, resHist] = await Promise.all([
          fetch(`${API_BASE_URL}/api/training/hardware`).catch(() => null),
          fetch(`${API_BASE_URL}/api/training/datasets`).catch(() => null),
          fetch(`${API_BASE_URL}/api/training/history`).catch(() => null),
        ]);

        if (isCancelled) return;

        if (resHw && resHw.ok) {
          const hwData = await resHw.json();
          setHardware(hwData);
        }
        if (resDs && resDs.ok) {
          const dsData = await resDs.json();
          setDatasets(dsData.datasets || []);
        }
        if (resHist && resHist.ok) {
          const histData = await resHist.json();
          setHistory(histData.history || []);
        }
      } catch {
        // Silenciar error transitorio
      }
    }

    initTrainingData();

    return () => {
      isCancelled = true;
    };
  }, []);

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
          const res = await fetch(`${API_BASE_URL}/api/training/progress`);
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

            const total = data.total_models || (data.is_tri_model ? 3 : 1);
            if (total > 1 || data.is_tri_model) {
              setTriadProgress({
                isTriad: true,
                modelIdx: data.current_model_index || 1,
                totalModels: total,
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
    if (!physicsValidation.valid) {
      alert(`Parámetros acústicos inválidos: ${physicsValidation.error}`);
      return;
    }

    if (isTraining) return;
    setIsTraining(true);
    setIsStopping(false);
    setMetricsHistory([]);
    setCurrentEpoch(0);

    const currentEnsemble = ensembleModels.slice(0, ensembleSize);
    const sumW = currentEnsemble.reduce((acc, m) => acc + m.weight, 0) || 1.0;
    const normalizedEnsemble = currentEnsemble.map((m) => ({
      architecture: m.architecture,
      weight: Math.round((m.weight / sumW) * 1000) / 1000,
    }));
    const normSum = normalizedEnsemble.reduce((acc, m) => acc + m.weight, 0);
    if (normalizedEnsemble.length > 0 && Math.abs(normSum - 1.0) > 1e-4) {
      normalizedEnsemble[0].weight =
        Math.round((normalizedEnsemble[0].weight + (1.0 - normSum)) * 1000) / 1000;
    }

    if (ensembleSize > 1) {
      setTriadProgress({
        isTriad: true,
        modelIdx: 1,
        totalModels: ensembleSize,
        currentArch: normalizedEnsemble[0]?.architecture || architecture,
      });
    } else {
      setTriadProgress({
        isTriad: false,
        modelIdx: 1,
        totalModels: 1,
        currentArch: normalizedEnsemble[0]?.architecture || architecture,
      });
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/training/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dataset_name: selectedDataset,
          architecture: normalizedEnsemble[0]?.architecture || architecture,
          epochs: parseInt(epochs) || 10,
          learning_rate: parseFloat(learningRate) || 0.001,
          weight_decay: parseFloat(weightDecay) || 0.01,
          batch_size: parseInt(batchSize) || 16,
          framework,
          is_tri_model: ensembleSize === 3,
          models: normalizedEnsemble,
          audio_config: {
            target_sr: targetSr,
            duration_seconds: durationSeconds,
            f_min: fMin,
            f_max: fMax,
            n_mels: nMels,
            n_fft: nFft,
            hop_length: hopLength,
          },
          windowing_config: {
            hop_seconds: hopSeconds,
            aggregation_mode: aggregationMode,
            gem_p: gemP,
            vad_threshold: vadThreshold,
          },
          regularization_config: {
            loss_type: lossType,
            focal_gamma: focalGamma,
            mixup_enabled: mixupEnabled,
            mixup_alpha: mixupAlpha,
            pitch_shift_enabled: pitchShiftEnabled,
          },
        }),
      });


      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || `Error HTTP ${res.status}`);
      }

      await res.json();
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
      await fetch(`${API_BASE_URL}/api/training/stop`, { method: "POST" });
    } catch {
      setIsStopping(false);
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
      {/* 2.5. PANEL DE FÍSICA DE AUDIO Y ADAPTACIÓN AL DOMINIO */}
      {/* ==================================================================== */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl overflow-hidden shadow-sm transition-all">
        {/* Encabezado colapsable */}
        <button
          type="button"
          onClick={() => setIsPhysicsExpanded(!isPhysicsExpanded)}
          className="w-full p-4 px-5 flex items-center justify-between text-left hover:bg-[#1a1b20] transition-colors"
        >
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-teal-500/10 border border-teal-500/30 flex items-center justify-center text-teal-400">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
              </svg>
            </div>
            <div>
              <span className="text-xs font-semibold text-gray-200 block">
                Física de Audio y Adaptación al Dominio
              </span>
              <span className="text-[11px] text-gray-400">
                Espectrograma Mel ({targetSr} Hz, {durationSeconds}s, {fMin}-{fMax} Hz) · Ventaneo denso · Regularización
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {!physicsValidation.valid && (
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-rose-950/70 border border-rose-800 text-rose-300">
                Física Inválida
              </span>
            )}
            <svg
              className={`w-4 h-4 text-gray-400 transition-transform duration-200 ${
                isPhysicsExpanded ? "rotate-180" : ""
              }`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </button>

        {isPhysicsExpanded && (
          <div className="p-5 pt-1 space-y-4 border-t border-[#23252e]">
            {/* Presets Rápidos de 1-Clic */}
            <div className="space-y-1.5">
              <span className="text-[11px] text-gray-400 font-medium block">
                Presets de Dominio Acústico (1-Clic)
              </span>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {(
                  [
                    { key: "bioacoustics", label: "Bioacústica (Aves)", badge: "22.05 kHz · 5.0s" },
                    { key: "industrial", label: "Diagnóstico Industrial", badge: "32 kHz · 1.5s" },
                    { key: "medical_cough", label: "Tos Médica", badge: "16 kHz · 2.0s" },
                    { key: "custom", label: "Personalizado", badge: "Manual" },
                  ] as const
                ).map((p) => {
                  const isActive = domainPreset === p.key;
                  return (
                    <button
                      key={p.key}
                      type="button"
                      disabled={isTraining}
                      onClick={() => handleApplyPreset(p.key)}
                      className={`p-2.5 rounded-lg border text-left transition-all flex flex-col justify-between ${
                        isActive
                          ? "bg-teal-950/40 border-teal-500/70 text-teal-200 shadow-sm"
                          : "bg-[#111215] border-[#23252e] text-gray-400 hover:text-gray-200 hover:border-gray-700"
                      }`}
                    >
                      <span className="text-xs font-semibold block">{p.label}</span>
                      <span className="text-[10px] font-mono text-gray-400 block mt-1">{p.badge}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Alerta de Validación Acústica Reactiva */}
            {!physicsValidation.valid && (
              <div className="p-3 rounded-lg bg-rose-950/80 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
                <svg className="w-4 h-4 flex-shrink-0 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                <span>{physicsValidation.error}</span>
              </div>
            )}

            {/* Grid 1: Física Espectral */}
            <div>
              <span className="text-[11px] text-gray-400 font-semibold block mb-2">
                1. Física del Audio y Espectrograma
              </span>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div>
                  <label htmlFor="target_sr" className="text-[11px] text-gray-400 block mb-1 font-medium">
                    Tasa de Muestreo (Hz)
                  </label>
                  <input
                    id="target_sr"
                    type="number"
                    value={targetSr}
                    disabled={isTraining}
                    min={8000}
                    max={48000}
                    step={100}
                    onChange={(e) => {
                      setDomainPreset("custom");
                      setTargetSr(parseInt(e.target.value, 10) || 8000);
                    }}
                    className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-teal-500"
                  />
                </div>

                <div>
                  <label htmlFor="duration_seconds" className="text-[11px] text-gray-400 block mb-1 font-medium">
                    Duración de Ventana (s)
                  </label>
                  <input
                    id="duration_seconds"
                    type="number"
                    value={durationSeconds}
                    disabled={isTraining}
                    min={0.5}
                    max={30.0}
                    step={0.5}
                    onChange={(e) => {
                      setDomainPreset("custom");
                      setDurationSeconds(parseFloat(e.target.value) || 0.5);
                    }}
                    className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-teal-500"
                  />
                </div>

                <div>
                  <label htmlFor="f_min" className="text-[11px] text-gray-400 block mb-1 font-medium">
                    Frecuencia Mínima (Hz)
                  </label>
                  <input
                    id="f_min"
                    type="number"
                    value={fMin}
                    disabled={isTraining}
                    min={0}
                    step={10}
                    onChange={(e) => {
                      setDomainPreset("custom");
                      setFMin(parseFloat(e.target.value) || 0);
                    }}
                    className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-teal-500"
                  />
                </div>

                <div>
                  <label htmlFor="f_max" className="text-[11px] text-gray-400 block mb-1 font-medium">
                    Frecuencia Máxima (Hz)
                  </label>
                  <input
                    id="f_max"
                    type="number"
                    value={fMax}
                    disabled={isTraining}
                    min={100}
                    step={100}
                    onChange={(e) => {
                      setDomainPreset("custom");
                      setFMax(parseFloat(e.target.value) || 100);
                    }}
                    className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-teal-500"
                  />
                </div>
              </div>
            </div>

            {/* Grid 2: Ventaneo Denso y Captura de Eventos Breves */}
            <div>
              <span className="text-[11px] text-gray-400 font-semibold block mb-2">
                2. Ventaneo Denso y Agregación Temporal
              </span>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div>
                  <label htmlFor="hop_seconds" className="text-[11px] text-gray-400 block mb-1 font-medium">
                    Salto Temporal (s)
                  </label>
                  <input
                    id="hop_seconds"
                    type="number"
                    value={hopSeconds}
                    disabled={isTraining}
                    min={0.1}
                    max={10.0}
                    step={0.1}
                    onChange={(e) => {
                      setDomainPreset("custom");
                      setHopSeconds(parseFloat(e.target.value) || 0.1);
                    }}
                    className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-teal-500"
                  />
                </div>

                <div>
                  <label htmlFor="aggregation_mode" className="text-[11px] text-gray-400 block mb-1 font-medium">
                    Agregación Temporal
                  </label>
                  <select
                    id="aggregation_mode"
                    value={aggregationMode}
                    disabled={isTraining}
                    onChange={(e) => {
                      setDomainPreset("custom");
                      setAggregationMode(e.target.value as "max" | "mean");
                    }}
                    className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-teal-500"
                  >
                    <option value="max">Max-Pooling (Eventos Breves)</option>
                    <option value="mean">Mean-Pooling (Fondo Continuo)</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="gem_p" className="text-[11px] text-gray-400 block mb-1 font-medium">
                    Exponente GeM (p)
                  </label>
                  <input
                    id="gem_p"
                    type="number"
                    value={gemP}
                    disabled={isTraining}
                    min={1.0}
                    max={10.0}
                    step={0.5}
                    onChange={(e) => {
                      setDomainPreset("custom");
                      setGemP(parseFloat(e.target.value) || 1.0);
                    }}
                    className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-teal-500"
                  />
                </div>

                <div>
                  <label htmlFor="vad_threshold" className="text-[11px] text-gray-400 block mb-1 font-medium">
                    Umbral VAD Energético
                  </label>
                  <input
                    id="vad_threshold"
                    type="number"
                    value={vadThreshold}
                    disabled={isTraining}
                    min={0.0}
                    max={1.0}
                    step={0.01}
                    onChange={(e) => {
                      setDomainPreset("custom");
                      setVadThreshold(parseFloat(e.target.value) || 0.0);
                    }}
                    className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-teal-500"
                  />
                </div>
              </div>
            </div>

            {/* Grid 3: Regularización y Pérdida */}
            <div>
              <span className="text-[11px] text-gray-400 font-semibold block mb-2">
                3. Regularización y Función de Pérdida
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label htmlFor="loss_type" className="text-[11px] text-gray-400 block mb-1 font-medium">
                    Función de Pérdida
                  </label>
                  <select
                    id="loss_type"
                    value={lossType}
                    disabled={isTraining}
                    onChange={(e) => {
                      setDomainPreset("custom");
                      setLossType(e.target.value as "focal" | "cross_entropy");
                    }}
                    className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-teal-500"
                  >
                    <option value="focal">Focal Loss (Desbalance de Clases)</option>
                    <option value="cross_entropy">Cross Entropy (Estándar)</option>
                  </select>
                </div>

                {lossType === "focal" && (
                  <div>
                    <label htmlFor="focal_gamma" className="text-[11px] text-gray-400 block mb-1 font-medium">
                      Parámetro Gamma (Focal)
                    </label>
                    <input
                      id="focal_gamma"
                      type="number"
                      value={focalGamma}
                      disabled={isTraining}
                      min={0.0}
                      max={10.0}
                      step={0.5}
                      onChange={(e) => {
                        setDomainPreset("custom");
                        setFocalGamma(parseFloat(e.target.value) || 0.0);
                      }}
                      className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-teal-500"
                    />
                  </div>
                )}

                <div className="flex items-center gap-4 pt-4 sm:pt-6">
                  <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={mixupEnabled}
                      disabled={isTraining}
                      onChange={(e) => {
                        setDomainPreset("custom");
                        setMixupEnabled(e.target.checked);
                      }}
                      className="rounded bg-[#111215] border-[#23252e] text-teal-500 focus:ring-0"
                    />
                    <span>Mixup</span>
                  </label>

                  <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                    <input
                      type="checkbox"
                      checked={pitchShiftEnabled}
                      disabled={isTraining}
                      onChange={(e) => {
                        setDomainPreset("custom");
                        setPitchShiftEnabled(e.target.checked);
                      }}
                      className="rounded bg-[#111215] border-[#23252e] text-teal-500 focus:ring-0"
                    />
                    <span>Pitch Shift</span>
                  </label>
                </div>
              </div>
            </div>
          </div>
        )}
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

        {/* Selector Dinámico de Ensamble (1 a 3 Modelos) */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-lg bg-[#111215] border border-[#23252e]">
          <div>
            <span className="text-xs font-semibold text-gray-200 block">Topología del Modelo / Ensamble</span>
            <span className="text-[11px] text-gray-500">
              {ensembleSize === 1
                ? "Entrena únicamente 1 arquitectura con hiperparámetros personalizados."
                : ensembleSize === 2
                ? "Dúo Ensamble: Entrena secuencialmente 2 redes seleccionadas con ponderaciones calibradas (menor costo de cómputo y VRAM)."
                : "Tri Ensamble: Entrena la tríada completa de 3 modelos con ponderaciones calibradas para máxima capacidad generalizadora."}
            </span>
          </div>

          <div className="flex items-center gap-1.5 p-1 bg-[#16171b] border border-[#23252e] rounded-lg flex-shrink-0">
            <button
              type="button"
              disabled={isTraining}
              onClick={() => handleEnsembleSizeChange(1)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                ensembleSize === 1
                  ? "bg-blue-600 text-white shadow-sm font-semibold"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              1 Modelo (Individual)
            </button>
            <button
              type="button"
              disabled={isTraining}
              onClick={() => handleEnsembleSizeChange(2)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                ensembleSize === 2
                  ? "bg-cyan-600 text-white shadow-sm font-semibold"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              2 Modelos (Dúo)
            </button>
            <button
              type="button"
              disabled={isTraining}
              onClick={() => handleEnsembleSizeChange(3)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                ensembleSize === 3
                  ? "bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-sm font-semibold"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              <svg className="w-3.5 h-3.5 text-amber-300" fill="currentColor" viewBox="0 0 20 20">
                <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
              </svg>
              <span>3 Modelos (Tríada)</span>
            </button>
          </div>
        </div>

        {/* Inputs de Hiperparámetros en Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div>
            <label htmlFor="learning-rate-input" className="text-[11px] text-gray-400 block mb-1 font-medium">
              Learning Rate (Tasa de Aprendizaje)
            </label>
            <input
              id="learning-rate-input"
              type="text"
              value={learningRate}
              disabled={isTraining || ensembleSize > 1}
              onChange={(e) => setLearningRate(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500 disabled:opacity-60"
            />
          </div>

          <div>
            <label htmlFor="weight-decay-input" className="text-[11px] text-gray-400 block mb-1 font-medium">
              Weight Decay (AdamW L2)
            </label>
            <input
              id="weight-decay-input"
              type="text"
              value={weightDecay}
              disabled={isTraining}
              onChange={(e) => setWeightDecay(e.target.value)}
              placeholder="0.01"
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500 disabled:opacity-60"
            />
          </div>

          <div>
            <label htmlFor="epochs-input" className="text-[11px] text-gray-400 block mb-1 font-medium">
              Épocas de Entrenamiento
            </label>
            <input
              id="epochs-input"
              type="number"
              value={epochs}
              disabled={isTraining || ensembleSize > 1}
              min="1"
              max="100"
              onChange={(e) => setEpochs(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500 disabled:opacity-60"
            />
          </div>

          <div>
            <label htmlFor="batch-size-input" className="text-[11px] text-gray-400 block mb-1 font-medium">
              Batch Size (Tamaño de Lote)
            </label>
            <input
              id="batch-size-input"
              type="number"
              value={batchSize}
              disabled={isTraining || ensembleSize > 1}
              min="4"
              max="128"
              onChange={(e) => setBatchSize(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500 disabled:opacity-60"
            />
          </div>
        </div>

        {/* Selección de Framework */}
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

          {ensembleSize === 1 && (
            <div>
              <label className="text-[11px] text-gray-400 block mb-1 font-medium flex items-center justify-between">
                <span>Arquitectura de Red Neuronal</span>
                <span className="text-[10px] text-emerald-400 font-normal">
                  {ARCHITECTURE_PRESETS[architecture]?.desc || "Calibrado"}
                </span>
              </label>
              <select
                value={architecture}
                disabled={isTraining}
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
          )}
        </div>

        {/* Configuración Detallada de Miembros del Ensamble con Sliders Auto-Rebalanceados */}
        {ensembleSize > 1 && (
          <div className="space-y-3 pt-2 border-t border-[#23252e]/60">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-300 flex items-center gap-1.5">
                <svg className="w-4 h-4 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
                Composición y Ponderación del Ensamble ({ensembleSize} Modelos)
              </span>
              <span className="text-[10px] text-emerald-400 font-mono bg-emerald-950/60 border border-emerald-800/50 px-2 py-0.5 rounded flex items-center gap-1">
                <svg className="w-3 h-3 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                &Sigma; w<sub>i</sub> = 100% (Normalizado)
              </span>
            </div>

            <div className="grid grid-cols-1 gap-2.5">
              {ensembleModels.slice(0, ensembleSize).map((m, idx) => (
                <div
                  key={idx}
                  className="p-3 rounded-lg bg-[#111215] border border-[#23252e] space-y-2 hover:border-[#2f323e] transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-5 h-5 rounded-full bg-cyan-500/20 text-cyan-300 text-[10px] font-mono font-bold flex items-center justify-center">
                        {idx + 1}
                      </span>
                      <span className="text-xs font-semibold text-gray-200">
                        Modelo #{idx + 1}: {m.architecture}
                      </span>
                    </div>
                    <span className="text-[11px] font-mono text-cyan-300 font-semibold bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-800/40">
                      {(m.weight * 100).toFixed(0)}% (w = {m.weight.toFixed(2)})
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-center">
                    <div>
                      <label className="text-[10px] text-gray-400 block mb-1 font-medium">Arquitectura Pre-entrenada</label>
                      <select
                        value={m.architecture}
                        disabled={isTraining}
                        onChange={(e) => handleModelArchChange(idx, e.target.value)}
                        className="w-full bg-[#16171b] border border-[#23252e] rounded-lg px-2.5 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-cyan-500 font-mono disabled:opacity-60"
                      >
                        <option value="EfficientNet-B0">EfficientNet-B0 (Transfer Learning)</option>
                        <option value="ConvNeXt-Nano">ConvNeXt-Nano (Arquitectura Moderna)</option>
                        <option value="ResNet-34d">ResNet-34d (ResNet Profunda)</option>
                        <option value="PANNs-CNN14">PANNs-CNN14 (Audio Industrial CNN)</option>
                        <option value="AudioCNN">AudioCNN (Baseline Convolucional)</option>
                      </select>
                    </div>

                    <div>
                      <div className="flex justify-between items-center mb-1">
                        <label className="text-[10px] text-gray-400 font-medium">Ponderación en Inferencia (w<sub>{idx + 1}</sub>)</label>
                        <span className="text-[10px] font-mono text-gray-400">
                          {(m.weight * 100).toFixed(1)}%
                        </span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="100"
                        step="1"
                        value={Math.round(m.weight * 100)}
                        disabled={isTraining}
                        onChange={(e) => handleWeightChange(idx, parseInt(e.target.value, 10) / 100)}
                        className="w-full h-1.5 bg-[#23252e] rounded-lg appearance-none cursor-pointer accent-cyan-400"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

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
            {ensembleSize === 1
              ? "1 modelo seleccionado"
              : `${ensembleSize} modelos secuenciales (Pipeline MLOps Ensamble)`}
          </span>
        </div>

        {/* Botones de Acción (Entrenar / Detener) */}
        <div className="flex items-center gap-3 pt-1">
          <button
            type="button"
            onClick={handleStartTraining}
            disabled={isTraining}
            className={`flex-1 py-2.5 rounded-lg text-white font-bold text-xs transition-all flex items-center justify-center gap-2 shadow-lg disabled:opacity-40 disabled:cursor-not-allowed ${
              ensembleSize === 3
                ? "bg-gradient-to-r from-emerald-600 via-teal-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 shadow-emerald-950/40"
                : ensembleSize === 2
                ? "bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 shadow-cyan-950/40"
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
                    ? `Ensamble [${triadProgress.modelIdx}/${triadProgress.totalModels} ${triadProgress.currentArch}] · Época ${currentEpoch}/${totalEpochs}...`
                    : `Entrenando Época ${currentEpoch} / ${totalEpochs}...`}
                </span>
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clipRule="evenodd" />
                </svg>
                <span>
                  {ensembleSize === 1
                    ? "Iniciar Entrenamiento Local (1 Modelo)"
                    : ensembleSize === 2
                    ? "Iniciar Pipeline Dúo Ensamble (2 Modelos)"
                    : "Iniciar Pipeline de Tri Ensamble (3 Modelos)"}
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
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
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

          {/* Selector de Pestañas / Pills por Modelo en Ensambles */}
          {availableChartModels.length > 1 && (
            <div className="flex flex-wrap items-center gap-1.5 p-1 bg-[#111215] border border-[#23252e] rounded-lg">
              <button
                type="button"
                onClick={() => setChartModelFilter("current")}
                className={`px-2 py-1 rounded text-[10px] font-mono transition-all ${
                  chartModelFilter === "current"
                    ? "bg-blue-600 text-white font-semibold shadow-sm"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                Modelo Actual
              </button>
              {availableChartModels.map((m) => (
                <button
                  key={`filter-${m.index}`}
                  type="button"
                  onClick={() => setChartModelFilter(m.index)}
                  className={`px-2 py-1 rounded text-[10px] font-mono transition-all ${
                    chartModelFilter === m.index
                      ? "bg-cyan-600 text-white font-semibold shadow-sm"
                      : "text-gray-400 hover:text-gray-200"
                  }`}
                >
                  Modelo {m.index}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setChartModelFilter("all")}
                className={`px-2 py-1 rounded text-[10px] font-mono transition-all ${
                  chartModelFilter === "all"
                    ? "bg-emerald-600 text-white font-semibold shadow-sm"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                Todos
              </button>
            </div>
          )}

          {/* Tarjetas de Métricas Actuales */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <div className="bg-[#111215] border border-[#23252e] rounded-lg p-2 text-center">
              <span className="text-[10px] text-gray-500 block">Train Loss</span>
              <span className="text-xs font-mono font-bold text-amber-400">
                {displayMetrics.trainLoss ? displayMetrics.trainLoss.toFixed(4) : "—"}
              </span>
            </div>
            <div className="bg-[#111215] border border-[#23252e] rounded-lg p-2 text-center">
              <span className="text-[10px] text-gray-500 block">Val Loss</span>
              <span className="text-xs font-mono font-bold text-rose-400">
                {displayMetrics.valLoss ? displayMetrics.valLoss.toFixed(4) : "—"}
              </span>
            </div>
            <div className="bg-[#111215] border border-[#23252e] rounded-lg p-2 text-center">
              <span className="text-[10px] text-gray-500 block">Train Acc</span>
              <span className="text-xs font-mono font-bold text-blue-400">
                {displayMetrics.trainAcc ? `${displayMetrics.trainAcc.toFixed(1)}%` : "—"}
              </span>
            </div>
            <div className="bg-[#111215] border border-[#23252e] rounded-lg p-2 text-center">
              <span className="text-[10px] text-gray-500 block">Val Acc</span>
              <span className="text-xs font-mono font-bold text-emerald-400">
                {displayMetrics.valAcc ? `${displayMetrics.valAcc.toFixed(1)}%` : "—"}
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
                      <span className="w-2 h-0.5 bg-rose-400 inline-block" /> Val Loss (escala {chartData.maxLoss.toFixed(1)})
                    </span>
                  </div>
                  <span className="font-mono">Punto {chartData.totalPoints}/{chartData.maxPoints}</span>
                </div>

                {/* SVG Curves */}
                <div className="flex-1 w-full relative mt-2">
                  <svg className="w-full h-full overflow-visible" viewBox="0 0 300 100" preserveAspectRatio="none">
                    {/* Guías de cuadrícula */}
                    <line x1="0" y1="20" x2="300" y2="20" stroke="#1f2128" strokeDasharray="3 3" />
                    <line x1="0" y1="50" x2="300" y2="50" stroke="#1f2128" strokeDasharray="3 3" />
                    <line x1="0" y1="80" x2="300" y2="80" stroke="#1f2128" strokeDasharray="3 3" />

                    {/* Separadores entre modelos en ensamble */}
                    {chartData.separators.map((sep) => (
                      <g key={`sep-${sep.modelIndex}`}>
                        <line
                          x1={sep.x}
                          y1={10}
                          x2={sep.x}
                          y2={90}
                          stroke="#374151"
                          strokeWidth="1.5"
                          strokeDasharray="2 2"
                        />
                        <text
                          x={sep.x + 3}
                          y={20}
                          fill="#9ca3af"
                          fontSize="8"
                          fontFamily="monospace"
                        >
                          {sep.label}
                        </text>
                      </g>
                    ))}

                    {/* Segmentos de Curvas por Modelo */}
                    {chartData.segments.map((seg) => (
                      <g key={`segment-${seg.modelIndex}`}>
                        {/* Curva de Accuracy (Verde) */}
                        {seg.points.length > 1 && (
                          <polyline
                            fill="none"
                            stroke="#10b981"
                            strokeWidth="2.5"
                            points={seg.accPolyline}
                          />
                        )}

                        {/* Curva de Loss (Rosa/Rojo punteada) */}
                        {seg.points.length > 1 && (
                          <polyline
                            fill="none"
                            stroke="#f43f5e"
                            strokeWidth="2"
                            strokeDasharray="2 2"
                            points={seg.lossPolyline}
                          />
                        )}

                        {/* Puntos de Accuracy */}
                        {seg.points.map((p, pIdx) => (
                          <circle
                            key={`acc-${seg.modelIndex}-${pIdx}`}
                            cx={p.x}
                            cy={p.yAcc}
                            r="3"
                            fill="#10b981"
                          >
                            <title>{`[${seg.architecture}] Época ${p.metric.epoca}: Val Acc ${p.metric.val_acc}%`}</title>
                          </circle>
                        ))}

                        {/* Puntos de Loss */}
                        {seg.points.map((p, pIdx) => (
                          <circle
                            key={`loss-${seg.modelIndex}-${pIdx}`}
                            cx={p.x}
                            cy={p.yLoss}
                            r="2.5"
                            fill="#f43f5e"
                          >
                            <title>{`[${seg.architecture}] Época ${p.metric.epoca}: Val Loss ${p.metric.val_loss}`}</title>
                          </circle>
                        ))}
                      </g>
                    ))}
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
                <th className="pb-3 font-medium">Modelo / Versión</th>
                <th className="pb-3 font-medium">Dataset / Dominio</th>
                <th className="pb-3 font-medium">Épocas</th>
                <th className="pb-3 font-medium">Precisión (Val Acc)</th>
                <th className="pb-3 font-medium">Pérdida (Loss)</th>
                <th className="pb-3 font-medium">Archivo</th>
                <th className="pb-3 font-medium text-right pr-2">Acción</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#23252e]/60">
              {history.map((item) => {
                const isBirds =
                  item.dataset?.toLowerCase().includes("aves") ||
                  item.name?.toLowerCase().includes("aves") ||
                  item.filename?.toLowerCase().includes("aves") ||
                  item.id === 6;

                return (
                  <tr key={item.id} className="hover:bg-[#1c1e24]/40 transition-colors">
                    <td className="py-3 font-medium text-gray-200">
                      <div className="flex items-center gap-2">
                        <span>{item.name || `${item.architecture} (v${item.version || 1})`}</span>
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-blue-950/70 text-blue-300 border border-blue-800/60">
                          v{item.version || 1}
                        </span>
                      </div>
                    </td>
                    <td className="py-3">
                      {isBirds ? (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-950/60 text-emerald-400 border border-emerald-800/50 inline-flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                          Aves Chilenas
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-950/60 text-amber-400 border border-amber-800/50 inline-flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                          Motores
                        </span>
                      )}
                    </td>
                    <td className="py-3 text-gray-400 font-mono">{item.epochs}</td>
                    <td className="py-3 font-mono font-semibold">
                      <span className={item.accuracy >= 75 ? "text-emerald-400" : "text-amber-400"}>
                        {item.accuracy ? `${item.accuracy.toFixed(2)}%` : "—"}
                      </span>
                    </td>
                    <td className="py-3 text-gray-400 font-mono">
                      {item.loss ? item.loss.toFixed(4) : "—"}
                    </td>
                    <td className="py-3 text-gray-400 font-mono text-[11px] max-w-[220px] truncate" title={item.filename}>
                      {item.filename}
                    </td>
                    <td className="py-3 text-right pr-2">
                      <button
                        type="button"
                        onClick={() => setSelectedModelModal(item)}
                        className="text-[11px] text-cyan-300 hover:text-white px-2.5 py-1 rounded bg-cyan-950/60 hover:bg-cyan-900/60 border border-cyan-800/60 hover:border-cyan-600 transition-colors inline-flex items-center gap-1.5 shadow-sm"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <span>Ficha Técnica</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Modal de Ficha Técnica Detallada */}
        {selectedModelModal && (
          <div
            data-testid="modal-ficha-tecnica"
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200"
          >
            <div className="bg-[#16171b] border border-[#2d303b] rounded-2xl max-w-2xl md:max-w-4xl lg:max-w-5xl w-full p-6 shadow-2xl space-y-5 max-h-[90vh] overflow-y-auto">
              {/* Header */}
              <div className="flex items-start justify-between pb-3 border-b border-[#23252e]">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-blue-950/70 text-blue-300 border border-blue-800/60">
                      v{selectedModelModal.version || 1}
                    </span>
                    <h2 className="text-base font-bold text-white tracking-tight">
                      {selectedModelModal.name || `${selectedModelModal.architecture} (v${selectedModelModal.version || 1})`}
                    </h2>
                  </div>
                  <p className="text-xs text-gray-400 mt-1">
                    Ficha Técnica del Modelo · Artefacto y parámetros reproducibles
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedModelModal(null)}
                  className="text-gray-400 hover:text-white p-1 rounded-lg hover:bg-[#23252e] transition-colors"
                  aria-label="Cerrar"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              {/* 3 Tarjetas de Especificaciones */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
                {/* 1) Hiperparámetros de Entrenamiento */}
                <div className="bg-[#111215] border border-[#23252e] rounded-xl p-4 space-y-2.5">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-indigo-400">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    <span>Hiperparámetros de Entrenamiento</span>
                  </div>
                  <div className="space-y-1.5 text-[11px]">
                    <div className="flex justify-between items-center gap-2">
                      <span className="text-gray-400 shrink-0">Learning Rate:</span>
                      <span className="text-gray-200 font-mono font-medium text-right">
                        {selectedModelModal.hyperparameters?.learning_rate ?? "0.001"}
                      </span>
                    </div>
                    <div className="flex justify-between items-center gap-2">
                      <span className="text-gray-400 shrink-0">Batch Size:</span>
                      <span className="text-gray-200 font-mono font-medium text-right">
                        {selectedModelModal.hyperparameters?.batch_size ?? 16}
                      </span>
                    </div>
                    <div className="flex justify-between items-center gap-2">
                      <span className="text-gray-400 shrink-0">Optimizer:</span>
                      <span className="text-cyan-400 font-mono font-medium text-right">
                        {selectedModelModal.hyperparameters?.optimizer ?? "AdamW"}
                      </span>
                    </div>
                    <div className="flex justify-between items-center gap-2">
                      <span className="text-gray-400 shrink-0">Loss Function:</span>
                      <span className="text-emerald-400 font-mono font-medium text-right">
                        {selectedModelModal.hyperparameters?.loss_type ?? "Focal Loss"}
                      </span>
                    </div>
                  </div>
                </div>

                {/* 2) Parámetros de Física de Audio */}
                <div className="bg-[#111215] border border-[#23252e] rounded-xl p-4 space-y-2.5">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-teal-400">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                    </svg>
                    <span>Parámetros de Física de Audio</span>
                  </div>
                  <div className="space-y-1.5 text-[11px]">
                    <div className="flex justify-between items-center gap-2">
                      <span className="text-gray-400 shrink-0">Sample Rate:</span>
                      <span className="text-gray-200 font-mono font-medium whitespace-nowrap text-right">
                        {selectedModelModal.audio_specs?.target_sr ?? 22050} Hz
                      </span>
                    </div>
                    <div className="flex justify-between items-center gap-2">
                      <span className="text-gray-400 shrink-0">Duración Ventana:</span>
                      <span className="text-gray-200 font-mono font-medium whitespace-nowrap text-right">
                        {selectedModelModal.audio_specs?.duration_seconds ?? 5.0} s
                      </span>
                    </div>
                    <div className="flex justify-between items-center gap-2">
                      <span className="text-gray-400 shrink-0">Bandas Mel:</span>
                      <span className="text-gray-200 font-mono font-medium whitespace-nowrap text-right">
                        {selectedModelModal.audio_specs?.n_mels ?? 128} mels (FFT {selectedModelModal.audio_specs?.n_fft ?? 2048})
                      </span>
                    </div>
                    <div className="flex justify-between items-center gap-2">
                      <span className="text-gray-400 shrink-0">Rango Frecuencia:</span>
                      <span className="text-gray-200 font-mono font-medium whitespace-nowrap text-right">
                        {selectedModelModal.audio_specs?.fmin ?? 50} - {selectedModelModal.audio_specs?.fmax ?? 11025} Hz
                      </span>
                    </div>
                  </div>
                </div>

                {/* 3) Especificaciones del Artefacto */}
                <div className="bg-[#111215] border border-[#23252e] rounded-xl p-4 space-y-2.5">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                    </svg>
                    <span>Especificaciones del Artefacto</span>
                  </div>
                  <div className="space-y-1.5 text-[11px]">
                    <div>
                      <span className="text-gray-400 block mb-0.5">Archivo binario (.pt):</span>
                      <span className="text-cyan-300 font-mono text-[10px] break-all block">
                        {selectedModelModal.filename}
                      </span>
                    </div>
                    <div className="flex justify-between pt-1">
                      <span className="text-gray-400">Tamaño:</span>
                      <span className="text-gray-200 font-mono font-medium">
                        {selectedModelModal.file_size_bytes
                          ? `${(selectedModelModal.file_size_bytes / (1024 * 1024)).toFixed(2)} MB`
                          : "46.56 MB"}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-400">Clases soportadas:</span>
                      <span className="text-emerald-400 font-mono font-semibold">
                        {selectedModelModal.classes_count ?? (selectedModelModal.classes?.length ?? 15)} clases
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Taxonomía de Clases */}
              {selectedModelModal.classes && selectedModelModal.classes.length > 0 && (
                <div className="bg-[#111215] border border-[#23252e] rounded-xl p-3.5 space-y-2">
                  <span className="text-[11px] text-gray-400 font-medium block">
                    Taxonomía de Clases Soportadas ({selectedModelModal.classes_count ?? selectedModelModal.classes.length}):
                  </span>
                  <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto pr-1">
                    {selectedModelModal.classes.map((clsName, i) => (
                      <span
                        key={i}
                        className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#1c1e24] text-gray-300 border border-[#2b2e38]"
                      >
                        {clsName}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Footer */}
              <div className="flex justify-end pt-2 border-t border-[#23252e]">
                <button
                  type="button"
                  onClick={() => setSelectedModelModal(null)}
                  className="px-4 py-2 rounded-lg bg-[#23252e] hover:bg-[#2d303b] text-gray-200 text-xs font-medium transition-colors"
                >
                  Cerrar
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
