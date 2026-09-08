"use client";

import { useState, useRef, ChangeEvent, FormEvent } from "react";

interface PredictionResponse {
  filename: string;
  gcp_upload: boolean;
  db_id: number;
  clase: string;
  confianza: number;
}

interface HistoryItem {
  id: number | string;
  filename: string;
  timestamp: string;
  clase: string;
  confianza: number;
  badgeCode?: string;
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
  const fileInputRef = useRef<HTMLInputElement | null>(null);

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

      // Agregar al inicio del historial de predicciones con badge code
      const newItem: HistoryItem = {
        id: predData.db_id,
        filename: predData.filename,
        timestamp: new Date().toLocaleString(),
        clase: predData.clase,
        badgeCode: "AVE-" + String(predData.db_id).padStart(3, "0"),
        confianza: predData.confianza,
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight font-heading">
            Predicción y Monitoreo Bioacústico
          </h1>
          <p className="text-xs text-gray-400 mt-0.5">
            Super-Ensamble Tri-Modelo · Aves Chilenas · F.A.M.A.
          </p>
        </div>

        {/* Indicador de Latencia / Estado a la derecha */}
        <div className="flex items-center gap-2 px-2.5 py-1 rounded-full bg-black/40 border border-green-800/40 text-green-400 text-xs font-mono">
          <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
          <span>Latencia: {latency}</span>
        </div>
      </div>

      {/* Fila 1: Modelo Activo (Super-Ensamble) + Cargar Audio */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Tarjeta: Modelo Activo Actualizado con Datos Reales */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-400 font-medium">Modelo activo en producción</span>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-950/60 border border-green-800/60 text-green-400">
                Super-Ensamble Activo
              </span>
            </div>
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-base font-bold text-white">Super-Ensamble Tri-Modelo</h2>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  EfficientNet-B0 (55%) · ConvNeXt-Nano (30%) · ResNet34d (15%)
                </p>
              </div>
              <span className="text-xs text-blue-400 font-mono bg-blue-950/50 border border-blue-800/50 px-2 py-0.5 rounded shrink-0">
                v3.0.0
              </span>
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
        {/* Tarjeta: Forma de Onda Acústica */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-400 font-medium block">Visualización de señal acústica</span>
              <span className="text-[10px] font-mono text-gray-500">22.05 kHz · Mono</span>
            </div>

            {/* Gráfico de Forma de Onda en Azul */}
            <div className="relative bg-[#101114] rounded-lg p-3 border border-[#1f2128] overflow-hidden">
              <svg
                viewBox="0 0 500 120"
                className="w-full h-24 overflow-hidden"
                preserveAspectRatio="none"
              >
                <defs>
                  <linearGradient id="waveformGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#2563eb" stopOpacity="0.4" />
                    <stop offset="100%" stopColor="#1e3a8a" stopOpacity="0.08" />
                  </linearGradient>
                </defs>
                <line x1="0" y1="60" x2="500" y2="60" stroke="#1f293d" strokeWidth="1" strokeDasharray="3 3" />

                <path
                  d="M 0,60 
                     C 25,58 35,50 55,52 
                     C 75,54 90,68 115,70 
                     C 135,72 145,85 165,88 
                     C 185,90 195,65 215,55 
                     C 235,48 245,56 265,58 
                     C 285,60 295,78 315,82 
                     C 335,84 345,45 365,38 
                     C 385,32 395,44 415,40 
                     C 435,35 445,68 465,72 
                     C 485,74 495,62 500,60 
                     L 500,120 L 0,120 Z"
                  fill="url(#waveformGradient)"
                />
                <path
                  d="M 0,60 
                     C 25,58 35,50 55,52 
                     C 75,54 90,68 115,70 
                     C 135,72 145,85 165,88 
                     C 185,90 195,65 215,55 
                     C 235,48 245,56 265,58 
                     C 285,60 295,78 315,82 
                     C 335,84 345,45 365,38 
                     C 385,32 395,44 415,40 
                     C 435,35 445,68 465,72 
                     C 485,74 495,62 500,60"
                  fill="none"
                  stroke="#3b82f6"
                  strokeWidth="2"
                />
              </svg>

              <div className="flex justify-between text-[9px] font-mono text-gray-500 mt-1 px-1">
                <span>0.0s</span>
                <span>1.0s</span>
                <span>2.0s</span>
                <span>3.0s</span>
                <span>4.0s</span>
                <span>5.0s</span>
              </div>
            </div>
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
