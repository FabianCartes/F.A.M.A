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
  const [pendingFeedbackCount, setPendingFeedbackCount] = useState<number>(0);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/training/hardware`)
      .then((res) => (res.ok ? res.json() : null))
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
    <aside className="w-full h-full min-w-0 bg-[#121316] border-r border-[#1f2128] flex flex-col justify-between select-none">
      {/* Top Section: Logo & Nav */}
      <div className="min-w-0 min-h-0 overflow-y-auto">
        {/* Logo F.A.M.A. Header — the only asset is a 185x40 horizontal PNG, so the rail drops it */}
        <div
          className={`px-4 pt-4 pb-4 border-b border-[#1f2128]/60 ${isCollapsed ? "md:hidden" : ""}`}
        >
          <div className="flex items-center justify-center">
            <Image
              src="/F.A.M.A-sinFondoBlanco.png"
              alt="Logo F.A.M.A."
              width={185}
              height={40}
              unoptimized
              priority
              className="w-full max-w-[185px] h-auto object-contain"
            />
          </div>
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
                {isCollapsed && (
                  <span
                    aria-hidden="true"
                    className="hidden md:block pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 whitespace-nowrap rounded-md border border-[#2e323e] bg-[#1d1f26] px-2 py-1 text-[11px] text-gray-100 opacity-0 shadow-lg transition-opacity md:group-hover:opacity-100"
                  >
                    {item.label}
                  </span>
                )}
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
        <div className={`flex items-center justify-between ${isCollapsed ? "md:justify-center" : ""}`}>
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
          <span
            className={`px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-950/70 border border-green-700/60 text-green-400 ${
              isCollapsed ? "md:sr-only" : ""
            }`}
          >
            Conectado
          </span>
        </div>

        {/* Cómputo / Hardware Status */}
        <div className={`flex items-center justify-between ${isCollapsed ? "md:justify-center" : ""}`}>
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
          <span
            className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
              hw?.cuda_available
                ? "bg-emerald-950/70 border-emerald-700/60 text-emerald-400"
                : "bg-blue-950/70 border-blue-700/60 text-blue-400"
            } ${isCollapsed ? "md:sr-only" : ""}`}
          >
            {hw?.cuda_available
              ? `CUDA${hw.temperature_c ? ` · ${hw.temperature_c}°C` : ""}`
              : "CPU Host"}
          </span>
        </div>

        {/* Feedback / Notificaciones (RF_06) */}
        <div className={`flex items-center justify-between ${isCollapsed ? "md:justify-center" : ""}`}>
          <div className="relative flex items-center text-gray-400">
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
            <span className={`ml-1.5 ${isCollapsed ? "md:ml-0 md:sr-only" : ""}`}>Feedback</span>
          </div>
          <span
            className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold border transition-colors ${feedbackBadgeClass} ${
              isCollapsed
                ? "md:absolute md:top-1/2 md:-right-2.5 md:-translate-y-1/2 md:min-w-[16px] md:px-1 md:py-0 md:text-[9px] md:leading-4 md:text-center"
                : ""
            }`}
          >
            {pendingFeedbackCount}
          </span>
        </div>

        {/* Control de colapso del panel lateral — solo desde md, donde el rail es el modo compacto.
            En móvil el drawer off-canvas ya es la presentación comprimida, así que el control sería inerte. */}
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label={isCollapsed ? "Expandir panel lateral" : "Colapsar panel lateral"}
          aria-expanded={!isCollapsed}
          className={`group relative hidden md:flex w-full items-center gap-2 px-2 py-1.5 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-[#18191e] transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-blue-500 ${
            isCollapsed ? "md:justify-center md:gap-0 md:px-0 md:py-2" : ""
          }`}
        >
          <svg
            className="w-3.5 h-3.5 shrink-0 transition-transform"
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
          <span className={isCollapsed ? "md:sr-only" : ""}>
            {isCollapsed ? "Expandir" : "Colapsar"}
          </span>
          {isCollapsed && (
            <span
              aria-hidden="true"
              className="hidden md:block pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 whitespace-nowrap rounded-md border border-[#2e323e] bg-[#1d1f26] px-2 py-1 text-[11px] text-gray-100 opacity-0 shadow-lg transition-opacity md:group-hover:opacity-100"
            >
              Expandir
            </span>
          )}
        </button>
      </div>
    </aside>
  );
}
