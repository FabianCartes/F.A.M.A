"use client";

import { useState, useEffect } from "react";
import Image from "next/image";

export type TabType = "dashboard" | "ingesta" | "entrenamiento" | "prediccion";

interface SidebarProps {
  activeTab: TabType;
  onSelectTab: (tab: TabType) => void;
}

interface HardwareMini {
  cuda_available: boolean;
  temperature_c?: number | null;
}

export default function Sidebar({ activeTab, onSelectTab }: SidebarProps) {
  const [hw, setHw] = useState<HardwareMini | null>(null);

  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/training/hardware")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) setHw(data);
      })
      .catch(() => null);
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

  return (
    <aside className="w-56 shrink-0 bg-[#121316] border-r border-[#1f2128] flex flex-col justify-between h-screen sticky top-0 select-none z-20">
      {/* Top Section: Logo & Nav */}
      <div>
        {/* Logo F.A.M.A. Header */}
        <div className="px-4 pt-4 pb-4 border-b border-[#1f2128]/60">
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
        <nav className="p-3 space-y-1.5 mt-2">
          {navItems.map((item) => {
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                id={`nav-${item.id}`}
                type="button"
                onClick={() => onSelectTab(item.id)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium cursor-pointer transition-all ${
                  isActive
                    ? "bg-[#1d1f26] text-white border border-[#2e323e] shadow-sm"
                    : "text-gray-400 hover:text-gray-200 hover:bg-[#18191e]"
                }`}
              >
                <span className={isActive ? "text-white" : "text-gray-400"}>
                  {item.icon}
                </span>
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom Section: System Status Badges */}
      <div className="p-4 border-t border-[#1f2128] space-y-2 text-[11px]">
        {/* GCP Status */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-gray-400">
            <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            <span>GCP</span>
          </div>
          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-950/70 border border-green-700/60 text-green-400">
            Conectado
          </span>
        </div>

        {/* Cómputo / Hardware Status */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-gray-400">
            <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
            </svg>
            <span>{hw?.cuda_available ? "GPU" : "Cómputo"}</span>
          </div>
          <span
            className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
              hw?.cuda_available
                ? "bg-emerald-950/70 border-emerald-700/60 text-emerald-400"
                : "bg-blue-950/70 border-blue-700/60 text-blue-400"
            }`}
          >
            {hw?.cuda_available
              ? `CUDA${hw.temperature_c ? ` · ${hw.temperature_c}°C` : ""}`
              : "CPU Host"}
          </span>
        </div>

        {/* Feedback / Notificaciones */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-gray-400">
            <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>Feedback</span>
          </div>
          <span className="px-1.5 py-0.2 rounded-full text-[10px] font-bold bg-red-950/70 border border-red-700/60 text-red-400">
            12
          </span>
        </div>
      </div>
    </aside>
  );
}
