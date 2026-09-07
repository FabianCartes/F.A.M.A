"use client";

import { TabType } from "../Sidebar";

interface DashboardViewProps {
  onNavigate: (tab: TabType) => void;
}

export default function DashboardView({ onNavigate }: DashboardViewProps) {
  return (
    <div className="space-y-5">
      {/* Header de la Vista (Figura 6.5) */}
      <div>
        <h1 className="text-xl font-bold text-white tracking-tight font-heading">
          Dashboard
        </h1>
        <p className="text-xs text-gray-400 mt-0.5">
          Resumen del estado del framework MLOps
        </p>
      </div>

      {/* Fila 1: 4 KPIs Principales */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
        {/* KPI 1: Accuracy */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-4">
          <div className="flex items-center gap-1.5 text-gray-400 text-xs font-medium">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <span>Accuracy</span>
          </div>
          <p className="text-2xl font-bold text-white font-mono mt-3">93.89%</p>
        </div>

        {/* KPI 2: Loss */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-4">
          <div className="flex items-center gap-1.5 text-gray-400 text-xs font-medium">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M13 17h8m0 0V9m0 8l-8-8-4 4-6-6" />
            </svg>
            <span>Loss</span>
          </div>
          <p className="text-2xl font-bold text-[#ef4444] font-mono mt-3">0.2456</p>
        </div>

        {/* KPI 3: Datasets disponibles */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-4">
          <div className="flex items-center gap-1.5 text-gray-400 text-xs font-medium">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
            </svg>
            <span>Datasets disponibles</span>
          </div>
          <p className="text-2xl font-bold text-white font-mono mt-3">12</p>
        </div>

        {/* KPI 4: Predicciones hoy */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-4">
          <div className="flex items-center gap-1.5 text-gray-400 text-xs font-medium">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
            </svg>
            <span>Predicciones hoy</span>
          </div>
          <p className="text-2xl font-bold text-white font-mono mt-3">847</p>
        </div>
      </div>

      {/* Fila 2: Métricas de Entrenamiento + Actividad Reciente */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Gráfico: Métricas del último entrenamiento (Figura 6.5) */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5">
          <span className="text-xs text-gray-300 font-semibold block mb-4">
            Métricas del último entrenamiento
          </span>

          <div className="relative bg-[#101114] rounded-lg p-4 border border-[#1f2128]">
            <div className="flex">
              {/* Eje Y */}
              <div className="flex flex-col justify-between text-[9px] font-mono text-gray-500 pr-3 select-none h-40">
                <span>1.50</span>
                <span>1.20</span>
                <span>0.80</span>
                <span>0.40</span>
                <span>0.00</span>
              </div>

              {/* Área del Gráfico SVG */}
              <div className="flex-1 relative">
                {/* Cuadrícula tenue */}
                <div className="absolute inset-0 flex flex-col justify-between pointer-events-none opacity-15">
                  <div className="border-b border-gray-500 w-full" />
                  <div className="border-b border-gray-500 w-full" />
                  <div className="border-b border-gray-500 w-full" />
                  <div className="border-b border-gray-500 w-full" />
                  <div className="border-b border-gray-500 w-full" />
                </div>

                <svg viewBox="0 0 400 160" className="w-full h-40 overflow-visible" preserveAspectRatio="none">
                  {/* Curva Azul: Accuracy (sube de ~0.55 a ~0.94) */}
                  <path
                    d="M 10,105 Q 120,90 200,65 T 390,30"
                    fill="none"
                    stroke="#3b82f6"
                    strokeWidth="2.2"
                  />
                  {/* Curva Roja: Loss (baja de ~1.25 a ~0.24) */}
                  <path
                    d="M 10,35 Q 100,75 200,105 T 390,135"
                    fill="none"
                    stroke="#ef4444"
                    strokeWidth="2.2"
                  />
                </svg>
              </div>
            </div>

            {/* Eje X (Épocas 1 a 10) */}
            <div className="flex justify-between text-[9px] font-mono text-gray-500 mt-2 pl-9 pr-1">
              <span>1</span>
              <span>2</span>
              <span>3</span>
              <span>4</span>
              <span>5</span>
              <span>6</span>
              <span>7</span>
              <span>8</span>
              <span>9</span>
              <span>10</span>
            </div>
          </div>
        </div>

        {/* Actividad Reciente (Figura 6.5) */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 flex flex-col justify-between">
          <span className="text-xs text-gray-300 font-semibold block mb-3">
            Actividad reciente
          </span>

          <div className="space-y-2.5 text-xs">
            <div className="flex items-start gap-2.5 py-1">
              <span className="px-2 py-0.5 rounded text-[10px] bg-white/10 text-gray-300 shrink-0 font-medium">
                Entrenamiento
              </span>
              <div className="flex-1">
                <p className="text-gray-200">Entrenamiento completado — modelo v2.3.1</p>
                <span className="text-[10px] text-gray-500">28 jun 2026, 6:30</span>
              </div>
            </div>

            <div className="flex items-start gap-2.5 py-1">
              <span className="px-2 py-0.5 rounded text-[10px] bg-blue-950/60 text-blue-300 border border-blue-800/40 shrink-0 font-medium">
                Sincronización
              </span>
              <div className="flex-1">
                <p className="text-gray-200">Sincronización con GCP Storage completada</p>
                <span className="text-[10px] text-gray-500">28 jun 2026, 5:15</span>
              </div>
            </div>

            <div className="flex items-start gap-2.5 py-1">
              <span className="px-2 py-0.5 rounded text-[10px] bg-purple-950/60 text-purple-300 border border-purple-800/40 shrink-0 font-medium">
                Predicción
              </span>
              <div className="flex-1">
                <p className="text-gray-200">Predicción por lote — 320 archivos procesados</p>
                <span className="text-[10px] text-gray-500">28 jun 2026, 4:45</span>
              </div>
            </div>

            <div className="flex items-start gap-2.5 py-1">
              <span className="px-2 py-0.5 rounded text-[10px] bg-red-950/60 text-red-300 border border-red-800/40 shrink-0 font-medium">
                Error
              </span>
              <div className="flex-1">
                <p className="text-gray-200">Pipeline de ingesta falló — archivo corrupto</p>
                <span className="text-[10px] text-gray-500">28 jun 2026, 3:00</span>
              </div>
            </div>

            <div className="flex items-start gap-2.5 py-1">
              <span className="px-2 py-0.5 rounded text-[10px] bg-blue-950/60 text-blue-300 border border-blue-800/40 shrink-0 font-medium">
                Sincronización
              </span>
              <div className="flex-1">
                <p className="text-gray-200">Sincronización de dataset &apos;bosque-tropical&apos;</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Fila 3: Estado Nodos + Acceso Rápido + Alertas (Figura 6.5) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Tarjeta 1: Estado de Nodos Locales */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3">
          <span className="text-xs text-gray-300 font-semibold block">Estado de nodos locales</span>
          <div className="space-y-2 text-xs">
            <div className="flex justify-between items-center">
              <span className="text-gray-400 flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                GPU
              </span>
              <span className="text-emerald-400 font-medium font-mono text-[11px] flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                CUDA activo 67°C
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-400 flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7" />
                </svg>
                RAM
              </span>
              <span className="text-gray-200 font-mono text-[11px]">23.4 / 32.0 GB</span>
            </div>
          </div>
        </div>

        {/* Tarjeta 2: Acceso Rápido */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-2.5">
          <span className="text-xs text-gray-300 font-semibold block">Acceso rápido</span>
          <div className="space-y-1.5">
            <button
              onClick={() => onNavigate("ingesta")}
              className="w-full py-1.5 px-3 rounded-md bg-white hover:bg-gray-100 text-gray-900 font-semibold text-xs transition-colors text-left flex items-center gap-2 shadow-sm"
            >
              <span>🗄️</span>
              <span>Ingesta</span>
            </button>
            <button
              onClick={() => onNavigate("entrenamiento")}
              className="w-full py-1.5 px-3 rounded-md bg-white hover:bg-gray-100 text-gray-900 font-semibold text-xs transition-colors text-left flex items-center gap-2 shadow-sm"
            >
              <span>🔄</span>
              <span>Entrenamiento</span>
            </button>
            <button
              onClick={() => onNavigate("prediccion")}
              className="w-full py-1.5 px-3 rounded-md bg-white hover:bg-gray-100 text-gray-900 font-semibold text-xs transition-colors text-left flex items-center gap-2 shadow-sm"
            >
              <span>📊</span>
              <span>Predicción</span>
            </button>
          </div>
        </div>

        {/* Tarjeta 3: Alertas */}
        <div className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-1.5 text-amber-400 text-xs font-semibold">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>Alertas</span>
          </div>

          <div className="space-y-2 text-[11px]">
            <div>
              <span className="text-red-400 font-semibold block">⚠️ Error</span>
              <p className="text-gray-400 text-[10px] leading-tight mt-0.5">
                Pipeline de ingesta — archivo corrupto detectado en dataset &apos;Tos resfrío&apos;
              </p>
            </div>
            <div>
              <span className="text-amber-400 font-semibold block">⚠️ Advertencia</span>
              <p className="text-gray-400 text-[10px] leading-tight mt-0.5">
                Dataset &apos;humedales&apos; sin procesar — requiere validación
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
