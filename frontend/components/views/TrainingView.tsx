"use client";

import { useState } from "react";

export default function TrainingView() {
  const [learningRate, setLearningRate] = useState("0.0001");
  const [epochs, setEpochs] = useState("50");
  const [batchSize, setBatchSize] = useState("32");
  const [framework, setFramework] = useState("pytorch");
  const [architecture, setArchitecture] = useState("audiocnn");
  const [isTraining, setIsTraining] = useState(false);

  const handleTrain = () => {
    setIsTraining(true);
    setTimeout(() => setIsTraining(false), 3000);
  };

  return (
    <div className="space-y-5">
      {/* Header de la Vista (Figura 6.8) */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <svg className="w-5 h-5 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          <h1 className="text-xl font-bold text-white tracking-tight font-heading">
            Entrenamiento y Métricas
          </h1>
        </div>

        {/* Indicador Derecha */}
        <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-blue-950/70 border border-blue-700/60 text-blue-300 font-mono text-[11px]">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
          CUDA: Activo
        </span>
      </div>

      {/* Fila 1: Seleccionar Dataset + Monitor GPU (Figura 6.8) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Tarjeta: Seleccionar Dataset */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3">
          <span className="text-xs text-gray-400 font-medium flex items-center gap-1.5">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7" />
            </svg>
            Seleccionar Dataset
          </span>

          <div>
            <label className="text-[11px] text-gray-500 block mb-1">Dataset</label>
            <select className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-300 focus:outline-none focus:border-gray-500">
              <option value="xeno-canto">Xeno-canto v3 (15 Aves Chilenas · 1.205 audios)</option>
              <option value="esc-50">ESC-50 (Sonidos Ambientales)</option>
              <option value="urbansound">UrbanSound8K</option>
            </select>
          </div>
        </div>

        {/* Tarjeta: GPU Monitor */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400 font-medium flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
              GPU
            </span>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-cyan-950/70 border border-cyan-800/60 text-cyan-300 font-semibold">
              CUDA
            </span>
          </div>

          <div className="space-y-2 text-xs">
            <div>
              <div className="flex justify-between text-gray-400 text-[11px] mb-1">
                <span>VRAM</span>
                <span className="font-mono text-gray-200">3.2 / 8 GB</span>
              </div>
              <div className="w-full bg-[#111215] rounded-full h-1.5 overflow-hidden">
                <div className="bg-cyan-500 h-1.5 rounded-full" style={{ width: "40%" }} />
              </div>
            </div>

            <div className="flex justify-between text-[11px] pt-1">
              <span className="text-gray-400">Temperatura</span>
              <span className="font-mono text-emerald-400 font-semibold">67°C</span>
            </div>
          </div>
        </div>
      </div>

      {/* Tarjeta: Configuración de Entrenamiento (Figura 6.8) */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-4">
        <span className="text-xs text-gray-300 font-semibold flex items-center gap-1.5">
          <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          </svg>
          Configuración de Entrenamiento
        </span>

        {/* Inputs en Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label className="text-[11px] text-gray-400 block mb-1">Learning Rate</label>
            <input
              type="text"
              value={learningRate}
              onChange={(e) => setLearningRate(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-gray-500"
            />
          </div>

          <div>
            <label className="text-[11px] text-gray-400 block mb-1">Épocas</label>
            <input
              type="number"
              value={epochs}
              onChange={(e) => setEpochs(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-gray-500"
            />
          </div>

          <div>
            <label className="text-[11px] text-gray-400 block mb-1">Batch Size</label>
            <input
              type="number"
              value={batchSize}
              onChange={(e) => setBatchSize(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-gray-500"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="text-[11px] text-gray-400 block mb-1">Framework</label>
            <select
              value={framework}
              onChange={(e) => setFramework(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-300 focus:outline-none focus:border-gray-500"
            >
              <option value="pytorch">PyTorch 2.5</option>
              <option value="tensorflow">TensorFlow 2.16</option>
            </select>
          </div>

          <div>
            <label className="text-[11px] text-gray-400 block mb-1">Arquitectura</label>
            <select
              value={architecture}
              onChange={(e) => setArchitecture(e.target.value)}
              className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-1.5 text-xs text-gray-300 focus:outline-none focus:border-gray-500"
            >
              <option value="audiocnn">AudioCNN (FAMA Deep Model)</option>
              <option value="resnet18">ResNet-18 Spec</option>
              <option value="ast">Audio Spectrogram Transformer (AST)</option>
            </select>
          </div>
        </div>

        {/* Botón: Entrenar (Píldora ancha de la Figura 6.8) */}
        <button
          type="button"
          onClick={handleTrain}
          disabled={isTraining}
          className="w-full py-2.5 rounded-lg bg-gray-200 hover:bg-white text-gray-900 font-bold text-xs transition-colors flex items-center justify-center gap-2 shadow-sm disabled:opacity-50"
        >
          {isTraining ? (
            <>
              <svg className="animate-spin h-3.5 w-3.5 text-gray-900" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>Ejecutando pipeline de entrenamiento...</span>
            </>
          ) : (
            <>
              <span>▷</span>
              <span>Entrenar</span>
            </>
          )}
        </button>
      </div>

      {/* Fila 2: Métricas en Tiempo Real + Consola (Figura 6.8) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Tarjeta: Métricas en Tiempo Real */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3">
          <span className="text-xs text-gray-300 font-semibold block">
            Métricas en Tiempo Real
          </span>
          <div className="bg-[#101114] border border-[#1f2128] rounded-lg h-36 flex items-center justify-center text-gray-500 text-xs">
            {isTraining ? (
              <span className="animate-pulse text-blue-400 font-mono">Calculando loss y accuracy por época...</span>
            ) : (
              <span>Inicia un entrenamiento para observar curvas en vivo</span>
            )}
          </div>
        </div>

        {/* Tarjeta: Consola */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3">
          <span className="text-xs text-gray-300 font-semibold block">
            &gt;_ Consola
          </span>
          <div className="bg-[#0f1013] border border-[#1f2128] rounded-lg p-3 font-mono text-[11px] text-gray-300 h-36 overflow-y-auto space-y-1">
            <p><span className="text-gray-500">06:00:01</span> <span className="text-blue-400 bg-blue-950/70 px-1 rounded text-[10px]">INFO</span> Sistema listo. GPU CUDA disponible.</p>
            <p><span className="text-gray-500">06:00:02</span> <span className="text-blue-400 bg-blue-950/70 px-1 rounded text-[10px]">INFO</span> VRAM: 3.2/8.0 GB disponible.</p>
            <p><span className="text-gray-500">06:00:04</span> <span className="text-yellow-400 bg-yellow-950/70 px-1 rounded text-[10px]">WARN</span> Esperando configuración de entrenamiento...</p>
            {isTraining && (
              <p><span className="text-emerald-400">06:00:10</span> <span className="text-emerald-400 bg-emerald-950/70 px-1 rounded text-[10px]">INFO</span> Época 1/50 - Loss: 1.423 - Acc: 58.2%</p>
            )}
          </div>
        </div>
      </div>

      {/* Tarjeta: Historial de Entrenamientos (Figura 6.8) */}
      <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5">
        <span className="text-xs text-gray-300 font-semibold block">
          Historial de Entrenamientos
        </span>
        <p className="text-[11px] text-gray-500 mt-2">
          Último checkpoint guardado: <span className="font-mono text-gray-300">augmented_best.pt</span> (Test Accuracy: 61.69% · Val Loss: 1.1254)
        </p>
      </div>
    </div>
  );
}
