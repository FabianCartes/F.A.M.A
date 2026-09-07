"use client";

import { useState } from "react";
import Sidebar, { TabType } from "@/components/Sidebar";
import PredictionView from "@/components/views/PredictionView";
import DashboardView from "@/components/views/DashboardView";
import IngestionView from "@/components/views/IngestionView";
import TrainingView from "@/components/views/TrainingView";

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabType>("prediccion");

  return (
    <div className="flex h-screen bg-[#0e0f12] text-gray-100 overflow-hidden font-sans">
      {/* Sidebar Lateral Fija (Figuras 6.5 a 6.8) */}
      <Sidebar activeTab={activeTab} onSelectTab={(tab) => setActiveTab(tab)} />

      {/* Área Principal de Contenido */}
      <main className="flex-1 overflow-y-auto p-6 sm:p-8 max-w-7xl mx-auto w-full">
        {activeTab === "prediccion" && <PredictionView />}
        {activeTab === "dashboard" && <DashboardView onNavigate={(tab) => setActiveTab(tab)} />}
        {activeTab === "ingesta" && <IngestionView />}
        {activeTab === "entrenamiento" && <TrainingView />}
      </main>
    </div>
  );
}
