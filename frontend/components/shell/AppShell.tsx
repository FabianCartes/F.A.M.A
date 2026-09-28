"use client";

import { useCallback, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";

const DESKTOP_QUERY = "(min-width: 768px)";
const COLLAPSED_KEY = "fama:sidebar-collapsed";

const collapsedListeners = new Set<() => void>();

let collapsedSnapshot = false;

function readCollapsedPreference(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "true";
  } catch {
    return collapsedSnapshot;
  }
}

function writeCollapsedPreference(next: boolean) {
  collapsedSnapshot = next;
  try {
    window.localStorage.setItem(COLLAPSED_KEY, String(next));
  } catch {
    /* storage unavailable: the preference stays in memory for this session */
  }
  collapsedListeners.forEach((listener) => listener());
}

function subscribeToCollapsedPreference(onStoreChange: () => void) {
  collapsedListeners.add(onStoreChange);
  window.addEventListener("storage", onStoreChange);
  return () => {
    collapsedListeners.delete(onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

export interface SidebarActions {
  closeSidebar: () => void;
  isSidebarCollapsed: boolean;
  toggleSidebarCollapsed: () => void;
}

interface AppShellProps {
  sidebar: (actions: SidebarActions) => ReactNode;
  onNavigate?: () => void;
  children: ReactNode;
}

export default function AppShell({ sidebar, onNavigate, children }: AppShellProps) {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const isSidebarCollapsed = useSyncExternalStore(
    subscribeToCollapsedPreference,
    readCollapsedPreference,
    () => false,
  );

  const closeSidebar = useCallback(() => {
    setIsSidebarOpen(false);
  }, []);

  const toggleSidebarCollapsed = useCallback(() => {
    writeCollapsedPreference(!readCollapsedPreference());
  }, []);

  const handleNavigate = useCallback(() => {
    setIsSidebarOpen(false);
    onNavigate?.();
  }, [onNavigate]);

  useEffect(() => {
    if (!isSidebarOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsSidebarOpen(false);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isSidebarOpen]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(DESKTOP_QUERY);
    const handleChange = () => setIsSidebarOpen(false);
    query.addEventListener("change", handleChange);
    return () => query.removeEventListener("change", handleChange);
  }, []);

  return (
    <div className="flex h-dvh overflow-hidden bg-[#0e0f12] font-sans text-gray-100">
      <div
        data-testid="app-shell-scrim"
        aria-hidden={!isSidebarOpen}
        onClick={closeSidebar}
        className={`fixed inset-0 z-30 bg-black/70 backdrop-blur-sm transition-opacity duration-200 md:hidden ${
          isSidebarOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />

      <div
        id="app-sidebar"
        className={`fixed inset-y-0 left-0 z-50 shrink-0 h-full transition-[width,transform] duration-200 ease-out md:relative md:z-10 md:transition-[width] ${
          isSidebarCollapsed ? "w-56 md:w-16" : "w-56"
        } ${
          isSidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        }`}
      >
        {sidebar({ closeSidebar: handleNavigate, isSidebarCollapsed, toggleSidebarCollapsed })}
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="relative z-40 flex items-center gap-3 border-b border-[#1f2128] bg-[#121316] px-3 py-2 md:hidden">
          <button
            type="button"
            onClick={() => setIsSidebarOpen((open) => !open)}
            aria-label={isSidebarOpen ? "Cerrar menú" : "Abrir menú"}
            aria-expanded={isSidebarOpen}
            aria-controls="app-sidebar"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-[#2e323e] bg-[#1d1f26] text-gray-200 transition-colors hover:bg-[#18191e] focus:outline-none focus-visible:border-blue-500"
          >
            {isSidebarOpen ? (
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 6l12 12M18 6L6 18" />
              </svg>
            ) : (
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7h16M4 12h16M4 17h16" />
              </svg>
            )}
          </button>
          <span className="font-heading text-sm font-bold tracking-tight text-white">F.A.M.A.</span>
        </header>

        <main className="min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-4 sm:p-6 lg:p-8">
          <div className="mx-auto w-full max-w-7xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
