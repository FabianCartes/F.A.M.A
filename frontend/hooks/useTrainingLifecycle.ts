"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  HardwareStatus,
  TrainingDataset,
  StartTrainingRequest,
  MetricPoint,
  LogEntry,
  ModelHistoryItem,
} from "@/lib/schemas/training";
import * as trainingApi from "@/lib/api/trainingApi";

export type ConnectionStatus = "online" | "offline" | "reconnecting";

export interface TriadProgress {
  isTriad: boolean;
  modelIdx: number;
  totalModels: number;
  currentArch: string;
}

const MAX_LOGS_BUFFER = 500;
const POLLING_INTERVAL_TRAINING_MS = 1000;
const POLLING_INTERVAL_IDLE_MS = 5000;
const MAX_BACKOFF_MS = 30000;

export function useTrainingLifecycle() {
  // Observability & Connection State (ODD)
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("online");
  const [lastError, setLastError] = useState<string | null>(null);
  const consecutiveErrorsRef = useRef<number>(0);

  // Hardware & Catalog Data
  const [hardware, setHardware] = useState<HardwareStatus | null>(null);
  const [datasets, setDatasets] = useState<TrainingDataset[]>([]);
  const [history, setHistory] = useState<ModelHistoryItem[]>([]);

  // Training Execution Lifecycle State
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
  const [triadProgress, setTriadProgress] = useState<TriadProgress>({
    isTriad: false,
    modelIdx: 1,
    totalModels: 1,
    currentArch: "",
  });

  const [activatingId, setActivatingId] = useState<number | null>(null);

  // References to keep track of current states in asynchronous timers
  const isTrainingRef = useRef<boolean>(isTraining);
  useEffect(() => {
    isTrainingRef.current = isTraining;
  }, [isTraining]);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Handle successful server interactions
  const handleSuccess = useCallback(() => {
    consecutiveErrorsRef.current = 0;
    setConnectionStatus("online");
    setLastError(null);
  }, []);

  // Handle connection errors with backoff logic (ODD)
  const handleError = useCallback((err: unknown) => {
    consecutiveErrorsRef.current += 1;
    const msg = err instanceof Error ? err.message : String(err);
    setLastError(msg);

    if (consecutiveErrorsRef.current >= 3) {
      setConnectionStatus("offline");
    } else {
      setConnectionStatus("reconnecting");
    }
  }, []);

  // Compute next polling delay with exponential backoff
  const getNextDelay = useCallback(() => {
    const base = isTrainingRef.current
      ? POLLING_INTERVAL_TRAINING_MS
      : POLLING_INTERVAL_IDLE_MS;
    const count = consecutiveErrorsRef.current;
    if (count === 0) return base;
    return Math.min(base * Math.pow(1.5, count), MAX_BACKOFF_MS);
  }, []);

  // Fetch telemetry and catalogs on demand
  const refreshHardware = useCallback(async () => {
    try {
      const data = await trainingApi.getHardwareStatus();
      setHardware(data);
      handleSuccess();
    } catch (err) {
      handleError(err);
    }
  }, [handleSuccess, handleError]);

  const refreshDatasets = useCallback(async () => {
    try {
      const data = await trainingApi.getDatasets();
      setDatasets(data);
      handleSuccess();
    } catch (err) {
      handleError(err);
    }
  }, [handleSuccess, handleError]);

  const refreshHistory = useCallback(async () => {
    try {
      const data = await trainingApi.getHistory();
      setHistory(data);
      handleSuccess();
    } catch (err) {
      handleError(err);
    }
  }, [handleSuccess, handleError]);

  // Initial load on mount
  useEffect(() => {
    let isCancelled = false;

    const loadInitialData = async () => {
      try {
        const [hw, ds, hist] = await Promise.all([
          trainingApi.getHardwareStatus(),
          trainingApi.getDatasets(),
          trainingApi.getHistory(),
        ]);
        if (!isCancelled) {
          setHardware(hw);
          setDatasets(ds);
          setHistory(hist);
          handleSuccess();
        }
      } catch (err) {
        if (!isCancelled) {
          handleError(err);
        }
      }
    };

    loadInitialData();

    return () => {
      isCancelled = true;
    };
  }, [handleSuccess, handleError]);

  // Adaptive polling loop
  useEffect(() => {
    let isCancelled = false;

    const scheduleNextPoll = () => {
      if (isCancelled) return;
      const delay = getNextDelay();
      timerRef.current = setTimeout(runPoll, delay);
    };

    const runPoll = async () => {
      if (isCancelled) return;

      try {
        if (isTrainingRef.current) {
          const progress = await trainingApi.getProgress();
          if (isCancelled) return;

          handleSuccess();
          setCurrentEpoch(progress.epoch);
          if (progress.total_epochs) setTotalEpochs(progress.total_epochs);
          setCurrentTrainLoss(progress.train_loss);
          setCurrentValLoss(progress.val_loss);
          setCurrentTrainAcc(progress.train_acc);
          setCurrentValAcc(progress.val_acc);
          if (progress.metrics_history) {
            setMetricsHistory(progress.metrics_history);
          }

          if (progress.logs && progress.logs.length > 0) {
            const rawLogs = progress.logs;
            setLogs(
              rawLogs.length > MAX_LOGS_BUFFER
                ? rawLogs.slice(-MAX_LOGS_BUFFER)
                : rawLogs
            );
          }

          if (progress.is_tri_model) {
            setTriadProgress({
              isTriad: true,
              modelIdx: progress.current_model_index,
              totalModels: progress.total_models,
              currentArch: progress.current_architecture,
            });
          }

          if (
            progress.status === "completed" ||
            progress.status === "failed" ||
            progress.status === "stopped"
          ) {
            setIsTraining(false);
            setIsStopping(false);
            refreshHistory();
            refreshHardware();
          }
        } else {
          // In idle mode, refresh hardware telemetry periodically
          const hw = await trainingApi.getHardwareStatus();
          if (isCancelled) return;
          setHardware(hw);
          handleSuccess();
        }
      } catch (err) {
        if (!isCancelled) {
          handleError(err);
        }
      } finally {
        scheduleNextPoll();
      }
    };

    scheduleNextPoll();

    return () => {
      isCancelled = true;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [isTraining, getNextDelay, handleSuccess, handleError, refreshHistory, refreshHardware]);

  // Actions
  const start = useCallback(
    async (params: StartTrainingRequest): Promise<boolean> => {
      if (isTrainingRef.current) return false;

      setIsTraining(true);
      setIsStopping(false);
      setMetricsHistory([]);
      setLogs([]);
      setCurrentEpoch(0);
      setTotalEpochs(params.epochs);
      setLastError(null);

      if (params.is_tri_model) {
        const isEngine = params.dataset_name === "engine_diagnostics";
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
          currentArch: params.architecture,
        });
      }

      try {
        const res = await trainingApi.startTraining(params);
        setTrainingJobId(res.job_id);
        handleSuccess();
        return true;
      } catch (err: unknown) {
        setIsTraining(false);
        handleError(err);
        return false;
      }
    },
    [handleSuccess, handleError]
  );

  const stop = useCallback(async (): Promise<boolean> => {
    if (!isTrainingRef.current || isStopping) return false;
    setIsStopping(true);

    try {
      await trainingApi.stopTraining();
      handleSuccess();
      return true;
    } catch (err: unknown) {
      setIsStopping(false);
      handleError(err);
      return false;
    }
  }, [isStopping, handleSuccess, handleError]);

  const activate = useCallback(
    async (modelId: number): Promise<boolean> => {
      setActivatingId(modelId);
      try {
        const res = await trainingApi.activateModel(modelId);
        if (res.success) {
          await refreshHistory();
          handleSuccess();
          return true;
        }
        return false;
      } catch (err) {
        handleError(err);
        return false;
      } finally {
        setActivatingId(null);
      }
    },
    [refreshHistory, handleSuccess, handleError]
  );

  const clearError = useCallback(() => {
    setLastError(null);
  }, []);

  return {
    // State
    connectionStatus,
    lastError,
    hardware,
    datasets,
    history,
    isTraining,
    isStopping,
    trainingJobId,
    currentEpoch,
    totalEpochs,
    currentTrainLoss,
    currentValLoss,
    currentTrainAcc,
    currentValAcc,
    metricsHistory,
    logs,
    triadProgress,
    activatingId,

    // Actions
    start,
    stop,
    activate,
    refreshHardware,
    refreshDatasets,
    refreshHistory,
    clearError,
  };
}
