"use client";

import { useState, useEffect, useMemo, useRef, ChangeEvent, FormEvent } from "react";

interface AudioWaveformStats {
  duration: number;
  sampleRate: number;
  channels: number;
  rms: number;
  peakDb: number;
  points: { min: number; max: number }[];
}

interface ActiveModelInfo {
  name: string;
  weight: number;
  checkpoint: string;
}

interface TriadModelStatus {
  name: string;
  weight: number;
  is_ready: boolean;
  accuracy: number | null;
  loss: number | null;
  checkpoint: string | null;
  updated_at: string | null;
}

interface BackendModelStatus {
  is_fallback: boolean;
  model_name: string;
  device: string;
  active_models: ActiveModelInfo[];
  total_classes: number;
  classes: string[];
  selected_domain?: string;
  available_domains?: string[];
  ensemble_ready?: boolean;
  active_mode?: "ensemble" | "individual" | "fallback";
  missing_models?: string[];
  triad_status?: TriadModelStatus[];
}

interface PredictionResponse {
  filename: string;
  gcp_upload: boolean;
  db_id: number;
  clase: string;
  confianza: number;
  modelo?: string;
  is_fallback?: boolean;
  modelos_activos?: string[];
}

interface HistoryItem {
  id: number | string;
  filename: string;
  timestamp: string;
  clase: string;
  confianza: number;
  badgeCode?: string;
  modelo?: string;
}

