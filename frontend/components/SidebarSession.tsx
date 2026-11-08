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

  return <section aria-label="Sesión actual" className="min-w-0 border-b border-[#1f2128] pb-3 mb-3 text-gray-400">
    {isCollapsed && <button type="button" onClick={onToggleCollapsed}
      aria-label="Mostrar sesión de usuario" title="Mostrar sesión de usuario" aria-expanded={false}
      className="hidden md:flex h-9 w-full items-center justify-center rounded-lg hover:text-white hover:bg-[#18191e] focus-visible:ring-1 focus-visible:ring-blue-500">
      {icon}
    </button>}
    <div data-session-details className={isCollapsed ? "md:hidden" : ""}>
      <div className="flex items-center gap-2 min-w-0">
        {icon}
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-gray-200" title={user.nombre_completo}>{user.nombre_completo}</p>
          <p className="truncate text-[11px]" title={user.rol}>{user.rol}</p>
        </div>
      </div>
      <button type="button" onClick={logout}
        className="mt-2 w-full rounded-lg border border-[#2e323e] px-2 py-1.5 text-[11px] hover:text-white hover:bg-[#18191e] focus-visible:ring-1 focus-visible:ring-blue-500">
        Cerrar sesión
      </button>
    </div>
  </section>;
}
