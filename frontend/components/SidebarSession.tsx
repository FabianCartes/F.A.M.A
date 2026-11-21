"use client";

import { useOptionalWebSession, useOptionalWebSessionLogout } from "./auth/SessionBoundary";

export default function SidebarSession({ isCollapsed, onToggleCollapsed }: {
  isCollapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  const user = useOptionalWebSession();
  const logout = useOptionalWebSessionLogout();
  if (!user || !logout) return null;

  const icon = <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM5 21v-2a7 7 0 0114 0v2" />
  </svg>;

  const initials = user.nombre_completo.split(/\s+/).filter(Boolean).slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";

  return <section aria-label="Sesión actual" className={`min-w-0 rounded-xl border border-[#1e2030] bg-[#10111b] p-3 text-gray-400 ${
    isCollapsed ? "md:p-0 md:border-transparent md:bg-transparent" : ""}`}>
    {isCollapsed && <button type="button" onClick={onToggleCollapsed}
      aria-label="Mostrar sesión de usuario" title="Mostrar sesión de usuario" aria-expanded={false}
      className="hidden md:flex h-9 w-full items-center justify-center rounded-lg hover:text-white hover:bg-[#151622] focus-visible:ring-1 focus-visible:ring-blue-500">
      {icon}
    </button>}
    <div data-session-details className={isCollapsed ? "md:hidden" : ""}>
      <div className="flex items-center gap-2.5 min-w-0">
        <span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#2b2350] font-heading text-xs font-bold text-purple-200">
          {initials}
        </span>
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold text-gray-100" title={user.nombre_completo}>{user.nombre_completo}</p>
          <p className="truncate text-[11px]" title={user.rol}>{user.rol}</p>
        </div>
      </div>
      <button type="button" onClick={logout}
        className="mt-3 w-full rounded-lg border border-[#2e323e] px-2 py-2 text-[11px] font-semibold text-gray-300 hover:text-white hover:bg-[#151622] focus-visible:ring-1 focus-visible:ring-blue-500">
        Cerrar sesión
      </button>
    </div>
  </section>;
}