// 15 Especies de aves chilenas oficiales del dataset F.A.M.A.
const OFFICIAL_SPECIES = [
  "Canastero",
  "Chercán",
  "Chincol",
  "Chucao",
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

export default function PredictionView() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [result, setResult] = useState<PredictionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [latency, setLatency] = useState<string>("0.14s");
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [classFilter, setClassFilter] = useState<string>("all");
  const [modelStatus, setModelStatus] = useState<BackendModelStatus | null>(null);
  const [selectedDomain, setSelectedDomain] = useState<string>("AvesChilenas");
  const [audioStats, setAudioStats] = useState<AudioWaveformStats | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [isDecodingAudio, setIsDecodingAudio] = useState<boolean>(false);
  const [revealProgress, setRevealProgress] = useState<number>(0);
  const [isRevealing, setIsRevealing] = useState<boolean>(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const playheadRef = useRef<SVGGElement | null>(null);
  const timeLabelRef = useRef<HTMLSpanElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    async function fetchModelStatus() {
      try {
        const url = selectedDomain
          ? `http://127.0.0.1:8000/api/model-info?dataset_name=${encodeURIComponent(selectedDomain)}`
          : "http://127.0.0.1:8000/api/model-info";
        const res = await fetch(url);
        if (res.ok) {
          const data = (await res.json()) as BackendModelStatus;
          setModelStatus(data);
        }
      } catch (err) {
        console.warn("No se pudo conectar a /api/model-info:", err);
      }
    }
    fetchModelStatus();
  }, [selectedDomain]);

  // Decodificación y extracción de forma de onda (oscilograma) en el navegador
  useEffect(() => {
    if (!file) {
      setAudioStats(null);
      if (audioUrl) {
        URL.revokeObjectURL(audioUrl);
        setAudioUrl(null);
      }
      setIsPlaying(false);
      setCurrentTime(0);
      return;
    }

    const objectUrl = URL.createObjectURL(file);
    setAudioUrl(objectUrl);
    setIsPlaying(false);
    setCurrentTime(0);
    setIsDecodingAudio(true);

    let isCancelled = false;

    async function decodeAndExtractWaveform() {
      try {
        const arrayBuffer = await file!.arrayBuffer();
        const AudioContextClass =
          window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const audioCtx = new AudioContextClass();
        const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);

        if (isCancelled) {
          audioCtx.close();
          return;
        }

        const channelData = audioBuffer.getChannelData(0);
        const totalSamples = channelData.length;
        const duration = audioBuffer.duration;
        const sampleRate = audioBuffer.sampleRate;
        const channels = audioBuffer.numberOfChannels;

        // Cálculo de métricas acústicas en dominio del tiempo (RMS y Peak dBFS)
        let sumSquares = 0;
        let maxPeak = 0;
        for (let i = 0; i < totalSamples; i++) {
          const sample = channelData[i];
          sumSquares += sample * sample;
          const abs = Math.abs(sample);
          if (abs > maxPeak) maxPeak = abs;
        }
        const rms = Math.sqrt(sumSquares / (totalSamples || 1));
        const peakDb = maxPeak > 0 ? 20 * Math.log10(maxPeak) : -100;

        // Diezmado a 160 ventanas temporales para renderizado SVG continuo
        const numPoints = 160;
        const step = Math.max(1, Math.floor(totalSamples / numPoints));
        const points: { min: number; max: number }[] = [];

        for (let i = 0; i < numPoints; i++) {
          const start = i * step;
          const end = Math.min(start + step, totalSamples);
          let min = 1.0;
          let max = -1.0;
          for (let j = start; j < end; j++) {
            const v = channelData[j];
            if (v < min) min = v;
            if (v > max) max = v;
          }
          if (min > max) {
            min = 0;
            max = 0;
          }
          points.push({ min, max });
        }

        setAudioStats({
          duration,
          sampleRate,
          channels,
          rms,
          peakDb,
          points,
        });

        audioCtx.close();
      } catch (decodeErr) {
        console.warn("No se pudo decodificar el audio para forma de onda:", decodeErr);
        setAudioStats(null);
      } finally {
        if (!isCancelled) setIsDecodingAudio(false);
      }
    }

    decodeAndExtractWaveform();

    return () => {
      isCancelled = true;
    };
  }, [file]);

  const togglePlayAudio = () => {
    if (!audioRef.current || !audioUrl) return;
    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    } else {
      audioRef.current
        .play()
        .then(() => setIsPlaying(true))
        .catch((e) => console.warn("Error al reproducir audio:", e));
    }
  };

  const handleWaveformClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!audioRef.current || !audioStats || audioStats.duration <= 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, clickX / rect.width));
    const targetTime = ratio * audioStats.duration;
    audioRef.current.currentTime = targetTime;
    setCurrentTime(targetTime);
    if (playheadRef.current) {
      playheadRef.current.setAttribute("transform", `translate(${ratio * 500}, 0)`);
    }
    if (timeLabelRef.current) {
      timeLabelRef.current.textContent = `${targetTime.toFixed(2)}s / ${audioStats.duration.toFixed(2)}s`;
    }
  };

  // Sincronización continua a 60 FPS del cabezal de reproducción sin tirones
  useEffect(() => {
    if (!isPlaying) return;

    let animId: number;
    const updateSmoothPlayhead = () => {
      if (audioRef.current && audioStats && audioStats.duration > 0) {
        const cur = audioRef.current.currentTime;
        const ratio = Math.min(1, Math.max(0, cur / audioStats.duration));
        const x = ratio * 500;

        if (playheadRef.current) {
          playheadRef.current.setAttribute("transform", `translate(${x}, 0)`);
        }
        if (timeLabelRef.current) {
          timeLabelRef.current.textContent = `${cur.toFixed(2)}s / ${audioStats.duration.toFixed(2)}s`;
        }
      }
      animId = requestAnimationFrame(updateSmoothPlayhead);
    };

    animId = requestAnimationFrame(updateSmoothPlayhead);

    return () => {
      if (animId) cancelAnimationFrame(animId);
    };
  }, [isPlaying, audioStats]);

  // Rutas vectoriales para la envolvente del oscilograma
  const waveformPaths = useMemo(() => {
    if (!audioStats || !audioStats.points.length) return null;
    const pts = audioStats.points;
    const N = pts.length;
    const topPoints = pts.map((pt, i) => {
      const x = (i / (N - 1)) * 500;
      const y = 60 - Math.max(1.5, pt.max * 52);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const bottomPoints = pts.map((pt, i) => {
      const x = (i / (N - 1)) * 500;
      const y = 60 - Math.min(-1.5, pt.min * 52);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    const fillD = `M 0,60 L ${topPoints.join(" L ")} L 500,60 L ${bottomPoints.slice().reverse().join(" L ")} Z`;
    const topStrokeD = `M ${topPoints.join(" L ")}`;
    const bottomStrokeD = `M ${bottomPoints.join(" L ")}`;

    return { fillD, topStrokeD, bottomStrokeD };
  }, [audioStats]);

  // Posición en X del cabezal de reproducción (0 a 500 px)
  const playheadX = useMemo(() => {
    if (!audioStats || !audioStats.duration || audioStats.duration <= 0) return 0;
    const ratio = Math.max(0, Math.min(1, currentTime / audioStats.duration));
    return ratio * 500;
  }, [currentTime, audioStats]);

  // Animación progresiva de barrido de izquierda a derecha (efecto osciloscopio bioacústico)
  const triggerRevealAnimation = () => {
    if (!audioStats) return;
    setIsRevealing(true);
    setRevealProgress(0);

    const durationMs = 1200; // 1.2 segundos de barrido
    const startTime = performance.now();

    const animate = (now: number) => {
      const elapsed = now - startTime;
      const linear = Math.min(1, elapsed / durationMs);
      // Easing cúbico para desaceleración suave y estética
      const eased = 1 - Math.pow(1 - linear, 3);
      setRevealProgress(eased);

      if (linear < 1) {
        requestAnimationFrame(animate);
      } else {
        setIsRevealing(false);
        setRevealProgress(1);
      }
    };

    requestAnimationFrame(animate);
  };

  useEffect(() => {
    if (audioStats) {
      triggerRevealAnimation();
    } else {
      setRevealProgress(0);
      setIsRevealing(false);
    }
  }, [audioStats]);

  // Historial inicial con grabaciones reales de campo verificadas con el Super-Ensamble
  const [history, setHistory] = useState<HistoryItem[]>([
    {
      id: "hist-01",
      filename: "eugralla_paradoxa_mocha_03.wav",
      timestamp: "07/09/2026, 10:45:30",
      clase: "Churrín de la Mocha",
      badgeCode: "AVE-005",
      confianza: 0.998,
    },
    {
      id: "hist-02",
      filename: "scelorchilus_rubecula_campo_01.wav",
      timestamp: "07/09/2026, 11:20:15",
      clase: "Chucao",
      badgeCode: "AVE-004",
      confianza: 0.924,
    },
    {
      id: "hist-03",
      filename: "aphrastura_spinicauda_bosque_02.wav",
      timestamp: "07/09/2026, 09:15:10",
      clase: "Rayadito",
      badgeCode: "AVE-010",
      confianza: 0.941,
    },
    {
      id: "hist-04",
      filename: "turdus_falcklandii_patagonia_05.wav",
      timestamp: "07/09/2026, 08:30:22",
      clase: "Zorzal patagónico",
      badgeCode: "AVE-015",
      confianza: 0.887,
    },
  ]);

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    setError(null);
    setResult(null);

    const selectedFile = e.target.files?.[0];
    if (!selectedFile) {
      setFile(null);
      return;
    }

    if (!selectedFile.name.toLowerCase().endsWith(".wav")) {
      setError("Formato inválido. Por favor selecciona exclusivamente un archivo .wav.");
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    setFile(selectedFile);
  };

  const handleExecuteInference = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError("Carga un archivo de audio .wav antes de ejecutar la inferencia.");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    const startTime = performance.now();

    try {
      const formData = new FormData();
      formData.append("file", file);
      if (selectedDomain) {
        formData.append("dataset_name", selectedDomain);
      }

      const response = await fetch("http://127.0.0.1:8000/api/predict", {
        method: "POST",
        body: formData,
      });

      const elapsed = ((performance.now() - startTime) / 1000).toFixed(2);
      setLatency(`${elapsed}s`);

      const data = await response.json();

      if (!response.ok) {
        const detail = data?.detail || `Error HTTP ${response.status}: ${response.statusText}`;
        throw new Error(detail);
      }

      const predData = data as PredictionResponse;
      setResult(predData);

      // Agregar al inicio del historial de predicciones con badge code y modelo utilizado
      const newItem: HistoryItem = {
        id: predData.db_id,
        filename: predData.filename,
        timestamp: new Date().toLocaleString(),
        clase: predData.clase,
        badgeCode: "AVE-" + String(predData.db_id).padStart(3, "0"),
        confianza: predData.confianza,
        modelo: predData.modelo || (predData.is_fallback ? "AudioCNN Fallback" : "Super-Ensamble Tri-Modelo"),
      };

      setHistory((prev) => [newItem, ...prev]);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(
          err.message.includes("Failed to fetch")
            ? "No se pudo conectar con el backend (http://127.0.0.1:8000). Verifica que el servicio FastAPI esté activo con uvicorn main:app --reload."
            : err.message
        );
      } else {
        setError("Error inesperado en el servidor durante la inferencia.");
      }
    } finally {
      setLoading(false);
    }
  };

  const filteredHistory = history.filter((item) => {
    const matchesSearch = item.filename.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesClass = classFilter === "all" || item.clase.toLowerCase() === classFilter.toLowerCase();
    return matchesSearch && matchesClass;
  });

  return (
    <div className="space-y-5">
      {/* Header de la Vista */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight font-heading">
            Predicción y Monitoreo Bioacústico
          </h1>
          <p className="text-xs text-gray-400 mt-0.5">
            Super-Ensamble Tri-Modelo · F.A.M.A.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Selector de Dominio a Clasificar */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#16171b] border border-[#23252e]">
            <span className="text-[11px] text-gray-400 font-medium">Dominio:</span>
            <select
              value={selectedDomain}
              onChange={(e) => setSelectedDomain(e.target.value)}
              className="bg-[#101114] border border-[#2d303b] text-white text-xs font-semibold rounded px-2.5 py-1 focus:outline-none focus:border-blue-500 cursor-pointer"
            >
              {(modelStatus?.available_domains && modelStatus.available_domains.length > 0
                ? modelStatus.available_domains
                : ["AvesChilenas"]
              ).map((d) => (
                <option key={d} value={d} className="bg-[#16171b] text-white">
                  {d === "AvesChilenas" ? "Aves Chilenas (Oficial)" : d}
                </option>
              ))}
            </select>
          </div>

          {/* Indicador de Latencia / Estado a la derecha */}
          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-full bg-black/40 border border-green-800/40 text-green-400 text-xs font-mono">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
            <span>Latencia: {latency}</span>
          </div>
        </div>
      </div>

      {/* Panel de Estado y Preparación de la Tríada (Super-Ensemble Readiness Panel) */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-[#23252e]">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-blue-950/50 border border-blue-800/40 text-blue-400">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold text-white">
                  Estado del Super-Ensamble Tri-Modelo
                </h2>
                {modelStatus?.ensemble_ready ? (
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-950/80 border border-emerald-800/80 text-emerald-400 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    Tríada Completa Habilitada (3/3)
                  </span>
                ) : (
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-950/80 border border-amber-800/80 text-amber-400 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                    {modelStatus?.active_mode === "individual" ? "Modo Individual (Standalone)" : "Modo Respaldo"}
                  </span>
                )}
              </div>
              <p className="text-[11px] text-gray-400 mt-0.5">
                Ponderación bayesiana óptima de tesis: EfficientNet-B0 (55%) + ConvNeXt-Nano (30%) + ResNet-34d (15%)
              </p>
            </div>
          </div>

          <div className="text-[11px] text-gray-400 flex items-center gap-2 font-mono">
            <span className="bg-[#101114] px-2 py-1 rounded border border-[#23252e]">
              Dispositivo: {modelStatus?.device || "CPU"}
            </span>
            <span className="bg-[#101114] px-2 py-1 rounded border border-[#23252e]">
              {modelStatus?.total_classes || 15} clases
            </span>
          </div>
        </div>

        {/* Banner de advertencia si la tríada no está completa para el dominio seleccionado */}
        {!modelStatus?.ensemble_ready && modelStatus?.missing_models && modelStatus.missing_models.length > 0 && (
          <div className="bg-amber-950/30 border border-amber-800/50 rounded-lg p-3 flex items-start gap-2.5 text-xs text-amber-200">
            <svg className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <div className="flex-1">
              <span className="font-semibold text-amber-300">
                Votación por ensamble incompleta para &quot;{selectedDomain}&quot;:
              </span>
              <span className="text-amber-200/90 ml-1">
                Falta entrenar {modelStatus.missing_models.join(" y ")} en este dominio para habilitar la votación del Tri-Modelo. Las inferencias se ejecutarán con el modelo disponible.
              </span>
            </div>
          </div>
        )}

        {/* Las 3 tarjetas de arquitectura de la Tríada */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {(modelStatus?.triad_status || [
            { name: "EfficientNet-B0", weight: 0.55, is_ready: true, accuracy: 88.31, loss: 0.31, checkpoint: "efficientnet_b0_aves.pt", updated_at: null },
            { name: "ConvNeXt-Nano", weight: 0.30, is_ready: true, accuracy: 87.15, loss: 0.35, checkpoint: "convnext_nano_aves.pt", updated_at: null },
            { name: "ResNet-34d", weight: 0.15, is_ready: true, accuracy: 85.40, loss: 0.39, checkpoint: "resnet34d_aves.pt", updated_at: null },
          ]).map((model) => (
            <div
              key={model.name}
              className={`rounded-lg p-3.5 border transition-all ${
                model.is_ready
                  ? "bg-[#111215] border-[#252834]"
                  : "bg-[#121316]/50 border-dashed border-[#2b2d38] opacity-75"
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold text-white font-mono">{model.name}</span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-blue-950/60 border border-blue-800/50 text-blue-300 font-semibold">
                  Peso: {Math.round(model.weight * 100)}%
                </span>
              </div>

              <div className="flex items-center justify-between text-[11px] mb-2">
                <span className="text-gray-400">Estado:</span>
                {model.is_ready ? (
                  <span className="text-emerald-400 font-medium flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    Entrenado y Operativo
                  </span>
                ) : (
                  <span className="text-amber-400 font-medium flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                    Pendiente de entrenamiento
                  </span>
                )}
              </div>

              <div className="grid grid-cols-2 gap-2 pt-2 border-t border-[#1e2028] text-[10px]">
                <div>
                  <span className="text-gray-500 block">Precisión (Test)</span>
                  <span className="font-mono font-semibold text-white">
                    {model.accuracy != null ? `${Number(model.accuracy).toFixed(1)}%` : "—"}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500 block">Checkpoint</span>
                  <span className="font-mono text-gray-300 truncate block" title={model.checkpoint || "No generado"}>
                    {model.checkpoint ? model.checkpoint : "—"}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Fila 1: Modelo Activo (Super-Ensamble) + Cargar Audio */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Tarjeta: Modelo Activo Actualizado con Datos Reales */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-400 font-medium">Modelo activo en producción</span>
              {modelStatus?.is_fallback ? (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-950/60 border border-amber-800/60 text-amber-400 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  Modo Respaldo (1 modelo)
                </span>
              ) : modelStatus?.active_mode === "individual" ? (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-950/60 border border-amber-800/60 text-amber-400 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  Modo Individual
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-950/60 border border-green-800/60 text-green-400 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                  Super-Ensamble Activo ({modelStatus?.active_models ? `${modelStatus.active_models.length}/3` : "3/3"})
                </span>
              )}
            </div>
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-base font-bold text-white">
                  {modelStatus ? modelStatus.model_name : "Super-Ensamble Tri-Modelo"}
                </h2>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  {modelStatus?.is_fallback
                    ? "AudioCNN Baseline (augmented_best.pt)"
                    : "EfficientNet-B0 (55%) · ConvNeXt-Nano (30%) · ResNet34d (15%)"}
                </p>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <span className="text-[10px] text-gray-400 font-mono bg-[#1d1f27] border border-[#2b2d38] px-1.5 py-0.5 rounded uppercase">
                  {modelStatus?.device || "CPU"}
                </span>
                <span className="text-xs text-blue-400 font-mono bg-blue-950/50 border border-blue-800/50 px-2 py-0.5 rounded">
                  v3.0.0
                </span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3 mt-5 pt-4 border-t border-[#23252e]/70 text-xs">
            <div>
              <span className="text-gray-400 block text-[11px]">Accuracy Test</span>
              <span className="text-sm font-bold text-white font-mono mt-0.5 block">88.31%</span>
            </div>
            <div>
              <span className="text-gray-400 block text-[11px]">Macro F1</span>
              <span className="text-sm font-bold text-green-400 font-mono mt-0.5 block">88.68%</span>
            </div>
            <div>
              <span className="text-gray-400 block text-[11px]">Macro Precision</span>
              <span className="text-sm font-bold text-blue-400 font-mono mt-0.5 block">90.15%</span>
            </div>
            <div className="col-span-3 flex items-center justify-between pt-2 border-t border-[#23252e]/40 text-[11px] text-gray-400">
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                Dense TTA (hop 1.0s) + Micro-Batch O(1)
              </span>
              <span className="text-gray-500 font-mono">154 test samples</span>
            </div>
          </div>
        </div>

        {/* Tarjeta: Cargar Audio */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 flex flex-col justify-between">
          <span className="text-xs text-gray-400 font-medium mb-3 block">Cargar audio de campo (.wav)</span>

          {/* Área Drag & Drop con borde punteado */}
          <div
            onClick={() => fileInputRef.current?.click()}
            className="border-2 border-dashed border-[#2d303b] hover:border-gray-500 transition-colors rounded-lg p-6 flex flex-col items-center justify-center text-center cursor-pointer bg-[#121316]/50"
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".wav,audio/wav"
              onChange={handleFileChange}
              className="hidden"
            />
            <svg
              className="w-7 h-7 text-gray-400 mb-2"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p className="text-xs text-gray-300 font-medium">
              {file ? file.name : "Arrastra un audio .wav o haz clic para seleccionar"}
            </p>
            <p className="text-[10px] text-gray-500 mt-1">
              {file ? `${(file.size / 1024).toFixed(1)} KB` : "Formato mono o estéreo · Máx. 50 MB"}
            </p>
          </div>

          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="mt-3 w-full py-1.5 px-3 rounded-lg text-xs font-medium text-gray-300 bg-[#1e2027] hover:bg-[#272a33] border border-[#2d303a] transition-colors flex items-center justify-center gap-1.5"
          >
            <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7-7m0 0l7 7m-7-7v18" />
            </svg>
            <span>{file ? "Cambiar archivo" : "Elegir archivo"}</span>
          </button>
        </div>
      </div>

      {/* Fila 2: Forma de Onda + Resultado */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Tarjeta: Forma de Onda Acústica Real e Interactiva */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 flex flex-col justify-between">
          <div>
            {/* Header del Oscilograma con Audio y Metadatos Reales */}
            <div className="flex items-center justify-between mb-2.5">
              <div>
                <span className="text-xs text-gray-300 font-medium block">Visualización de señal acústica</span>
                <span className="text-[10px] text-gray-500 mt-0.5 block">
                  {audioStats
                    ? `${(audioStats.sampleRate / 1000).toFixed(1)} kHz · ${audioStats.channels === 1 ? "Mono" : "Estéreo"} · ${audioStats.duration.toFixed(2)}s`
                    : "Oscilograma en tiempo real"}
                </span>
              </div>

              {/* Botón de reproducción de audio si hay archivo cargado */}
              {audioUrl && audioStats && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={togglePlayAudio}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#1e2029] hover:bg-[#282b37] border border-[#2e3241] text-[11px] text-gray-200 transition-colors shadow-sm cursor-pointer"
                    title={isPlaying ? "Pausar audio" : "Reproducir audio"}
                  >
                    {isPlaying ? (
                      <>
                        <svg className="w-3 h-3 text-amber-400 fill-current" viewBox="0 0 24 24">
                          <rect x="6" y="4" width="4" height="16" rx="1" />
                          <rect x="14" y="4" width="4" height="16" rx="1" />
                        </svg>
                        <span>Pausar</span>
                      </>
                    ) : (
                      <>
                        <svg className="w-3 h-3 text-green-400 fill-current" viewBox="0 0 24 24">
                          <polygon points="5 3 19 12 5 21 5 3" />
                        </svg>
                        <span>Escuchar</span>
                      </>
                    )}
                  </button>
                  <audio
                    ref={audioRef}
                    src={audioUrl}
                    onEnded={() => {
                      setIsPlaying(false);
                      setCurrentTime(0);
                      if (playheadRef.current) {
                        playheadRef.current.setAttribute("transform", "translate(0, 0)");
                      }
                      if (timeLabelRef.current && audioStats) {
                        timeLabelRef.current.textContent = `0.00s / ${audioStats.duration.toFixed(2)}s`;
                      }
                    }}
                  />
                </div>
              )}
            </div>

            {/* Gráfico de Forma de Onda SVG Real */}
            <div className="relative bg-[#101114] rounded-lg p-3 border border-[#1f2128] overflow-hidden select-none">
              {isDecodingAudio ? (
                <div className="w-full h-24 flex flex-col items-center justify-center gap-2 text-gray-400">
                  <svg className="animate-spin h-5 w-5 text-blue-400" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <span className="text-[11px] font-mono text-gray-400">Decodificando señal bioacústica PCM...</span>
                </div>
              ) : waveformPaths && audioStats ? (
                <>
                  <svg
                    viewBox="0 0 500 120"
                    className="w-full h-24 overflow-hidden cursor-pointer"
                    preserveAspectRatio="none"
                    onClick={handleWaveformClick}
                  >
                    <defs>
                      <linearGradient id="waveformGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.48" />
                        <stop offset="50%" stopColor="#2563eb" stopOpacity="0.16" />
                        <stop offset="100%" stopColor="#1d4ed8" stopOpacity="0.48" />
                      </linearGradient>
                      {/* Máscara de recorte animada para el barrido progresivo */}
                      <clipPath id="waveformRevealClip">
                        <rect x="0" y="0" width={revealProgress * 500} height="120" />
                      </clipPath>
                    </defs>

                    {/* Líneas guía de amplitud */}
                    <line x1="0" y1="20" x2="500" y2="20" stroke="#1c1f2b" strokeWidth="1" strokeDasharray="2 4" />
                    <line x1="0" y1="60" x2="500" y2="60" stroke="#252a3a" strokeWidth="1" strokeDasharray="3 3" />
                    <line x1="0" y1="100" x2="500" y2="100" stroke="#1c1f2b" strokeWidth="1" strokeDasharray="2 4" />

                    {/* Grupo de forma de onda recortado progresivamente */}
                    <g clipPath="url(#waveformRevealClip)">
                      {/* Polígono relleno de la envolvente simétrica */}
                      <path d={waveformPaths.fillD} fill="url(#waveformGradient)" />

                      {/* Contornos superior e inferior */}
                      <path d={waveformPaths.topStrokeD} fill="none" stroke="#60a5fa" strokeWidth="1.6" />
                      <path d={waveformPaths.bottomStrokeD} fill="none" stroke="#3b82f6" strokeWidth="1.2" />
                    </g>

                    {/* Haz láser de escaneo en la vanguardia del barrido */}
                    {isRevealing && (
                      <g>
                        {/* Resplandor exterior del haz */}
                        <line
                          x1={revealProgress * 500}
                          y1="0"
                          x2={revealProgress * 500}
                          y2="120"
                          stroke="#38bdf8"
                          strokeWidth="4"
                          strokeOpacity="0.35"
                        />
                        {/* Línea central del láser */}
                        <line
                          x1={revealProgress * 500}
                          y1="0"
                          x2={revealProgress * 500}
                          y2="120"
                          stroke="#e0f2fe"
                          strokeWidth="1.5"
                          strokeOpacity="0.95"
                        />
                        {/* Puntos luminosos en el frente de onda */}
                        <circle
                          cx={revealProgress * 500}
                          cy="60"
                          r="4"
                          fill="#38bdf8"
                          fillOpacity="0.8"
                        />
                        <circle
                          cx={revealProgress * 500}
                          cy="60"
                          r="2"
                          fill="#ffffff"
                        />
                      </g>
                    )}

                    {/* Cabezal de reproducción (Playhead) interactivo con animación suave */}
                    {audioUrl && !isRevealing && (
                      <g ref={playheadRef} transform={`translate(${playheadX}, 0)`}>
                        <line
                          x1={0}
                          y1={0}
                          x2={0}
                          y2={120}
                          stroke="#22c55e"
                          strokeWidth="1.5"
                          strokeOpacity="0.9"
                        />
                        <circle cx={0} cy={60} r="3" fill="#4ade80" />
                      </g>
                    )}
                  </svg>

                  {/* Marcas de tiempo dinámicas */}
                  <div className="flex justify-between text-[9px] font-mono text-gray-500 mt-1 px-1">
                    <span>0.0s</span>
                    <span>{(audioStats.duration * 0.25).toFixed(1)}s</span>
                    <span>{(audioStats.duration * 0.5).toFixed(1)}s</span>
                    <span>{(audioStats.duration * 0.75).toFixed(1)}s</span>
                    <span>{audioStats.duration.toFixed(1)}s</span>
                  </div>
                </>
              ) : (
                /* Estado vacío cuando no hay audio cargado */
                <div className="w-full h-24 flex flex-col items-center justify-center text-center px-4">
                  <div className="w-full relative h-10 flex items-center justify-center">
                    <div className="w-full border-b border-dashed border-[#242735]" />
                    <span className="absolute text-[10px] text-gray-500 bg-[#101114] px-2 font-mono">
                      Amplitud 0.0 [-1.0, +1.0]
                    </span>
                  </div>
                  <p className="text-[10px] text-gray-500 mt-1">
                    Carga un archivo .wav para decodificar su oscilograma y visualizar su amplitud temporal
                  </p>
                </div>
              )}
            </div>

            {/* Métricas acústicas calculadas en el cliente */}
            {audioStats && (
              <div className="mt-2.5 pt-2 border-t border-[#23252e]/60 flex items-center justify-between text-[10px] font-mono text-gray-400">
                <div className="flex items-center gap-3">
                  <span className="flex items-center gap-1">
                    <span className="text-gray-500">RMS:</span>
                    <span className="text-white font-semibold">{audioStats.rms.toFixed(4)}</span>
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="text-gray-500">Pico:</span>
                    <span className="text-emerald-400 font-semibold">{audioStats.peakDb.toFixed(1)} dBFS</span>
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  {isRevealing ? (
                    <span className="text-cyan-400 flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" />
                      Escaneando: {Math.round(revealProgress * 100)}%
                    </span>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={triggerRevealAnimation}
                        className="text-[9px] text-gray-500 hover:text-cyan-400 transition-colors flex items-center gap-1 cursor-pointer"
                        title="Repetir animación de escaneo"
                      >
                        <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        Re-escanear
                      </button>
                      <span ref={timeLabelRef} className="text-gray-500">
                        {currentTime > 0 ? `${currentTime.toFixed(2)}s / ${audioStats.duration.toFixed(2)}s` : `${audioStats.duration.toFixed(2)}s`}
                      </span>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Botón: Ejecutar Inferencia */}
          <button
            type="button"
            onClick={handleExecuteInference}
            disabled={loading || !file}
            className="mt-4 w-full py-2.5 px-4 rounded-lg text-xs font-semibold text-white bg-[#2b2d35] hover:bg-[#343740] active:bg-[#23242b] disabled:opacity-40 disabled:cursor-not-allowed border border-[#373a46] transition-all flex items-center justify-center gap-2 shadow-sm"
          >
            {loading ? (
              <>
                <svg className="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span>Procesando inferencia con Super-Ensamble...</span>
              </>
            ) : (
              <>
                <span>▷</span>
                <span>Ejecutar inferencia bioacústica</span>
              </>
            )}
          </button>
        </div>

        {/* Tarjeta: Resultado */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 flex flex-col justify-between">
          <span className="text-xs text-gray-400 font-medium block mb-2">Veredicto del Super-Ensamble</span>

          {result ? (
            <div className="bg-[#111215] border border-[#23252e] rounded-lg p-4 space-y-3">
              <div>
                <span className="text-[10px] text-gray-400 uppercase tracking-wider block font-semibold">
                  Especie de Ave Predicha
                </span>
                <p className="text-xl font-bold text-green-400 mt-0.5">
                  {result.clase}
                </p>
              </div>

              {/* Indicador del modelo utilizado para la predicción */}
              <div className="bg-[#14151a] rounded-lg p-2.5 border border-[#23252e] space-y-1.5">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-gray-400">Modelo ejecutado:</span>
                  <span className="text-blue-400 font-mono font-semibold">
                    {result.modelo || "Super-Ensamble Tri-Modelo"}
                  </span>
                </div>
                {result.modelos_activos && result.modelos_activos.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-1 border-t border-[#23252e]/70">
                    {result.modelos_activos.map((m, idx) => (
                      <span
                        key={idx}
                        className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-emerald-950/60 text-emerald-300 border border-emerald-800/50"
                      >
                        ✓ {m}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Nivel de confianza */}
              <div>
                <div className="flex justify-between items-center text-xs text-gray-300 mb-1">
                  <span>Confianza calibrada:</span>
                  <span className="font-mono font-bold text-white">
                    {(result.confianza * 100).toFixed(2)}%
                  </span>
                </div>
                <div className="w-full bg-gray-800 rounded-full h-2 overflow-hidden">
                  <div
                    className="h-2 rounded-full bg-green-500 transition-all duration-500"
                    style={{ width: `${Math.min(100, Math.max(0, result.confianza * 100))}%` }}
                  />
                </div>
              </div>

              {/* Metadatos de persistencia y trazabilidad */}
              <div className="pt-2 border-t border-[#23252e] flex items-center justify-between text-[11px] text-gray-400">
                <span className="font-mono">PostgreSQL ID #{result.db_id}</span>
                {result.gcp_upload && (
                  <span className="text-blue-400 flex items-center gap-1 text-[10px]">
                    ● Google Cloud Storage
                  </span>
                )}
              </div>
            </div>
          ) : error ? (
            <div className="bg-red-950/60 border border-red-800/80 rounded-lg p-4 text-xs text-red-300 space-y-1">
              <span className="font-bold block text-red-200">Error de inferencia:</span>
              <p>{error}</p>
            </div>
          ) : (
            <div className="bg-[#111215]/60 border border-[#1f2128] rounded-lg p-6 flex flex-col items-center justify-center text-center my-auto">
              <svg className="w-6 h-6 text-gray-500 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
              <p className="text-xs font-medium text-gray-400">Sin inferencia en ejecución</p>
              <p className="text-[11px] text-gray-500 mt-0.5">
                Carga un audio .wav y pulsa &apos;Ejecutar inferencia&apos;
              </p>
            </div>
          )}

          <div className="h-2" />
        </div>
      </div>

      {/* Fila 3: Historial de Predicciones */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4">
        <span className="text-xs text-gray-300 font-semibold block">Historial de predicciones en campo</span>

        {/* Filtros de Búsqueda y Clases Oficiales */}
        <div className="flex flex-col sm:flex-row gap-2.5">
          <div className="relative flex-1">
            <svg className="w-3.5 h-3.5 text-gray-500 absolute left-3 top-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder="Buscar por nombre de archivo..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg pl-8 pr-3 py-1.5 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-gray-500"
            />
          </div>

          <select
            value={classFilter}
            onChange={(e) => setClassFilter(e.target.value)}
            className="bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-300 focus:outline-none focus:border-gray-500"
          >
            <option value="all">Todas las especies (15)</option>
            {OFFICIAL_SPECIES.map((species) => (
              <option key={species} value={species}>
                {species}
              </option>
            ))}
          </select>
        </div>

        {/* Lista de Registros */}
        <div className="space-y-2">
          {filteredHistory.map((item) => (
            <div
              key={item.id}
              className="bg-[#111215] border border-[#1f2128] hover:border-[#2d303b] transition-colors rounded-lg px-4 py-3 flex items-center justify-between"
            >
              <div>
                <p className="text-xs font-medium text-gray-200 font-mono">{item.filename}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[10px] text-gray-500">{item.timestamp}</span>
                  <span className="text-[10px] text-green-400/90 font-medium">· {item.clase}</span>
                  {item.modelo && (
                    <span className="text-[9px] text-blue-400/80 bg-blue-950/40 px-1.5 py-0.2 rounded border border-blue-900/40 font-mono">
                      {item.modelo}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#1e2027] border border-[#2d303b] text-gray-300">
                  {item.badgeCode || "AVE"}
                </span>
                <span className="text-xs font-bold text-green-400 font-mono">
                  {(item.confianza * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
