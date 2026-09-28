"use client";

import { useState, useEffect } from "react";
import Image from "next/image";
import { API_BASE_URL } from "@/lib/api";
import { getFeedbackStats } from "@/lib/api/feedbackApi";

export type TabType = "dashboard" | "ingesta" | "entrenamiento" | "prediccion";

interface SidebarProps {
  activeTab: TabType;
  onSelectTab: (tab: TabType) => void;
  isCollapsed: boolean;
  onToggleCollapsed: () => void;
}

interface HardwareMini {
  cuda_available: boolean;
  temperature_c?: number | null;
}

export default function Sidebar({
  activeTab,
  onSelectTab,
  isCollapsed,
  onToggleCollapsed,
}: SidebarProps) {
  const [hw, setHw] = useState<HardwareMini | null>(null);
  const [isGcpConnected, setIsGcpConnected] = useState<boolean>(true);
  const [pendingFeedbackCount, setPendingFeedbackCount] = useState<number>(0);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/training/hardware`)
      .then((res) => {
        if (res.ok) {
          setIsGcpConnected(true);
          return res.json();
        }
        return null;
      })
      .then((data) => {
        if (data) setHw(data);
      })
      .catch(() => null);

    const fetchStats = () => {
      getFeedbackStats()
        .then((stats) => {
          setPendingFeedbackCount(stats.pending_curation_count);
        })
        .catch(() => null);
    };

    fetchStats();
    const interval = setInterval(fetchStats, 10000);
    return () => clearInterval(interval);
  }, []);

  const navItems: { id: TabType; label: string; icon: React.ReactNode }[] = [
    {
      id: "dashboard",
      label: "Dashboard",
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.8}
            d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"
          />
        </svg>
      ),
    },
    {
      id: "ingesta",
      label: "Ingesta",
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.8}
            d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
          />
        </svg>
      ),
    },
    {
      id: "entrenamiento",
      label: "Entrenamiento",
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.8}
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
          />
        </svg>
      ),
    },
    {
      id: "prediccion",
      label: "Predicción",
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.8}
            d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
          />
        </svg>
      ),
    },
  ];

  const feedbackBadgeClass =
    pendingFeedbackCount === 0
      ? "bg-emerald-950/70 border-emerald-700/60 text-emerald-400"
      : "bg-amber-950/70 border-amber-700/60 text-amber-400";

  return (
    <aside className="w-full h-full min-w-0 bg-[#121316] border-r border-[#1f2128] flex flex-col justify-between select-none overflow-x-hidden">
      {/* Top Section: Logo & Nav */}
      <div className="min-w-0 min-h-0 overflow-y-auto overflow-x-hidden">
        {/* Cabecera de la barra lateral con Logo F.A.M.A. y Botón de Colapso */}
        <div
          className={`border-b border-[#1f2128] transition-all ${
            isCollapsed
              ? "flex items-center justify-center p-3 h-14"
              : "flex items-center justify-between px-3 py-3"
          }`}
        >
          <div className={`flex items-center min-w-0 pl-1 ${isCollapsed ? "md:hidden" : "block"}`}>
            <Image
              src="/F.A.M.A-sinFondoBlanco.png"
              alt="Logo F.A.M.A."
              width={140}
              height={32}
              unoptimized
              priority
              className="h-7 w-auto object-contain"
            />
          </div>
          <button
            type="button"
            onClick={onToggleCollapsed}
            aria-label={isCollapsed ? "Expandir panel lateral" : "Colapsar panel lateral"}
            aria-expanded={!isCollapsed}
            title={isCollapsed ? "Expandir panel lateral" : "Colapsar panel lateral"}
            className={`group relative hidden md:flex items-center justify-center rounded-lg text-gray-400 hover:text-white hover:bg-[#18191e] transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-blue-500 ${
              isCollapsed ? "h-9 w-9" : "h-8 w-8 shrink-0"
            }`}
          >
            <svg
              className="w-4 h-4 shrink-0 transition-transform"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d={isCollapsed ? "M9 5l7 7-7 7" : "M15 19l-7-7 7-7"}
              />
            </svg>
            <span className={isCollapsed ? "md:sr-only" : "sr-only"}>
              {isCollapsed ? "Expandir" : "Colapsar"}
            </span>
          </button>
        </div>

        {/* Navigation Items */}
        <nav
          aria-label="Navegación principal"
          className={`p-3 space-y-1.5 mt-2 ${isCollapsed ? "md:px-1.5" : ""}`}
        >
          {navItems.map((item) => {
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                id={`nav-${item.id}`}
                type="button"
                aria-current={isActive ? "page" : undefined}
                onClick={() => onSelectTab(item.id)}
                title={isCollapsed ? item.label : undefined}
                className={`group relative w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium cursor-pointer transition-all ${
                  isCollapsed ? "md:gap-0 md:justify-center md:px-0" : ""
                } ${
                  isActive
                    ? "bg-[#1d1f26] text-white border border-[#2e323e] shadow-sm"
                    : "text-gray-400 hover:text-gray-200 hover:bg-[#18191e]"
                }`}
              >
                <span className={isActive ? "text-white" : "text-gray-400"}>
                  {item.icon}
                </span>
                <span className={isCollapsed ? "md:sr-only" : ""}>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom Section: System Status Badges */}
      <div
        className={`shrink-0 border-t border-[#1f2128] space-y-2 text-[11px] p-4 ${
          isCollapsed ? "md:p-2" : ""
        }`}
      >
        {/* GCP Status */}
        <div
          className={`flex items-center justify-between ${isCollapsed ? "md:justify-center md:gap-1.5" : ""}`}
          title={isCollapsed ? `GCP: ${isGcpConnected ? "Conectado" : "Desconectado"}` : undefined}
        >
          <div className={`flex items-center text-gray-400 gap-1.5 ${isCollapsed ? "md:gap-0" : ""}`}>
            <svg
              className="w-3.5 h-3.5 text-gray-400 shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M13 10V3L4 14h7v7l9-11h-7z"
              />
            </svg>
            <span className={isCollapsed ? "md:sr-only" : ""}>GCP</span>
          </div>
          {isCollapsed ? (
            <span
              className={`hidden md:inline-block w-2 h-2 rounded-full shrink-0 ${
                isGcpConnected
                  ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.7)]"
                  : "bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.7)]"
              }`}
              aria-label={isGcpConnected ? "GCP Conectado" : "GCP Desconectado"}
            />
          ) : (
            <span
              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold flex items-center gap-1.5 border ${
                isGcpConnected
                  ? "bg-green-950/70 border-green-700/60 text-green-400"
                  : "bg-red-950/70 border-red-700/60 text-red-400"
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isGcpConnected ? "bg-green-400" : "bg-red-400"
                }`}
              />
              {isGcpConnected ? "Conectado" : "Desconectado"}
            </span>
          )}
        </div>

        {/* Cómputo / Hardware Status */}
        <div
          className={`flex items-center justify-between ${isCollapsed ? "md:justify-center md:gap-1.5" : ""}`}
          title={
            isCollapsed
              ? `Cómputo: ${
                  hw?.cuda_available
                    ? `GPU${hw.temperature_c ? ` · ${hw.temperature_c}°C` : ""}`
                    : "CPU Host"
                }`
              : undefined
          }
        >
          <div className={`flex items-center text-gray-400 gap-1.5 ${isCollapsed ? "md:gap-0" : ""}`}>
            <svg
              className="w-3.5 h-3.5 text-gray-400 shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"
              />
            </svg>
            <span className={isCollapsed ? "md:sr-only" : ""}>
              {hw?.cuda_available ? "GPU" : "Cómputo"}
            </span>
          </div>
          {isCollapsed ? (
            <span
              data-testid="hardware-badge-collapsed"
              className={`hidden md:inline-block px-1 py-0.2 rounded text-[9px] font-bold tracking-tight border ${
                hw?.cuda_available
                  ? "bg-emerald-950/70 border-emerald-700/60 text-emerald-400"
                  : "bg-blue-950/70 border-blue-700/60 text-blue-400"
              }`}
            >
              {hw?.cuda_available ? "GPU" : "CPU"}
            </span>
          ) : (
            <span
              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                hw?.cuda_available
                  ? "bg-emerald-950/70 border-emerald-700/60 text-emerald-400"
                  : "bg-blue-950/70 border-blue-700/60 text-blue-400"
              }`}
            >
              {hw?.cuda_available
                ? `GPU${hw.temperature_c ? ` · ${hw.temperature_c}°C` : ""}`
                : "CPU Host"}
            </span>
          )}
        </div>

        {/* Feedback / Notificaciones (RF_06) */}
        <div
          className={`flex items-center justify-between ${isCollapsed ? "md:justify-center md:gap-1.5" : ""}`}
          title={isCollapsed ? `Feedback: ${pendingFeedbackCount} pendientes` : undefined}
        >
          <div className={`flex items-center text-gray-400 ${isCollapsed ? "md:gap-0" : ""}`}>
            <svg
              className="w-3.5 h-3.5 text-gray-400 shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
            <span className={`ml-1.5 ${isCollapsed ? "md:sr-only" : ""}`}>Feedback</span>
          </div>
          <span
            className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold border transition-colors ${feedbackBadgeClass} ${
              isCollapsed ? "md:px-1 md:py-0 md:text-[9px] md:leading-tight" : ""
            }`}
          >
            {pendingFeedbackCount}
          </span>
        </div>
      </div>
    </aside>
  );
}
