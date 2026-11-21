/**
 * Decorative loading placeholders. They are hidden from assistive technology:
 * the surrounding status text ("Cargando…") keeps announcing the state.
 */
export function Skeleton({ className = "" }: { className?: string }) {
  return <span aria-hidden="true" className={`fama-skeleton ${className}`} />;
}

/** A few text-like bars, for lists and tables that are still loading. */
export function SkeletonRows({ rows = 3, className = "" }: { rows?: number; className?: string }) {
  return (
    <span aria-hidden="true" data-testid="skeleton" className={`block space-y-2 ${className}`}>
      {Array.from({ length: rows }, (_, index) => (
        <span key={index} className="fama-skeleton h-9" style={{ width: `${100 - (index % 3) * 12}%` }} />
      ))}
    </span>
  );
}
