"use client";

/** Rows shown per page in the curation queue and the incorporated audio record. */
export const PAGE_SIZE = 20;

/**
 * Previous/next controls for offset pages read with PAGE_SIZE + 1 rows: the
 * extra row only reveals whether a next page exists and is never rendered.
 * Renders nothing when every row fits in the first page.
 */
export default function PageControls({ offset, hasNext, disabled = false, onChange }: {
  offset: number;
  hasNext: boolean;
  disabled?: boolean;
  onChange: (offset: number) => void;
}) {
  if (offset === 0 && !hasNext) return null;
  const button = "flex-1 sm:flex-none px-3 py-1.5 rounded-lg border border-[#23252e] bg-[#1c1e24] text-gray-300 hover:bg-[#23252e] disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer";
  return (
    <nav aria-label="Paginación" className="flex items-center justify-between gap-2 pt-3 text-xs">
      <button type="button" aria-label="Página anterior" className={button}
        disabled={disabled || offset === 0} onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}>
        ← Anterior
      </button>
      <span className="shrink-0 font-mono text-gray-400">Página {Math.floor(offset / PAGE_SIZE) + 1}</span>
      <button type="button" aria-label="Página siguiente" className={button}
        disabled={disabled || !hasNext} onClick={() => onChange(offset + PAGE_SIZE)}>
        Siguiente →
      </button>
    </nav>
  );
}
