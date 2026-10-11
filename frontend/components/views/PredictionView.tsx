"use client";

import { useState, useEffect, useMemo, useRef, useCallback, ChangeEvent, FormEvent } from "react";
import { API_BASE_URL } from "@/lib/api";
import { ApiConnectionError, sendFeedback } from "@/lib/api/feedbackApi";

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
  detalles?: { dataset_name?: string | null } | null;
  filename: string;
  gcp_upload: boolean;
  db_id?: number | null;
  clase: string;
  confianza: number;
  modelo?: string;
  modelo_id?: string;
  is_fallback?: boolean;
  modelos_activos?: string[];
}

interface HistoryItem {
  id: number | null;
  filename: string;
  timestamp: string;
  clase: string;

  confianza: number;
  modelo?: string;
  domain?: string;
}

export interface ModelEvaluationMetrics {
  accuracy?: number | null;
  f1_macro?: number | null;
  precision_macro?: number | null;
  ece?: number | null;
  [key: string]: number | string | boolean | null | undefined;
}

interface EvaluationProvenance {
  schema_version?: number;
  evaluator_version?: string;
  checkpoint_sha256?: string;
  dataset?: string;
  split?: "val" | "test";
  sample_count?: number;
}

interface FinalEvaluationReport {
  schema_version?: unknown;
  sample_count?: unknown;
  metrics?: Record<string, unknown> | null;
  coverage?: { complete?: unknown; absent_classes?: unknown } | null;
  rejection?: { count?: unknown; rate?: unknown } | null;
}

interface EvaluationAttempt {
  id_evaluation?: unknown;
  status?: unknown;
  created_at?: unknown;
  started_at?: unknown;
  finished_at?: unknown;
  provenance?: EvaluationProvenance | null;
}

interface CompletedEvaluation {
  id_evaluation?: unknown;
  report?: FinalEvaluationReport | null;
  provenance?: EvaluationProvenance | null;
  created_at?: unknown;
  started_at?: unknown;
  finished_at?: unknown;
}

interface EvaluationSplit {
  latest_attempt?: EvaluationAttempt | null;
  latest_completed?: CompletedEvaluation | null;
}

interface ModelEvaluations {
  val?: EvaluationSplit | null;
  test?: EvaluationSplit | null;
}

export interface RegisteredModel {
  id: string;
  name: string;
  description: string;
  target_sr: number;
  duration_seconds: number;
  classes: string[];
  is_default: boolean;
  has_weights?: boolean;
  metrics?: ModelEvaluationMetrics;
  evaluations?: ModelEvaluations | null;
}

const EVALUATION_STATUS_LABELS: Record<string, string> = {
  pending: "Pendiente",
  running: "En curso",
  completed: "Completado",
  failed: "Fallido",
};

function formatFinalRate(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1
    ? `${(value * 100).toFixed(2)}%`
    : "No disponible";
}

function formatFinalCount(value: unknown): string {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value.toLocaleString("es-CL")
    : "No disponible";
}

