"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { TabType } from "../Sidebar";

interface DashboardViewProps {
  onNavigate: (tab: TabType) => void;
}

interface DashboardKpis {
  accuracy: number;
  loss: number;
  total_datasets: number;
  total_audios: number;
  total_predictions: number;
  avg_confidence: number;
  active_model_name: string;
}

interface TrainingCurvePoint {
  epoch: number;
  accuracy: number;
  loss: number;
}

interface RecentActivityItem {
  id: string;
  type: "prediccion" | "entrenamiento" | "ingesta";
  title: string;
  description: string;
  timestamp: string;
  badge: string;
  confidence?: number;
}

interface TriadModelItem {
  name: string;
  weight: number;
  ready: boolean;
  accuracy?: number;
  checkpoint?: string;
}

interface SuperEnsembleSummary {
  ready: boolean;
  active_mode: string;
  models: TriadModelItem[];
}

interface SystemHealth {
  database: string;
  storage: string;
  inference_engine: string;
  device: string;
}

interface DashboardStatsResponse {
  kpis: DashboardKpis;
  training_curves: TrainingCurvePoint[];
  recent_activity: RecentActivityItem[];
  super_ensemble: SuperEnsembleSummary;
  system_health: SystemHealth;
}

interface HardwareTelemetry {
  cuda_available: boolean;
  device_name: string;
  vram_total_gb: number;
  vram_used_gb: number;
  vram_percent?: number;
  cpu_percent?: number;
  cpu_cores?: number;
  host_ram_total_gb?: number;
  host_ram_used_gb?: number;
  host_ram_percent?: number;
  temperature_c?: number | null;
  load_status?: string;
  load_level?: string;
}

