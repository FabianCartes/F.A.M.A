"use client";

import { useState } from "react";
import AppShell from "@/components/shell/AppShell";
import Sidebar, { TabType } from "@/components/Sidebar";
import PredictionView from "@/components/views/PredictionView";
import DashboardView from "@/components/views/DashboardView";
import IngestionView from "@/components/views/IngestionView";
import TrainingView from "@/components/views/TrainingView";

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabType>("prediccion");

  return (
    <AppShell
      sidebar={(actions) => (
        <Sidebar
          activeTab={activeTab}
          onSelectTab={(tab) => {
            setActiveTab(tab);
            actions.closeSidebar();
          }}
          isCollapsed={actions.isSidebarCollapsed}
          onToggleCollapsed={actions.toggleSidebarCollapsed}
        />
      )}
    >
      {activeTab === "prediccion" && <PredictionView />}
      {activeTab === "dashboard" && <DashboardView onNavigate={setActiveTab} />}
      {activeTab === "ingesta" && (
        <IngestionView
          onNavigate={(view) => {
            if (view === "predict") {
              setActiveTab("prediccion");
            } else if (
              view === "dashboard" ||
              view === "ingesta" ||
              view === "entrenamiento" ||
              view === "prediccion"
            ) {
              setActiveTab(view);
            }
          }}
        />
      )}
      {activeTab === "entrenamiento" && <TrainingView />}
    </AppShell>
  );
}
