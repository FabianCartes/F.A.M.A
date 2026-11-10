"use client";

import { useState } from "react";
import AppShell from "@/components/shell/AppShell";
import Sidebar, { TabType } from "@/components/Sidebar";
import PredictionView from "@/components/views/PredictionView";
import DashboardView from "@/components/views/DashboardView";
import IngestionView from "@/components/views/IngestionView";
import TrainingView from "@/components/views/TrainingView";
import SessionBoundary, { useWebSession } from "@/components/auth/SessionBoundary";
import AccountView from "@/components/account/AccountView";
import AdministrationView from "@/components/account/AdministrationView";

export default function Home() {
  return <SessionBoundary><Workspace /></SessionBoundary>;
}

function Workspace() {
  const { user } = useWebSession();
  const [activeTab, setActiveTab] = useState<TabType>("prediccion");

  return (
    <AppShell
      sidebar={(actions) => (
        <Sidebar
          activeTab={activeTab}
          role={user.rol}
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
          administrator={user.rol === "administrador"}
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
      {activeTab === "cuenta" && <AccountView />}
      {activeTab === "administracion" && (user.rol === "administrador" ? <AdministrationView /> : <AccountView />)}
    </AppShell>
  );
}