function safeTimestamp(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function EvaluationSplitCard({
  label,
  split,
}: {
  label: string;
  split?: EvaluationSplit | null;
}) {
  const latestAttempt = split?.latest_attempt;
  const latestCompleted = split?.latest_completed;
  const report = latestCompleted?.report;
  const metrics = report?.metrics;
  const metricRows = [
    ["Accuracy", metrics?.accuracy],
    ["Precision macro", metrics?.precision_macro],
    ["Recall macro", metrics?.recall_macro],
    ["F1 macro", metrics?.f1_macro],
    ["F1 ponderado", metrics?.f1_weighted],
    ["Balanced accuracy", metrics?.balanced_accuracy],
  ] as const;
  const coverage = report?.coverage;
  const absentClasses = Array.isArray(coverage?.absent_classes)
    ? coverage.absent_classes.filter((value): value is string => typeof value === "string")
    : null;
  const provenance = latestCompleted?.provenance;
  const checkpointHash = typeof provenance?.checkpoint_sha256 === "string" && /^[0-9a-f]{64}$/.test(provenance.checkpoint_sha256)
    ? provenance.checkpoint_sha256
    : null;
  const attemptStatus = typeof latestAttempt?.status === "string"
    ? EVALUATION_STATUS_LABELS[latestAttempt.status] || "Estado no reconocido"
    : "Estado no disponible";
  const attemptId = Number.isSafeInteger(latestAttempt?.id_evaluation) && Number(latestAttempt?.id_evaluation) > 0
    ? Number(latestAttempt?.id_evaluation)
    : null;
  const completedId = Number.isSafeInteger(latestCompleted?.id_evaluation) && Number(latestCompleted?.id_evaluation) > 0
    ? Number(latestCompleted?.id_evaluation)
    : null;
  const rejection = report?.schema_version === 2 ? report.rejection : null;
  const rejectionCount = rejection && Number.isSafeInteger(rejection.count) && Number(rejection.count) >= 0
    ? formatFinalCount(rejection.count)
    : null;
  const rejectionRate = rejection && typeof rejection.rate === "number" && Number.isFinite(rejection.rate) && rejection.rate >= 0 && rejection.rate <= 1
    ? formatFinalRate(rejection.rate)
    : null;

  return (
    <article className="min-w-0 rounded-lg border border-[#252834] bg-[#111215] p-3 space-y-3" aria-label={`Evaluación ${label}`}>
      <h3 className="text-sm font-semibold text-white">{label}</h3>
      {latestAttempt ? (
        <div className="text-xs text-gray-300">
          <p>
            Último intento{attemptId ? ` #${attemptId}` : ""}: <span className="font-semibold">{attemptStatus}</span>
          </p>
          {safeTimestamp(latestAttempt.created_at) && <p className="break-all text-[11px] text-gray-400">Creado: {safeTimestamp(latestAttempt.created_at)}</p>}
          {safeTimestamp(latestAttempt.started_at) && <p className="break-all text-[11px] text-gray-400">Inicio: {safeTimestamp(latestAttempt.started_at)}</p>}
          {safeTimestamp(latestAttempt.finished_at) && <p className="break-all text-[11px] text-gray-400">Finalizado: {safeTimestamp(latestAttempt.finished_at)}</p>}
        </div>
      ) : (
        <p className="text-xs text-gray-400">Sin intentos registrados para este split.</p>
      )}

      {report && latestCompleted ? (
        <div className="space-y-3">
          <p className="text-xs font-semibold text-emerald-300">
            Informe histórico completado{completedId ? ` #${completedId}` : ""}
          </p>
          <p className="text-xs text-gray-300">Muestras: {formatFinalCount(report.sample_count)}</p>
          {safeTimestamp(latestCompleted.created_at) && <p className="break-all text-[11px] text-gray-400">Informe creado: {safeTimestamp(latestCompleted.created_at)}</p>}
          {safeTimestamp(latestCompleted.finished_at) && <p className="break-all text-[11px] text-gray-400">Informe finalizado: {safeTimestamp(latestCompleted.finished_at)}</p>}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[18rem] text-left text-xs" aria-label={`Métricas del informe histórico ${label}`}>
              <thead className="text-gray-400">
                <tr><th scope="col" className="py-1 pr-3">Métrica</th><th scope="col" className="py-1">Valor</th></tr>
              </thead>
              <tbody>
                {metricRows.map(([name, value]) => (
                  <tr key={name} className="border-t border-[#252834]">
                    <th scope="row" className="py-1 pr-3 font-medium text-gray-300">{name}</th>
                    <td className="py-1 font-mono text-white">{formatFinalRate(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-gray-300">
            {coverage?.complete === true
              ? "Cobertura completa"
              : coverage?.complete === false
                ? `Cobertura incompleta${absentClasses?.length ? ` · clases ausentes: ${absentClasses.join(", ")}` : ""}`
                : "Cobertura no disponible"}
          </p>
          {rejectionCount !== null && rejectionRate !== null && (
            <p className="text-xs text-gray-300">Rechazos: {rejectionCount} ({rejectionRate})</p>
          )}
          <dl className="grid grid-cols-1 gap-1 text-[11px] text-gray-400 sm:grid-cols-2">
            <div><dt className="inline">Schema:</dt> <dd className="inline">{typeof provenance?.schema_version === "number" ? provenance.schema_version : "No disponible"}</dd></div>
            <div><dt className="inline">Evaluador:</dt> <dd className="inline">{provenance?.evaluator_version || "No disponible"}</dd></div>
            <div className="break-words"><dt className="inline">Dataset:</dt> <dd className="inline">{provenance?.dataset || "No disponible"}</dd></div>
            {checkpointHash && <div className="break-all"><dt className="inline">SHA-256 del checkpoint:</dt> <dd className="inline font-mono">{checkpointHash}</dd></div>}
          </dl>
          <p className="text-[11px] text-amber-200">Informe histórico; no garantiza correspondencia con los pesos cargados actualmente.</p>
        </div>
      ) : (
        <p className="text-xs text-gray-400">No hay un informe completado para este split.</p>
      )}
    </article>
  );
}

export function resolveModelDomain(
  model?: RegisteredModel,
  modelId?: string
): "engine_diagnostics" | "AvesChilenas" {
  const id = model?.id || modelId || "";
  if (id.includes("engine") || id.includes("motor")) {
    return "engine_diagnostics";
  }
  if (model?.classes && model.classes.some((c) => c in ENGINE_FAULT_LABELS)) {
    return "engine_diagnostics";
  }
  return "AvesChilenas";
}


const ENGINE_FAULT_LABELS: Record<string, string> = {
  bad_ignition: "Falla de Encendido / Combustión Irregular",
  dead_battery: "Batería Agotada (Arranque Lento/Débil)",
  low_oil: "Nivel de Aceite Crítico / Golpeteo de Bielas",
  "no oil_serpentine belt": "Falla Compuesta: Falta Aceite + Correa",
  normal_brakes: "Frenos en Estado Normal",
  normal_engine_idle: "Ralentí Estable sin Anomalías",
  normal_engine_startup: "Arranque de Fábrica Normal",
  "power steering combined_no oil": "Falla Compuesta: Dirección + Falta Aceite",
  "power steering combined_no oil_serpentine belt": "Falla Triple: Dirección + Aceite + Correa",
  "power steering combined_serpentine belt": "Falla Compuesta: Dirección + Correa",
  power_steering: "Bomba de Dirección Hidráulica",
  serpentine_belt: "Correa de Accesorios Chirriante",
  worn_out_brakes: "Desgaste Severo de Pastillas de Freno",
};

interface CurrentPrediction extends PredictionResponse {
  inferenceModel: string;
  inferenceModelId: string;
  modelMismatch: boolean;
  inferenceClasses: string[];
  inferenceDomain: string;
  inferenceEnsemble: boolean;
  sequence: number;
}

function PredictionFeedback({ prediction }: { prediction: CurrentPrediction }) {
  const [choice, setChoice] = useState<boolean | null>(null);
  const [correction, setCorrection] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error" | "finalized">("idle");
  const [message, setMessage] = useState("");
  const sending = useRef(false);
  const validId = typeof prediction.db_id === "number" && Number.isInteger(prediction.db_id) && prediction.db_id > 0;
  const canSubmit = validId && choice !== null && (choice || prediction.inferenceClasses.includes(correction));
  const locked = status === "sending" || status === "sent" || status === "finalized";

  const submit = async () => {
    if (!canSubmit || locked || sending.current) return;
    sending.current = true;
    setStatus("sending");
    setMessage("");
    try {
      await sendFeedback({ id_prediccion: prediction.db_id, fue_correcta: choice, etiqueta_corregida: choice ? null : correction });
      setStatus("sent");
    } catch (err: unknown) {
      const finalized = err instanceof ApiConnectionError && err.statusCode === 409;
      setStatus(finalized ? "finalized" : "error");
      setMessage(finalized
        ? "Conflicto (409): esta predicción ya fue finalizada y no admite nuevos envíos."
        : `No se pudo enviar a revisión: ${err instanceof Error ? err.message : String(err)}. Puedes reintentar sin perder tu selección.`);
    } finally {
      sending.current = false;
    }
  };

  return (
    <section aria-label="Validar resultado" className="pt-3 border-t border-[#23252e] space-y-3 text-xs text-gray-300">
      <h3 className="font-semibold text-white">Validar clase predicha</h3>
      {!validId && <p role="status">Este resultado no tiene un ID de predicción válido. No se puede enviar a revisión.</p>}
      {status === "sent" ? (
        <p role="status" className="text-emerald-400">Enviado a revisión. El audio queda pendiente en Gestión de audios; todavía no se ha incorporado al dataset.</p>
      ) : (
        <>
          <fieldset disabled={locked || !validId} className="space-y-2">
            <legend>¿La clase predicha es correcta?</legend>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                aria-pressed={choice === true}
                disabled={locked || !validId}
                onClick={() => setChoice(true)}
                className={`px-3 py-2 rounded-lg border text-xs font-semibold flex items-center justify-center gap-2 transition-colors focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-emerald-300 disabled:opacity-40 disabled:cursor-not-allowed ${choice === true ? "bg-emerald-600 border-emerald-300 text-white" : "bg-emerald-950/40 border-emerald-800 text-emerald-300 hover:bg-emerald-900/60"}`}
              >
                <svg aria-hidden="true" className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                <span>Correcta</span>
              </button>
              <button
                type="button"
                aria-pressed={choice === false}
                disabled={locked || !validId}
                onClick={() => setChoice(false)}
                className={`px-3 py-2 rounded-lg border text-xs font-semibold flex items-center justify-center gap-2 transition-colors focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-red-300 disabled:opacity-40 disabled:cursor-not-allowed ${choice === false ? "bg-red-600 border-red-300 text-white" : "bg-red-950/40 border-red-800 text-red-300 hover:bg-red-900/60"}`}
              >
                <svg aria-hidden="true" className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
                <span>Incorrecta</span>
              </button>
            </div>
            {choice === false && (prediction.inferenceClasses.length > 0 ? (
              <label className="block space-y-1">
                <span>Clase correcta</span>
                <select value={correction} onChange={(e) => setCorrection(e.target.value)} className="block w-full bg-[#101114] border border-[#2d303b] rounded px-2 py-1.5 text-white">
                  <option value="">Selecciona la clase correcta</option>
                  {prediction.inferenceClasses.map((cls) => <option key={cls} value={cls}>{ENGINE_FAULT_LABELS[cls] || cls}</option>)}
                </select>
              </label>
            ) : <p role="status">Catálogo de clases no disponible para el modelo ejecutado. No es posible corregir la clase; aún puedes confirmar una predicción correcta.</p>)}
          </fieldset>
          {message && <p role="alert" className="text-red-300">{message}</p>}
          <button type="button" onClick={submit} disabled={!canSubmit || locked} className="px-3 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold disabled:opacity-40 disabled:cursor-not-allowed">
            {status === "sending" ? "Enviando a revisión…" : "Enviar a revisión"}
          </button>
        </>
      )}
    </section>
  );
}

export default function PredictionView() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [result, setResult] = useState<CurrentPrediction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [latency, setLatency] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [classFilter, setClassFilter] = useState<string>("all");
  const [modelStatusSnapshot, setModelStatus] = useState<(BackendModelStatus & { requestedDomain: string }) | null>(null);
  const [availableModels, setAvailableModels] = useState<RegisteredModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string>("");
  const [catalogueError, setCatalogueError] = useState<string | null>(null);
  const [evaluationCatalogueStatus, setEvaluationCatalogueStatus] = useState<"available" | "unavailable" | "legacy">("legacy");
  const [evaluationCatalogueErrorCode, setEvaluationCatalogueErrorCode] = useState<string | null>(null);
  const [publicationErrors, setPublicationErrors] = useState<{ model_id?: string; code: string }[]>([]);
  const [audioStats, setAudioStats] = useState<AudioWaveformStats | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [isDecodingAudio, setIsDecodingAudio] = useState<boolean>(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const playheadRef = useRef<SVGGElement | null>(null);
  const timeLabelRef = useRef<HTMLSpanElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const inferenceSequence = useRef(0);

  const selectedModel = useMemo(() => {
    return availableModels.find((m) => m.id === selectedModelId);
  }, [availableModels, selectedModelId]);

  const selectedDomain = useMemo(() => {
    return resolveModelDomain(selectedModel, selectedModelId);
  }, [selectedModel, selectedModelId]);

  const modelStatus = modelStatusSnapshot?.requestedDomain === selectedDomain ? modelStatusSnapshot : null;

  const isEngineModel = useMemo(() => {
    return selectedDomain === "engine_diagnostics";
  }, [selectedDomain]);

  const isEnsemble = useMemo(() => {
    return (selectedModelId || "").toLowerCase().includes("ensemble");
  }, [selectedModelId]);

  const currentClasses = useMemo(() => {
    if (selectedModel?.classes && selectedModel.classes.length > 0) {
      return selectedModel.classes;
    }
    return [];
  }, [selectedModel]);

  const classesCount = currentClasses.length;

  const durationSeconds = selectedModel?.duration_seconds;
  const formattedDuration = durationSeconds != null && durationSeconds > 0 ? `${durationSeconds.toFixed(1)}s` : "duración no publicada";

  const targetSr = selectedModel?.target_sr;
  const formattedSr = targetSr != null && targetSr > 0 ? `${targetSr / 1000} kHz` : "frecuencia no publicada";
  const formattedSrHz = targetSr != null && targetSr > 0 ? `${targetSr.toLocaleString("es-CL")} Hz` : "frecuencia no publicada";

  const formattedMetric = useMemo(() => {
    if (selectedModel?.metrics) {
      if (selectedModel.metrics.f1_macro != null) {
        return `${(Number(selectedModel.metrics.f1_macro) * 100).toFixed(2)}% F1 histórico`;
      }
      if (selectedModel.metrics.accuracy != null) {
        return `${(Number(selectedModel.metrics.accuracy) * 100).toFixed(2)}% Accuracy histórica`;
      }
    }
    return "Sin métricas publicadas";
  }, [selectedModel]);

  const bioModels = useMemo(() => {
    return availableModels.filter((m) => resolveModelDomain(m, m.id) === "AvesChilenas");
  }, [availableModels]);

  const engineModels = useMemo(() => {
    return availableModels.filter((m) => resolveModelDomain(m, m.id) === "engine_diagnostics");
  }, [availableModels]);

  // ODD: Telemetría estructurada al conmutar modelo activo
  useEffect(() => {
    if (selectedModel) {
      console.log(
        `[PredictionView] Modelo activo: ${selectedModel.id} | Dominio: ${selectedDomain} | SR: ${selectedModel.target_sr}Hz | Ventana: ${selectedModel.duration_seconds}s`
      );
    }
  }, [selectedModel, selectedDomain]);


  // Cada entrada o regreso consulta el catálogo; la última solicitud prevalece.
  useEffect(() => {
    let generation = 0;
    let controller: AbortController | undefined;
    let previousModels: RegisteredModel[] = [];
    async function fetchModels() {
      const request = ++generation;
      controller?.abort();
      controller = new AbortController();
      try {
        const res = await fetch(`${API_BASE_URL}/api/models`, { signal: controller.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (request !== generation) return;
        if (!Array.isArray(data.models)) throw new Error("invalid_catalogue");
        setCatalogueError(null);
        setPublicationErrors(Array.isArray(data.publication_errors) ? data.publication_errors : []);
        setEvaluationCatalogueStatus(
          data.evaluation_catalogue_status === "available" || data.evaluation_catalogue_status === "unavailable"
            ? data.evaluation_catalogue_status
            : "legacy"
        );
        setEvaluationCatalogueErrorCode(
          data.evaluation_catalogue_error === "evaluation_store_unavailable" || data.evaluation_catalogue_error === "evaluation_records_invalid"
            ? data.evaluation_catalogue_error
            : null
        );
        const models: RegisteredModel[] = data.models;
        const priorCatalogue = previousModels;
        previousModels = models;
        setAvailableModels(models);
        setSelectedModelId((current) => {
          if (models.some((m) => m.id === current)) return current;
          const defaultModel = models.find((m) => m.id === data.default_model_id);
          const domain = resolveModelDomain(priorCatalogue.find((m) => m.id === current), current);
          const sameDomain = models.filter((m) => resolveModelDomain(m) === domain);
          const replacement = current
            ? sameDomain.find((m) => m.id === defaultModel?.id) || sameDomain[0] || defaultModel || models[0]
            : defaultModel || models[0];
          return replacement?.id || "";
        });
      } catch (err) {
        if (request !== generation) return;
        const status = err instanceof Error && /^HTTP \d{3}$/.test(err.message) ? ` (${err.message})` : "";
        setCatalogueError(`No se pudo actualizar el catálogo de modelos${status}. Se conserva el último catálogo disponible; vuelve a esta ventana para reintentar.`);
      }
    }
    const onVisible = () => { if (document.visibilityState === "visible") void fetchModels(); };
    void fetchModels();
    window.addEventListener("focus", fetchModels);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      generation += 1;
      controller?.abort();
      window.removeEventListener("focus", fetchModels);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function fetchModelStatus() {
      try {
        const url = selectedDomain
          ? `${API_BASE_URL}/api/model-info?dataset_name=${encodeURIComponent(selectedDomain)}`
          : `${API_BASE_URL}/api/model-info`;
        const res = await fetch(url);
        if (res.ok) {
          const data = (await res.json()) as BackendModelStatus;
          if (!cancelled) setModelStatus({ ...data, requestedDomain: selectedDomain });
        } else if (!cancelled) {
          setModelStatus(null);
        }
      } catch (err) {
        if (!cancelled) setModelStatus(null);
        console.warn("No se pudo conectar a /api/model-info:", err);
      }
    }
    fetchModelStatus();
    return () => { cancelled = true; };
  }, [selectedDomain]);

  useEffect(() => {
    return () => {
      if (audioUrl) {
        URL.revokeObjectURL(audioUrl);
      }
    };
  }, [audioUrl]);

  // Decodificación y extracción de forma de onda (oscilograma) en el navegador
  useEffect(() => {
    if (!file) return;

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

  const [history, setHistory] = useState<HistoryItem[]>([]);

  const handleFileSelection = useCallback(
    (selectedFile: File | null) => {
      inferenceSequence.current += 1;
      setError(null);
      setResult(null);

      if (audioUrl) {
        URL.revokeObjectURL(audioUrl);
        setAudioUrl(null);
      }
      setAudioStats(null);
      setIsPlaying(false);
      setCurrentTime(0);

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

      if (selectedFile.size > 100 * 1024 * 1024) {
        setError("El archivo supera el límite de 100 MiB (104.857.600 bytes). Selecciona un WAV más pequeño.");
        setFile(null);
        setIsDecodingAudio(false);
        if (fileInputRef.current) fileInputRef.current.value = "";
        return;
      }

      const nextUrl = URL.createObjectURL(selectedFile);
      setFile(selectedFile);
      setAudioUrl(nextUrl);
      setIsDecodingAudio(true);
    },
    [audioUrl]
  );

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0] || null;
    handleFileSelection(selectedFile);
  };

  const handleExecuteInference = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError("Carga un archivo de audio .wav antes de ejecutar la inferencia.");
      return;
    }

    if (file.size > 100 * 1024 * 1024) {
      setError("El archivo supera el límite de 100 MiB (104.857.600 bytes). Selecciona un WAV más pequeño.");
      return;
    }

    if (!selectedModel) {
      setError("No hay un modelo disponible para ejecutar la inferencia.");
      return;
    }

    setLoading(true);
    setLatency(null);
    setError(null);
    setResult(null);
    const startTime = performance.now();
    const sequence = ++inferenceSequence.current;
    const inferenceClasses = [...(selectedModel?.classes || [])];
    const inferenceModel = selectedModel?.name || selectedModelId;
    const inferenceModelId = selectedModelId;

    try {
      const formData = new FormData();
      formData.append("file", file);
      if (selectedDomain) {
        formData.append("dataset_name", selectedDomain);
      }

      const queryParam = selectedModelId ? `?model_id=${encodeURIComponent(selectedModelId)}` : "";
      const response = await fetch(`${API_BASE_URL}/api/predict${queryParam}`, {
        method: "POST",
        body: formData,
      });

      let data;
      try {
        data = await response.json();
      } catch {
        // Proxies can return HTML, plain text or an empty body; never expose it.
        data = null;
      }

      if (!response.ok) {
        const detail = data?.detail;
        const messages = (Array.isArray(detail) ? detail : [detail]).map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object") {
            if (typeof item.message === "string") return item.message;
            if (typeof item.msg === "string") return item.msg;
          }
          return "";
        }).filter(Boolean);
        throw new Error(messages.join("; ") || `Error HTTP ${response.status}${response.statusText ? `: ${response.statusText}` : ""}. No se pudo completar la inferencia.`);
      }

      if (!data || typeof data.filename !== "string" || !data.filename ||
          typeof data.clase !== "string" || !data.clase ||
          typeof data.confianza !== "number" || !Number.isFinite(data.confianza) ||
          data.confianza < 0 || data.confianza > 1 || typeof data.gcp_upload !== "boolean") {
        throw new Error("Respuesta de inferencia inválida. No se recibió una predicción válida del servidor.");
      }
      const elapsed = ((performance.now() - startTime) / 1000).toFixed(2);
      const predData = data as PredictionResponse;
      if (sequence !== inferenceSequence.current) return;
      setLatency(`${elapsed}s`);
      const modelMismatch = predData.modelo_id
        ? predData.modelo_id !== inferenceModelId
        : Boolean(predData.modelo && predData.modelo !== inferenceModel && predData.modelo !== inferenceModelId);
      setResult({ ...predData, inferenceClasses, inferenceModel, inferenceModelId, modelMismatch, inferenceDomain: selectedDomain, inferenceEnsemble: isEnsemble, sequence });

      const isEngine =
        isEngineModel ||
        Boolean(ENGINE_FAULT_LABELS[predData.clase]);

      // Agregar al inicio del historial de predicciones con badge code y modelo utilizado
      const newItem: HistoryItem = {
        id: typeof predData.db_id === "number" && Number.isInteger(predData.db_id) && predData.db_id > 0 ? predData.db_id : null,
        filename: predData.filename,
        timestamp: new Date().toLocaleString(),
        clase: predData.clase,

        confianza: predData.confianza,
        modelo: predData.modelo || "No informado por la API",
        domain: isEngine ? "engine_diagnostics" : "AvesChilenas",
      };

      setHistory((prev) => [newItem, ...prev]);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(
          err.message.includes("Failed to fetch")
            ? `No se pudo conectar con el backend (${API_BASE_URL}). Verifica que el servicio FastAPI esté activo con uvicorn main:app --reload.`
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
    const translatedName = ENGINE_FAULT_LABELS[item.clase] || "";
    const matchesClass =
      classFilter === "all" ||
      item.clase.toLowerCase() === classFilter.toLowerCase() ||
      (translatedName && translatedName.toLowerCase().includes(classFilter.toLowerCase()));
    return matchesSearch && matchesClass;
  });

  return (
    <div className="space-y-5">
      {/* Header de la Vista */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-white tracking-tight font-heading">
            Predicción y Monitoreo Acústico
          </h1>
          <p className="text-xs text-gray-400 mt-0.5">
            Plataforma Multi-Dominio F.A.M.A. · Bioacústica y Diagnóstico Industrial
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5 sm:gap-3 w-full lg:w-auto">
          {/* Selector de Modelo Acústico Registrado */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#16171b] border border-[#23252e] flex-1 sm:flex-initial min-w-0 max-w-full">
            <label htmlFor="model-select" className="text-[11px] text-gray-400 font-medium shrink-0">
              Modelo:
            </label>
            <select
              id="model-select"
              value={selectedModelId}
              onChange={(e) => setSelectedModelId(e.target.value)}
              className="bg-[#101114] border border-[#2d303b] text-white text-xs font-semibold rounded px-2.5 py-1 focus:outline-none focus:border-blue-500 cursor-pointer min-w-0 w-full sm:w-auto max-w-[240px] sm:max-w-[340px] truncate"
            >
              {availableModels.length > 0 ? (
                <>
                  {bioModels.length > 0 && (
                    <optgroup label="Bioacústica (Aves Chilenas)">
                      {bioModels.map((m) => (
                        <option key={m.id} value={m.id} className="bg-[#16171b] text-white">
                          {m.name || m.id}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {engineModels.length > 0 && (
                    <optgroup label="Diagnóstico Industrial (Motores)">
                      {engineModels.map((m) => (
                        <option key={m.id} value={m.id} className="bg-[#16171b] text-white">
                          {m.name || m.id}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </>
              ) : (
                <option value="">Sin modelos disponibles</option>
              )}
            </select>
          </div>

          {/* Indicador de Latencia / Estado a la derecha */}
          <div
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-full bg-black/40 border border-green-800/40 text-green-400 text-xs font-mono shrink-0 whitespace-nowrap"
            title="Tiempo total observado por el navegador, incluida transferencia y lectura de respuesta"
          >
            <span>Tiempo total de solicitud: {latency ?? "no disponible"}</span>
          </div>
        </div>
      </div>

      {catalogueError && <p role="alert" className="text-xs text-red-300">{catalogueError}</p>}
      {publicationErrors.length > 0 && (
        <div role="status" aria-label="Publicación de modelos" className="text-xs text-amber-300">
          <p>Algunos modelos no pudieron publicarse. Los modelos disponibles siguen siendo seleccionables.</p>
          <ul>
            {publicationErrors.map((issue, index) => {
              const labels: Record<string, string> = {
                checkpoint_missing: "archivo de pesos ausente",
                checkpoint_too_small: "archivo de pesos incompleto",
                checkpoint_invalid: "archivo de pesos inválido",
                checkpoint_unreadable: "archivo de pesos ilegible",
                checkpoint_outside_root: "archivo de pesos fuera de la ubicación permitida",
                database_unavailable: "base de datos no disponible",
              };
              const id = issue.model_id && /^[a-zA-Z0-9_-]+$/.test(issue.model_id) ? issue.model_id : "Modelo sin identificador";
              return <li key={index}>{id}: {labels[issue.code] || "error de publicación"}</li>;
            })}
          </ul>
        </div>
      )}

      {/* Banner de Especificaciones y Contrato Acústico del Modelo */}
      <div
        className={`rounded-xl p-3.5 border flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs ${
          isEngineModel
            ? "bg-amber-950/20 border-amber-800/40 text-amber-200"
            : "bg-blue-950/20 border-blue-800/40 text-blue-200"
        }`}
      >
        <div className="flex items-center gap-3">
          <div
            className={`p-2 rounded-lg shrink-0 ${
              isEngineModel
                ? "bg-amber-950/60 text-amber-400 border border-amber-800/50"
                : "bg-blue-950/60 text-blue-400 border border-blue-800/50"
            }`}
          >
            {isEngineModel ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 100-6 3 3 0 000 6z" />
              </svg>
            )}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-white">
                {isEngineModel
                  ? "Dominio Activo: Diagnóstico Acústico de Motores"
                  : "Dominio Activo: Bioacústica de Aves Chilenas"}
              </span>
              <span
                className={`text-[10px] font-mono px-2 py-0.5 rounded font-semibold border ${
                  isEngineModel
                    ? "bg-amber-950/80 border-amber-700/60 text-amber-300"
                    : "bg-emerald-950/80 border-emerald-700/60 text-emerald-300"
                }`}
              >
                {isEngineModel ? `${classesCount} Fallas Mecánicas` : `${classesCount} Especies Oficiales`}
              </span>
            </div>
            <p className="text-[11px] text-gray-300 mt-0.5">
              {`Contrato publicado: Audios de ${formattedDuration} a ${formattedSrHz} · ${selectedModel?.name || "Sin modelo disponible"}`}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 font-mono text-[11px] shrink-0 self-end sm:self-auto">
          <span className="bg-[#111215] px-2.5 py-1 rounded border border-[#23252e]">
            {formattedDuration} @ {formattedSr}
          </span>
          <span className="bg-[#111215] px-2.5 py-1 rounded border border-[#23252e] text-emerald-400 font-semibold">
            {formattedMetric}
          </span>
        </div>
      </div>

      {/* Panel de Estado y Preparación de la Tríada o Especificaciones Individuales */}
      {isEnsemble ? (
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
                    {isEngineModel
                      ? "Estado del Super-Ensamble Acústico de Motores"
                      : "Estado del Super-Ensamble Tri-Modelo Bioacústico"}
                  </h2>
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-950/80 border border-emerald-800/80 text-emerald-400 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    Participantes disponibles en el resultado de inferencia
                  </span>
                </div>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  Sin inferencia no se acredita participación ni ponderación.
                </p>
              </div>
            </div>

            <div className="text-[11px] text-gray-400 flex items-center gap-2 font-mono">
              <span className="bg-[#101114] px-2 py-1 rounded border border-[#23252e]">
                Dispositivo: {modelStatus?.device || "Estado no disponible"}
              </span>
              <span className="bg-[#101114] px-2 py-1 rounded border border-[#23252e]">
                {classesCount} {isEngineModel ? "fallas mecánicas" : "especies"}
              </span>
            </div>
          </div>

          <p className="text-xs text-gray-400">Los participantes y pesos informados por la API se muestran únicamente junto al resultado correspondiente.</p>
        </div>
      ) : (
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-[#23252e]">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-lg bg-blue-950/50 border border-blue-800/40 text-blue-400">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
                </svg>
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-bold text-white">
                    Especificaciones del Modelo Individual Activo
                  </h2>
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-950/80 border border-blue-800/80 text-blue-400 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                    Modelo Autónomo Standalone
                  </span>
                </div>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  {selectedModel?.description || "Inferencia individual con parámetros acústicos dedicados"}
                </p>
              </div>
            </div>

            <div className="text-[11px] text-gray-400 flex items-center gap-2 font-mono">
              <span className="bg-[#101114] px-2 py-1 rounded border border-[#23252e]">
                Dispositivo: {modelStatus?.device || "Estado no disponible"}
              </span>
              <span className="bg-[#101114] px-2 py-1 rounded border border-[#23252e]">
                {classesCount} {isEngineModel ? "fallas mecánicas" : "especies"}
              </span>
            </div>
          </div>

          {/* Tarjetas de Especificaciones Individuales */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="rounded-lg p-3.5 border bg-[#111215] border-[#252834]">
              <span className="text-[10px] text-gray-500 block uppercase font-mono">Arquitectura / Backbone</span>
              <span className="text-xs font-bold text-white font-mono mt-1 block truncate" title={selectedModel?.name || selectedModelId}>
                {selectedModel?.name || selectedModelId}
              </span>
              <span className="text-[10px] text-gray-400 mt-1 block truncate">
                ID: {selectedModelId}
              </span>
            </div>

            <div className="rounded-lg p-3.5 border bg-[#111215] border-[#252834]">
              <span className="text-[10px] text-gray-500 block uppercase font-mono">Estado de Pesos</span>
              <div className="flex items-center gap-1.5 mt-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                <span className="text-xs font-semibold text-emerald-400">
                  {!selectedModel ? "Sin modelo disponible" : selectedModel.has_weights === true ? "Pesos publicados" : selectedModel.has_weights === false ? "Sin pesos publicados" : "Estado no disponible"}
                </span>
              </div>
              <span className="text-[10px] text-gray-400 mt-1 block">
                Contrato: {formattedDuration} @ {formattedSr}
              </span>
            </div>

            <div className="rounded-lg p-3.5 border bg-[#111215] border-[#252834]">
              <span className="text-[10px] text-gray-500 block uppercase font-mono">Clases Soportadas</span>
              <span className="text-xs font-bold text-white font-mono mt-1 block">
                {classesCount} {isEngineModel ? "Fallas" : "Especies"}
              </span>
              <span className="text-[10px] text-gray-400 mt-1 block">
                Vocabulario {isEngineModel ? "industrial" : "bioacústico"}
              </span>
            </div>

            <div className="rounded-lg p-3.5 border bg-[#111215] border-[#252834]">
              <span className="text-[10px] text-gray-500 block uppercase font-mono">Rendimiento / Métrica</span>
              <span className="text-xs font-bold text-emerald-400 font-mono mt-1 block">
                {formattedMetric}
              </span>
              <span className="text-[10px] text-gray-400 mt-1 block">
                Evaluación en test set
              </span>
            </div>
          </div>
        </div>
      )}

      <section aria-label="Evaluaciones finales" className="rounded-xl border border-[#23252e] bg-[#16171b] p-4 sm:p-5 space-y-4">
        <div>
          <h2 className="text-sm font-bold text-white">Informes finales por split</h2>
          <p className="mt-1 text-xs text-gray-400">Los informes son históricos y se consultan junto con el catálogo de modelos.</p>
        </div>
        {evaluationCatalogueStatus === "unavailable" ? (
          <p role="status" className="text-xs text-amber-200">
            Catálogo de evaluaciones no disponible: {evaluationCatalogueErrorCode === "evaluation_records_invalid"
              ? "hay registros que no se pueden mostrar."
              : evaluationCatalogueErrorCode === "evaluation_store_unavailable"
                ? "el almacenamiento no está disponible."
                : "no se pudo consultar."}
          </p>
        ) : evaluationCatalogueStatus === "legacy" ? (
          <p role="status" className="text-xs text-gray-300">Esta respuesta antigua del catálogo no informa el estado de las evaluaciones finales.</p>
        ) : !selectedModel ? (
          <p role="status" className="text-xs text-gray-300">Selecciona un modelo para consultar sus informes finales.</p>
        ) : !selectedModel.evaluations?.val?.latest_attempt && !selectedModel.evaluations?.val?.latest_completed &&
          !selectedModel.evaluations?.test?.latest_attempt && !selectedModel.evaluations?.test?.latest_completed ? (
          <p role="status" className="text-xs text-gray-300">Catálogo de evaluaciones disponible; no hay informes finales para este modelo.</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <EvaluationSplitCard label="Validación (val)" split={selectedModel.evaluations?.val} />
            <EvaluationSplitCard label="Test (test)" split={selectedModel.evaluations?.test} />
          </div>
        )}
      </section>

      {/* Fila 1: Modelo Activo (Super-Ensamble) + Cargar Audio */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Tarjeta: Modelo Activo Actualizado con Datos Reales */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-400 font-medium">Modelo activo en producción</span>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-950/60 border border-green-800/60 text-green-400 flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                {selectedModel ? "Modelo seleccionado" : "Sin modelo disponible"}
              </span>
            </div>
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-base font-bold text-white">
                  {selectedModel?.name || "Sin modelo disponible"}
                </h2>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  {selectedModel?.description || "Descripción no publicada"}
                </p>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <span className="text-[10px] text-gray-400 font-mono bg-[#1d1f27] border border-[#2b2d38] px-1.5 py-0.5 rounded uppercase">
                  {modelStatus?.device || "Estado no disponible"}
                </span>
                <span className="text-xs text-blue-400 font-mono bg-blue-950/50 border border-blue-800/50 px-2 py-0.5 rounded">
                  Versión no publicada
                </span>
              </div>
            </div>
          </div>

          <h3 className="mt-5 border-t border-[#23252e]/70 pt-4 text-xs font-semibold text-gray-300">Métricas históricas del catálogo (legacy; sin reinterpretar)</h3>
          <div role="group" aria-label="Métricas históricas" className="grid grid-cols-3 gap-3 text-xs">
            <div>
              <span className="text-gray-400 block text-[11px]">Accuracy histórica (legacy)</span>
              <span className="text-sm font-bold text-white font-mono mt-0.5 block">
                {selectedModel?.metrics?.accuracy != null ? `${(Number(selectedModel.metrics.accuracy) * 100).toFixed(2)}%` : "Sin métricas publicadas"}
              </span>
            </div>
            <div>
              <span className="text-gray-400 block text-[11px]">
                F1 histórico (legacy)
              </span>
              <span className="text-sm font-bold text-green-400 font-mono mt-0.5 block">
                {selectedModel?.metrics?.f1_macro != null ? `${(Number(selectedModel.metrics.f1_macro) * 100).toFixed(2)}%` : "Sin métricas publicadas"}
              </span>
            </div>
            <div>
              <span className="text-gray-400 block text-[11px]">
                Precision histórica (legacy)
              </span>
              <span className="text-sm font-bold text-blue-400 font-mono mt-0.5 block">
                {selectedModel?.metrics?.precision_macro != null ? `${(Number(selectedModel.metrics.precision_macro) * 100).toFixed(2)}%` : "Sin métricas publicadas"}
              </span>
            </div>
            <div className="col-span-3 flex items-center justify-between pt-2 border-t border-[#23252e]/40 text-[11px] text-gray-400">
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                {`Contrato publicado: ${formattedDuration} @ ${formattedSr}`}
              </span>
              <span className="text-gray-500 font-mono">
                {isEngineModel ? `${classesCount} fallas mecánicas` : `${classesCount} especies`}
              </span>
            </div>
          </div>
        </div>

        {/* Tarjeta: Cargar Audio */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 flex flex-col justify-between">
          <span className="text-xs text-gray-400 font-medium mb-3 block">
            {isEngineModel
              ? "Cargar audio de motor (.wav)"
              : "Cargar audio de campo (.wav)"}
          </span>

          {/* Área Drag & Drop con borde punteado */}
          <div
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              const f = e.dataTransfer.files?.[0];
              if (f && f.name.toLowerCase().endsWith(".wav")) {
                handleFileSelection(f);
              }
            }}
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
              {file
                ? `${(file.size / 1024).toFixed(1)} KB`
                : `Audio ${isEngineModel ? "mecánico" : "bioacústico"} recomendado: ${formattedDuration} @ ${formattedSr} · .wav mono/estéreo`}
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
                <span className="text-xs text-gray-300 font-medium block">Audio original · canal 1 (mono/estéreo)</span>
                <span className="text-[10px] text-gray-500 block">Oscilograma, RMS y pico calculados en el navegador; no representan el audio preprocesado por el modelo.</span>
                <span className="text-[10px] text-gray-500 mt-0.5 block">
                  {audioStats
                    ? `${(audioStats.sampleRate / 1000).toFixed(1)} kHz · ${audioStats.channels === 1 ? "Mono" : "Estéreo"} · ${audioStats.duration.toFixed(2)}s`
                    : "Sin audio decodificado"}
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
                    </defs>

                    {/* Líneas guía de amplitud */}
                    <line x1="0" y1="20" x2="500" y2="20" stroke="#1c1f2b" strokeWidth="1" strokeDasharray="2 4" />
                    <line x1="0" y1="60" x2="500" y2="60" stroke="#252a3a" strokeWidth="1" strokeDasharray="3 3" />
                    <line x1="0" y1="100" x2="500" y2="100" stroke="#1c1f2b" strokeWidth="1" strokeDasharray="2 4" />

                    {/* Grupo de forma de onda recortado progresivamente */}
                    <g>
                      {/* Polígono relleno de la envolvente simétrica */}
                      <path d={waveformPaths.fillD} fill="url(#waveformGradient)" />

                      {/* Contornos superior e inferior */}
                      <path d={waveformPaths.topStrokeD} fill="none" stroke="#60a5fa" strokeWidth="1.6" />
                      <path d={waveformPaths.bottomStrokeD} fill="none" stroke="#3b82f6" strokeWidth="1.2" />
                    </g>

                    {/* Cabezal de reproducción (Playhead) interactivo con animación suave */}
                    {audioUrl && (
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
                  <span ref={timeLabelRef} className="text-gray-500">
                    {currentTime.toFixed(2)}s / {audioStats.duration.toFixed(2)}s
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Botón: Ejecutar Inferencia */}
          <button
            type="button"
            onClick={handleExecuteInference}
            disabled={loading || !file || !selectedModel}
            className="mt-4 w-full py-2.5 px-4 rounded-lg text-xs font-semibold text-white bg-[#2b2d35] hover:bg-[#343740] active:bg-[#23242b] disabled:opacity-40 disabled:cursor-not-allowed border border-[#373a46] transition-all flex items-center justify-center gap-2 shadow-sm"
          >
            {loading ? (
              <>
                <svg className="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span>Procesando inferencia con {isEnsemble ? "Super-Ensamble" : (selectedModel?.name || "modelo")}...</span>
              </>
            ) : (
              <>
                <span>▷</span>
                <span>{isEngineModel ? "Ejecutar inferencia de motores" : "Ejecutar inferencia bioacústica"}</span>
              </>
            )}
          </button>
        </div>

        {/* Tarjeta: Resultado */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 flex flex-col justify-between">
          <span className="text-xs text-gray-400 font-medium block mb-2">
            {result?.inferenceEnsemble ? "Veredicto del Super-Ensamble" : "Veredicto del Modelo"}
          </span>

          {result ? (
            <div className="bg-[#111215] border border-[#23252e] rounded-lg p-4 space-y-3">
              <div>
                <span className="text-[10px] text-gray-400 uppercase tracking-wider block font-semibold">
                  {result.inferenceDomain === "engine_diagnostics"
                    ? "Diagnóstico Mecánico Detectado"
                    : "Clase Predicha"}
                </span>
                <p
                  className={`text-xl font-bold mt-0.5 ${
                    result.inferenceDomain === "engine_diagnostics"
                      ? result.clase.startsWith("normal_")
                        ? "text-emerald-400"
                        : "text-amber-400"
                      : "text-green-400"
                  }`}
                >
                  {ENGINE_FAULT_LABELS[result.clase] || result.clase}
                </p>
                {Boolean(ENGINE_FAULT_LABELS[result.clase]) && (
                  <span className="text-[10px] font-mono text-gray-400 block mt-0.5">
                    Clase técnica: {result.clase}
                  </span>
                )}
              </div>

              {/* Indicador del modelo utilizado para la predicción */}
              <div className="bg-[#14151a] rounded-lg p-2.5 border border-[#23252e] space-y-1.5">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-gray-400">Modelo ejecutado:</span>
                  <span className="text-blue-400 font-mono font-semibold">
                    {result.modelo || result.modelo_id || "No informado por la API"}
                    {result.modelo && result.modelo_id && ` (${result.modelo_id})`}
                  </span>
                </div>
                {result.modelMismatch && (
                  <p role="alert" className="text-xs text-amber-300">
                    El modelo ejecutado difiere del modelo solicitado: {result.inferenceModel} ({result.inferenceModelId}). El resultado corresponde al modelo informado por la API.
                  </p>
                )}
                {result.inferenceEnsemble && result.modelos_activos && result.modelos_activos.length > 0 && (
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

              <div className="text-xs space-y-1">
                <span className="text-gray-400">Dataset de inferencia</span>
                {result.detalles?.dataset_name ? (
                  <p className="font-mono text-emerald-300">{result.detalles.dataset_name}</p>
                ) : (
                  <p role="status" className="text-amber-300">Sin dataset de inferencia asociado. El audio puede enviarse a revisión, pero no incorporarse hasta contar con una asociación verificable.</p>
                )}
              </div>

              {/* Nivel de confianza */}
              <div>
                <div className="flex justify-between items-center text-xs text-gray-300 mb-1">
                  <span>Puntuación del modelo (sin calibración acreditada):</span>
                  <span className="font-mono font-bold text-white">
                    {(result.confianza * 100).toFixed(2)}%
                  </span>
                </div>
                <div className="w-full bg-gray-800 rounded-full h-2 overflow-hidden">
                  <div
                    className={`h-2 rounded-full transition-all duration-500 ${
                      result.inferenceDomain === "engine_diagnostics" && !result.clase.startsWith("normal_")
                        ? "bg-amber-500"
                        : "bg-green-500"
                    }`}
                    style={{ width: `${Math.min(100, Math.max(0, result.confianza * 100))}%` }}
                  />
                </div>
              </div>

              {/* Metadatos de persistencia y trazabilidad */}
              <div className="pt-2 border-t border-[#23252e] flex items-center justify-between text-[11px] text-gray-400">
                <span className="font-mono">{result.db_id ? `Predicción #${result.db_id}` : "Predicción sin ID registrado"}</span>
                {result.gcp_upload && (
                  <span className="text-blue-400 flex items-center gap-1 text-[10px]">
                    ● Google Cloud Storage
                  </span>
                )}
              </div>
              <PredictionFeedback key={result.sequence} prediction={result} />
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
        <span className="text-xs text-gray-300 font-semibold block">Historial de predicciones de esta sesión</span>

        {/* Filtros de Búsqueda y Clases */}
        <div className="flex flex-col sm:flex-row gap-2.5">
          <div className="relative flex-1">
            <svg className="w-3.5 h-3.5 text-gray-500 absolute left-3 top-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder="Buscar por nombre de archivo o diagnóstico..."
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
            <option value="all">
              {isEngineModel
                ? `Todas las clases mecánicas (${classesCount})`
                : `Todas las especies de aves (${classesCount})`}
            </option>
            {isEngineModel
              ? currentClasses.map((cls) => (
                  <option key={cls} value={cls}>
                    {ENGINE_FAULT_LABELS[cls] || cls}
                  </option>
                ))
              : currentClasses.map((species) => (
                  <option key={species} value={species}>
                    {species}
                  </option>
                ))}
          </select>
        </div>

        {/* Lista de Registros */}
        <div className="space-y-2">
          {history.length === 0 && <p className="text-xs text-gray-400">Sin predicciones en esta sesión.</p>}
          {filteredHistory.map((item) => (
            <div
              key={`${item.timestamp}-${item.filename}-${history.indexOf(item)}`}
              className="bg-[#111215] border border-[#1f2128] hover:border-[#2d303b] transition-colors rounded-lg px-4 py-3 flex items-center justify-between"
            >
              <div>
                <p className="text-xs font-medium text-gray-200 font-mono">{item.filename}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[10px] text-gray-500">{item.timestamp}</span>
                  <span className="text-[10px] text-green-400/90 font-medium">
                    · {ENGINE_FAULT_LABELS[item.clase] || item.clase}
                  </span>
                  {item.modelo && (
                    <span className="text-[9px] text-blue-400/80 bg-blue-950/40 px-1.5 py-0.2 rounded border border-blue-900/40 font-mono">
                      {item.modelo}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#1e2027] border border-[#2d303b] text-gray-300">
                  {item.id !== null ? `ID de predicción: ${item.id}` : "ID de predicción no disponible"}
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