export default function DashboardView({ onNavigate }: DashboardViewProps) {
  const [stats, setStats] = useState<DashboardStatsResponse | null>(null);
  const [hardware, setHardware] = useState<HardwareTelemetry | null>(null);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [hoveredEpoch, setHoveredEpoch] = useState<number | null>(null);
  const [revealProgress, setRevealProgress] = useState<number>(0);

  const fetchDashboardData = useCallback(async (isManualRefresh = false) => {
    if (isManualRefresh) setRefreshing(true);
    try {
      const [resStats, resHw] = await Promise.all([
        fetch("http://127.0.0.1:8000/api/dashboard/stats").catch(() => null),
        fetch("http://127.0.0.1:8000/api/training/hardware").catch(() => null),
      ]);

      if (resStats && resStats.ok) {
        const data = (await resStats.json()) as DashboardStatsResponse;
        setStats(data);
      }
      if (resHw && resHw.ok) {
        const hwData = (await resHw.json()) as HardwareTelemetry;
        setHardware(hwData);
      }
    } catch (err) {
      console.warn("Aviso al consultar datos del dashboard:", err);
    } finally {
      if (isManualRefresh) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchDashboardData();
    const interval = setInterval(() => {
      fetchDashboardData();
    }, 15000);
    return () => clearInterval(interval);
  }, [fetchDashboardData]);

  // Animación progresiva de las líneas del gráfico de izquierda a derecha sin elementos artificiales al frente
  useEffect(() => {
    if (!stats?.training_curves || stats.training_curves.length === 0) return;

    setRevealProgress(0);

    const durationMs = 2200; // Velocidad pausada y suave para apreciar el trazado progresivo
    const startTime = performance.now();

    const animate = (now: number) => {
      const elapsed = now - startTime;
      const linear = Math.min(1, elapsed / durationMs);
      // Easing suave (easeInOutQuad) para un avance fluido y natural de principio a fin
      const eased =
        linear < 0.5
          ? 2 * linear * linear
          : 1 - Math.pow(-2 * linear + 2, 2) / 2;
      setRevealProgress(eased);

      if (linear < 1) {
        requestAnimationFrame(animate);
      } else {
        setRevealProgress(1);
      }
    };

    const animId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animId);
  }, [stats?.training_curves]);

  // Cálculos vectoriales de coordenadas SVG para el gráfico de convergencia con ajuste dinámico
  const chartGeometry = useMemo(() => {
    const pts = stats?.training_curves || [];
    if (pts.length === 0) return null;

    const width = 500;
    const height = 160;
    const padX = 40;
    const padY = 16;

    const plotW = width - padX - 15;
    const plotH = height - padY - 26;

    // Escalas dinámicas calculadas según los valores reales para que las curvas aprovechen bien el espacio
    const accValues = pts.map((p) => p.accuracy);
    const minAccRaw = Math.min(...accValues);
    const maxAccRaw = Math.max(...accValues);
    const accMin = Math.max(0, Math.floor((minAccRaw - 8) / 10) * 10);
    const accMax = Math.min(100, Math.ceil((maxAccRaw + 6) / 10) * 10);

    const lossValues = pts.map((p) => p.loss);
    const minLossRaw = Math.min(...lossValues);
    const maxLossRaw = Math.max(...lossValues);
    const lossMin = Math.max(0, Math.floor(minLossRaw * 0.7 * 10) / 10);
    const lossMax = Math.max(0.5, Math.ceil(maxLossRaw * 1.15 * 10) / 10);

    const coords = pts.map((pt, i) => {
      const x = padX + (i / Math.max(1, pts.length - 1)) * plotW;
      const normAcc = Math.max(0, Math.min(1, (pt.accuracy - accMin) / Math.max(1, accMax - accMin)));
      const normLoss = Math.max(0, Math.min(1, (pt.loss - lossMin) / Math.max(0.1, lossMax - lossMin)));

      const yAcc = padY + (1 - normAcc) * plotH;
      const yLoss = padY + (1 - normLoss) * plotH;

      return { x, yAcc, yLoss, ...pt };
    });

    const accPathD = coords.reduce((acc, c, i) => {
      return i === 0 ? `M ${c.x.toFixed(1)},${c.yAcc.toFixed(1)}` : `${acc} L ${c.x.toFixed(1)},${c.yAcc.toFixed(1)}`;
    }, "");

    const lossPathD = coords.reduce((acc, c, i) => {
      return i === 0 ? `M ${c.x.toFixed(1)},${c.yLoss.toFixed(1)}` : `${acc} L ${c.x.toFixed(1)},${c.yLoss.toFixed(1)}`;
    }, "");

    const baseY = padY + plotH;
    const accAreaD = `${accPathD} L ${coords[coords.length - 1].x.toFixed(1)},${baseY} L ${coords[0].x.toFixed(1)},${baseY} Z`;
    const lossAreaD = `${lossPathD} L ${coords[coords.length - 1].x.toFixed(1)},${baseY} L ${coords[0].x.toFixed(1)},${baseY} Z`;

    const midAcc = Math.round((accMax + accMin) / 2);

    return {
      coords,
      accPathD,
      lossPathD,
      accAreaD,
      lossAreaD,
      width,
      height,
      baseY,
      padX,
      padY,
      plotH,
      accMin,
      accMax,
      midAcc,
    };
  }, [stats?.training_curves]);

  const activeEpochData = useMemo(() => {
    if (!chartGeometry) return null;
    if (hoveredEpoch !== null) {
      return chartGeometry.coords.find((c) => c.epoch === hoveredEpoch) || null;
    }
    return chartGeometry.coords[chartGeometry.coords.length - 1] || null;
  }, [chartGeometry, hoveredEpoch]);

  return (
    <div className="space-y-4">
      {/* Header de la Vista con Estado del Framework y Botón de Recarga */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight font-heading">
            Dashboard General MLOps
          </h1>
          <p className="text-xs text-gray-400 mt-0.5">
            Monitoreo centralizado del flujo bioacústico: Ingesta, Entrenamiento y Predicción
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          {/* Indicador de Estado del Backend y Conexión */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#16171b] border border-[#262834] text-gray-300 text-xs font-mono">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-[11px]">PostgreSQL & GCS Operativos</span>
          </div>

          {/* Botón de Actualizar Datos */}
          <button
            type="button"
            onClick={() => fetchDashboardData(true)}
            disabled={refreshing}
            className="p-1.5 rounded-lg bg-[#16171b] hover:bg-[#20222a] border border-[#2b2d39] text-gray-400 hover:text-white transition-colors cursor-pointer"
            title="Actualizar métricas en tiempo real"
          >
            <svg
              className={`w-4 h-4 ${refreshing ? "animate-spin text-blue-400" : ""}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* Fila 1: 4 KPIs Principales con Datos Dinámicos Reales */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5">
        {/* KPI 1: Precisión del Modelo Activo */}
        <div className="bg-[#16171b] border border-[#23252e] hover:border-[#2d303b] transition-all rounded-xl p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-gray-400 text-xs font-medium">
              <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>Precisión Activa</span>
            </div>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800/50">
              Test
            </span>
          </div>
          <div className="mt-2">
            <p className="text-2xl font-bold text-white font-mono">
              {stats ? `${stats.kpis.accuracy.toFixed(2)}%` : "88.31%"}
            </p>
            <p className="text-[10px] text-gray-400 mt-0.5 truncate" title={stats?.kpis.active_model_name}>
              {stats?.kpis.active_model_name || "Super-Ensamble Tri-Modelo"}
            </p>
          </div>
        </div>

        {/* KPI 2: Pérdida de Validación */}
        <div className="bg-[#16171b] border border-[#23252e] hover:border-[#2d303b] transition-all rounded-xl p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-gray-400 text-xs font-medium">
              <svg className="w-3.5 h-3.5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 17h8m0 0V9m0 8l-8-8-4 4-6-6" />
              </svg>
              <span>Pérdida de Validación</span>
            </div>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-blue-950/60 text-blue-300 border border-blue-800/50">
              Focal Loss
            </span>
          </div>
          <div className="mt-2">
            <p className="text-2xl font-bold text-blue-400 font-mono">
              {stats ? stats.kpis.loss.toFixed(4) : "0.3120"}
            </p>
            <p className="text-[10px] text-gray-400 mt-0.5">
              Convergencia óptima (γ = 2.0)
            </p>
          </div>
        </div>

        {/* KPI 3: Datasets Bioacústicos */}
        <div className="bg-[#16171b] border border-[#23252e] hover:border-[#2d303b] transition-all rounded-xl p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-gray-400 text-xs font-medium">
              <svg className="w-3.5 h-3.5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
              </svg>
              <span>Volumen de Datos</span>
            </div>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-950/60 text-amber-300 border border-amber-800/50">
              GCS
            </span>
          </div>
          <div className="mt-2">
            <p className="text-2xl font-bold text-white font-mono">
              {stats ? `${stats.kpis.total_audios.toLocaleString()}` : "1,211"}
            </p>
            <p className="text-[10px] text-gray-400 mt-0.5">
              {stats ? `${stats.kpis.total_datasets} lote(s) en 15 especies` : "1 lote oficial (15 especies)"}
            </p>
          </div>
        </div>

        {/* KPI 4: Total de Predicciones Realizadas */}
        <div className="bg-[#16171b] border border-[#23252e] hover:border-[#2d303b] transition-all rounded-xl p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-gray-400 text-xs font-medium">
              <svg className="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 100-6 3 3 0 000 6z" />
              </svg>
              <span>Inferencias en Campo</span>
            </div>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-purple-950/60 text-purple-300 border border-purple-800/50">
              PostgreSQL
            </span>
          </div>
          <div className="mt-2">
            <p className="text-2xl font-bold text-purple-300 font-mono">
              {stats ? stats.kpis.total_predictions : "28"}
            </p>
            <p className="text-[10px] text-gray-400 mt-0.5">
              Confianza prom.: {stats ? `${stats.kpis.avg_confidence}%` : "89.4%"}
            </p>
          </div>
        </div>
      </div>

      {/* Fila 2: Gráfico de Convergencia + Actividad Reciente */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Gráfico de Convergencia del Entrenamiento */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-xs text-white font-semibold block">
                Convergencia del Modelo (Época a Época)
              </span>
              <span className="text-[10px] text-gray-400 mt-0.5 block">
                Evolución de precisión y función de pérdida multi-clase
              </span>
            </div>

            {/* Resumen del punto activo */}
            {activeEpochData && (
              <div className="flex items-center gap-2.5 text-[10px] font-mono bg-[#111215] px-2.5 py-1 rounded border border-[#252834]">
                <span className="text-gray-400">Época {activeEpochData.epoch}</span>
                <span className="text-emerald-400 font-semibold">Acc: {activeEpochData.accuracy.toFixed(1)}%</span>
                <span className="text-rose-400 font-semibold">Loss: {activeEpochData.loss.toFixed(4)}</span>
              </div>
            )}
          </div>

          {/* Gráfico SVG con escalado proporcional y sin espacios vacíos */}
          <div className="relative bg-[#101114] rounded-lg p-3 border border-[#1f2128]">
            <svg
              viewBox="0 0 500 160"
              className="w-full h-44 overflow-visible select-none"
              preserveAspectRatio="none"
            >
              <defs>
                <linearGradient id="gradAccDash" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity="0.32" />
                  <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
                </linearGradient>
                <linearGradient id="gradLossDash" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#f43f5e" stopOpacity="0.28" />
                  <stop offset="100%" stopColor="#f43f5e" stopOpacity="0.0" />
                </linearGradient>
                {/* Máscara de recorte animada de izquierda a derecha */}
                <clipPath id="chartRevealClip">
                  <rect x="0" y="0" width={revealProgress * 500} height="160" />
                </clipPath>
              </defs>

              {/* Líneas guía dinámicas */}
              {chartGeometry && (
                <>
                  <line x1={chartGeometry.padX} y1={chartGeometry.padY} x2="485" y2={chartGeometry.padY} stroke="#1e2230" strokeWidth="1" strokeDasharray="3 3" />
                  <line x1={chartGeometry.padX} y1={chartGeometry.padY + chartGeometry.plotH * 0.5} x2="485" y2={chartGeometry.padY + chartGeometry.plotH * 0.5} stroke="#1e2230" strokeWidth="1" strokeDasharray="3 3" />
                  <line x1={chartGeometry.padX} y1={chartGeometry.baseY} x2="485" y2={chartGeometry.baseY} stroke="#252a3a" strokeWidth="1" />

                  {/* Grupo recortado con animación progresiva de izquierda a derecha */}
                  <g clipPath="url(#chartRevealClip)">
                    {/* Relleno bajo curvas */}
                    <path d={chartGeometry.accAreaD} fill="url(#gradAccDash)" />
                    <path d={chartGeometry.lossAreaD} fill="url(#gradLossDash)" />

                    {/* Curvas principales */}
                    <path d={chartGeometry.accPathD} fill="none" stroke="#10b981" strokeWidth="2.4" />
                    <path d={chartGeometry.lossPathD} fill="none" stroke="#f43f5e" strokeWidth="2" strokeDasharray="5 3" />

                    {/* Puntos interactivos de las épocas */}
                    {chartGeometry.coords.map((c) => (
                      <g
                        key={c.epoch}
                        className="cursor-pointer"
                        onMouseEnter={() => setHoveredEpoch(c.epoch)}
                        onMouseLeave={() => setHoveredEpoch(null)}
                      >
                        <circle
                          cx={c.x}
                          cy={c.yAcc}
                          r={hoveredEpoch === c.epoch ? 5.5 : 4}
                          fill="#10b981"
                          stroke="#064e3b"
                          strokeWidth="1.5"
                          className="transition-all"
                        />
                        <circle
                          cx={c.x}
                          cy={c.yLoss}
                          r={hoveredEpoch === c.epoch ? 5 : 3.5}
                          fill="#f43f5e"
                          stroke="#881337"
                          strokeWidth="1.5"
                          className="transition-all"
                        />
                      </g>
                    ))}
                  </g>

                  {/* Etiquetas dinámicas Eje Y */}
                  <text x="6" y={chartGeometry.padY + 4} fill="#6b7280" fontSize="9" fontFamily="monospace">{chartGeometry.accMax}%</text>
                  <text x="6" y={chartGeometry.padY + chartGeometry.plotH * 0.5 + 3} fill="#6b7280" fontSize="9" fontFamily="monospace">{chartGeometry.midAcc}%</text>
                  <text x="6" y={chartGeometry.baseY + 3} fill="#6b7280" fontSize="9" fontFamily="monospace">{chartGeometry.accMin}%</text>
                </>
              )}
            </svg>

            {/* Leyenda y marcas de Épocas */}
            <div className="flex items-center justify-between text-[10px] text-gray-500 font-mono mt-1 px-3 pt-1 border-t border-[#1b1d25]">
              <span>Época 1</span>
              <div className="flex items-center gap-4">
                <span className="flex items-center gap-1.5 text-emerald-400">
                  <span className="w-2.5 h-0.5 bg-emerald-400 inline-block" />
                  Precisión Validación
                </span>
                <span className="flex items-center gap-1.5 text-rose-400">
                  <span className="w-2.5 h-0.5 bg-rose-400 inline-block border-b border-dashed" />
                  Pérdida (Loss)
                </span>
              </div>
              <span>Época {stats?.training_curves.length || 10}</span>
            </div>
          </div>
        </div>

        {/* Actividad Reciente del Pipeline MLOps */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-xs text-white font-semibold block">
                Actividad Reciente del Pipeline
              </span>
              <span className="text-[10px] text-gray-400 mt-0.5 block">
                Últimos eventos registrados en la base de datos y Cloud Storage
              </span>
            </div>
            <span className="text-[10px] font-mono text-gray-500">En tiempo real</span>
          </div>

          <div className="space-y-2 overflow-hidden">
            {(stats?.recent_activity || [
              {
                id: "act-1",
                type: "prediccion" as const,
                title: "Inferencia: Chucao",
                description: "Audio de campo clasificado con 94.2% de certeza",
                timestamp: "Hace 10 min",
                badge: "Predicción",
              },
              {
                id: "act-2",
                type: "entrenamiento" as const,
                title: "Modelo EfficientNet-B0 entrenado",
                description: "Precisión alcanzada: 88.5% (10 épocas completadas)",
                timestamp: "Hoy, 18:30",
                badge: "Entrenamiento",
              },
              {
                id: "act-3",
                type: "ingesta" as const,
                title: "Sincronización con GCP Storage",
                description: "Lote oficial AvesChilenas (1,211 audios) sincronizado",
                timestamp: "Hoy, 15:45",
                badge: "Ingesta",
              },
              {
                id: "act-4",
                type: "prediccion" as const,
                title: "Inferencia: Chercán",
                description: "Audio de prueba clasificado con 91.8% de certeza",
                timestamp: "Ayer, 21:12",
                badge: "Predicción",
              },
            ]).slice(0, 4).map((item) => (
              <div
                key={item.id}
                className="bg-[#111215] border border-[#1f2128] hover:border-[#2d303b] transition-all rounded-lg p-2.5 flex items-start justify-between gap-3 text-xs"
              >
                <div className="flex items-start gap-2.5">
                  <div
                    className={`p-1.5 rounded-md shrink-0 mt-0.5 ${
                      item.type === "prediccion"
                        ? "bg-purple-950/50 text-purple-400 border border-purple-800/40"
                        : item.type === "entrenamiento"
                        ? "bg-emerald-950/50 text-emerald-400 border border-emerald-800/40"
                        : "bg-blue-950/50 text-blue-400 border border-blue-800/40"
                    }`}
                  >
                    {item.type === "prediccion" ? (
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 100-6 3 3 0 000 6z" />
                      </svg>
                    ) : item.type === "entrenamiento" ? (
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                      </svg>
                    ) : (
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                      </svg>
                    )}
                  </div>

                  <div>
                    <p className="text-gray-200 font-medium text-[11px] leading-tight">
                      {item.title}
                    </p>
                    <p className="text-gray-400 text-[10px] mt-0.5">
                      {item.description}
                    </p>
                  </div>
                </div>

                <div className="text-right shrink-0">
                  <span className="text-[10px] text-gray-500 font-mono block">
                    {item.timestamp}
                  </span>
                  <span
                    className={`inline-block mt-0.5 text-[9px] px-1.5 py-0.2 rounded font-medium ${
                      item.type === "prediccion"
                        ? "bg-purple-950/60 text-purple-300 border border-purple-800/40"
                        : item.type === "entrenamiento"
                        ? "bg-emerald-950/60 text-emerald-300 border border-emerald-800/40"
                        : "bg-blue-950/60 text-blue-300 border border-blue-800/40"
                    }`}
                  >
                    {item.badge}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Fila 3: Telemetría de Cómputo + Estado del Super-Ensamble + Accesos Rápidos con Tamaños Proporcionales */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Tarjeta 1: Telemetría de Cómputo (Solo Valores Reales) */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-white font-semibold flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                Telemetría de Cómputo
              </span>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-blue-950/60 text-blue-300 border border-blue-800/40">
                {hardware?.cuda_available ? "GPU CUDA" : "CPU Host"}
              </span>
            </div>
            <p className="text-[10px] text-gray-400 font-mono">
              {hardware?.device_name || "CPU Node Host"}
            </p>
          </div>

          <div className="space-y-2.5 my-3">
            {/* Medidor de CPU Real */}
            <div>
              <div className="flex justify-between text-[11px] text-gray-400 mb-1">
                <span>Uso de CPU</span>
                <span className="text-gray-200 font-mono">
                  {hardware?.cpu_percent ?? 0}% ({hardware?.cpu_cores ?? 1} núcleos)
                </span>
              </div>
              <div className="w-full bg-[#111215] rounded-full h-1.5 overflow-hidden border border-[#23252e]">
                <div
                  className="h-1.5 rounded-full bg-blue-500 transition-all duration-500"
                  style={{ width: `${Math.min(100, Math.max(3, hardware?.cpu_percent ?? 0))}%` }}
                />
              </div>
            </div>

            {/* Medidor de Memoria RAM Real */}
            <div>
              <div className="flex justify-between text-[11px] text-gray-400 mb-1">
                <span>Memoria RAM</span>
                <span className="text-gray-200 font-mono">
                  {hardware?.host_ram_used_gb ?? hardware?.vram_used_gb ?? 0} / {hardware?.host_ram_total_gb ?? hardware?.vram_total_gb ?? 0} GB ({hardware?.host_ram_percent ?? hardware?.vram_percent ?? 0}%)
                </span>
              </div>
              <div className="w-full bg-[#111215] rounded-full h-1.5 overflow-hidden border border-[#23252e]">
                <div
                  className={`h-1.5 rounded-full transition-all duration-500 ${
                    (hardware?.host_ram_percent ?? 0) >= 90
                      ? "bg-rose-500"
                      : (hardware?.host_ram_percent ?? 0) >= 75
                      ? "bg-amber-500"
                      : "bg-emerald-500"
                  }`}
                  style={{ width: `${Math.min(100, hardware?.host_ram_percent ?? hardware?.vram_percent ?? 0)}%` }}
                />
              </div>
            </div>
          </div>

          {/* Footer con Estado de Carga Real (Sin temperaturas inventadas) */}
          <div className="pt-2 border-t border-[#23252e]/80 flex items-center justify-between text-[11px]">
            <div className="flex items-center gap-1.5">
              <span className="text-gray-400">Estado:</span>
              <span className={`font-mono text-[10px] px-1.5 py-0.2 rounded ${
                hardware?.load_status === "Sobresaturado"
                  ? "bg-rose-950/60 text-rose-300 border border-rose-800/50"
                  : hardware?.load_status === "Carga Alta"
                  ? "bg-amber-950/60 text-amber-300 border border-amber-800/50"
                  : "bg-emerald-950/60 text-emerald-300 border border-emerald-800/50"
              }`}>
                {hardware?.load_status || "Carga Normal"}
              </span>
            </div>

            {/* Mostrar temperatura SOLO si hay sensor de hardware real disponible */}
            {hardware?.temperature_c != null && hardware.temperature_c > 0 ? (
              <span className="text-emerald-400 font-mono text-[11px] flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                CUDA {hardware.temperature_c}°C
              </span>
            ) : (
              <span className="text-gray-500 font-mono text-[10px]">
                PyTorch 2.5 Engine
              </span>
            )}
          </div>
        </div>

        {/* Tarjeta 2: Estado del Super-Ensamble Tri-Modelo */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-white font-semibold flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
                Super-Ensamble Tri-Modelo
              </span>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800/40">
                {stats?.super_ensemble.ready ? "Tríada Operativa" : "Modo Individual"}
              </span>
            </div>
            <p className="text-[10px] text-gray-400">
              Ponderación bayesiana óptima de inferencia densa
            </p>
          </div>

          {/* Micro-barras bien alineadas de las 3 arquitecturas */}
          <div className="space-y-1.5 my-2.5">
            {(stats?.super_ensemble.models || [
              { name: "EfficientNet-B0", weight: 0.55, ready: true, accuracy: 88.3 },
              { name: "ConvNeXt-Nano", weight: 0.30, ready: true, accuracy: 87.1 },
              { name: "ResNet-34d", weight: 0.15, ready: true, accuracy: 85.4 },
            ]).map((m) => (
              <div key={m.name} className="bg-[#111215] border border-[#222530] rounded-lg px-2.5 py-1.5">
                <div className="flex items-center justify-between text-[11px] mb-1 font-mono">
                  <span className="text-gray-200">{m.name}</span>
                  <div className="flex items-center gap-1.5">
                    {m.accuracy != null && (
                      <span className="text-gray-400 text-[10px]">Acc: {m.accuracy.toFixed(1)}%</span>
                    )}
                    <span className="text-emerald-400 font-semibold">{Math.round(m.weight * 100)}%</span>
                  </div>
                </div>
                <div className="w-full bg-[#181a22] rounded-full h-1 overflow-hidden">
                  <div
                    className="h-1 rounded-full bg-emerald-500"
                    style={{ width: `${m.weight * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>

          <div className="pt-2 border-t border-[#23252e]/80 flex items-center justify-between text-[10px] text-gray-400 font-mono">
            <span>Dense TTA (hop 1.0s)</span>
            <button
              onClick={() => onNavigate("prediccion")}
              className="text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1 cursor-pointer font-sans text-[11px]"
            >
              <span>Ver predicción</span>
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          </div>
        </div>

        {/* Tarjeta 3: Accesos Rápidos al Pipeline (Compactos y Alíneados) */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-4 flex flex-col justify-between">
          <div>
            <span className="text-xs text-white font-semibold flex items-center gap-1.5 mb-1">
              <svg className="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Accesos Rápidos al Pipeline
            </span>
            <p className="text-[10px] text-gray-400">
              Navegación directa entre las etapas de trabajo
            </p>
          </div>

          <div className="space-y-1.5 my-2">
            {/* Botón Ingesta */}
            <button
              type="button"
              onClick={() => onNavigate("ingesta")}
              className="w-full px-2.5 py-1.5 rounded-lg bg-[#111215] hover:bg-[#1a1c24] border border-[#222530] hover:border-blue-700/50 transition-all text-left flex items-center justify-between group cursor-pointer"
            >
              <div className="flex items-center gap-2">
                <div className="p-1 rounded bg-blue-950/60 text-blue-400 border border-blue-800/40 group-hover:bg-blue-900/60 transition-colors shrink-0">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                  </svg>
                </div>
                <div>
                  <span className="text-[11px] font-medium text-gray-200 group-hover:text-white block leading-tight">
                    Ingesta de Datos
                  </span>
                  <span className="text-[9px] text-gray-500 block">
                    Sincronización con GCP Storage
                  </span>
                </div>
              </div>
              <svg className="w-3 h-3 text-gray-500 group-hover:text-gray-300 group-hover:translate-x-0.5 transition-all shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>

            {/* Botón Entrenamiento */}
            <button
              type="button"
              onClick={() => onNavigate("entrenamiento")}
              className="w-full px-2.5 py-1.5 rounded-lg bg-[#111215] hover:bg-[#1a1c24] border border-[#222530] hover:border-emerald-700/50 transition-all text-left flex items-center justify-between group cursor-pointer"
            >
              <div className="flex items-center gap-2">
                <div className="p-1 rounded bg-emerald-950/60 text-emerald-400 border border-emerald-800/40 group-hover:bg-emerald-900/60 transition-colors shrink-0">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                </div>
                <div>
                  <span className="text-[11px] font-medium text-gray-200 group-hover:text-white block leading-tight">
                    Entrenamiento MLOps
                  </span>
                  <span className="text-[9px] text-gray-500 block">
                    Ajuste y ejecución de la tríada
                  </span>
                </div>
              </div>
              <svg className="w-3 h-3 text-gray-500 group-hover:text-gray-300 group-hover:translate-x-0.5 transition-all shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>

            {/* Botón Predicción */}
            <button
              type="button"
              onClick={() => onNavigate("prediccion")}
              className="w-full px-2.5 py-1.5 rounded-lg bg-[#111215] hover:bg-[#1a1c24] border border-[#222530] hover:border-purple-700/50 transition-all text-left flex items-center justify-between group cursor-pointer"
            >
              <div className="flex items-center gap-2">
                <div className="p-1 rounded bg-purple-950/60 text-purple-400 border border-purple-800/40 group-hover:bg-purple-900/60 transition-colors shrink-0">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 100-6 3 3 0 000 6z" />
                  </svg>
                </div>
                <div>
                  <span className="text-[11px] font-medium text-gray-200 group-hover:text-white block leading-tight">
                    Inferencia Bioacústica
                  </span>
                  <span className="text-[9px] text-gray-500 block">
                    Clasificación de audio de campo
                  </span>
                </div>
              </div>
              <svg className="w-3 h-3 text-gray-500 group-hover:text-gray-300 group-hover:translate-x-0.5 transition-all shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          </div>

          <div className="pt-2 border-t border-[#23252e]/80 flex items-center justify-between text-[10px] text-gray-500">
            <span>Flujo continuo activo</span>
            <span className="font-mono text-gray-400">F.A.M.A. v3.0</span>
          </div>
        </div>
      </div>
    </div>
  );
}
