const rawApiUrl = process.env.NEXT_PUBLIC_API_URL;

export const API_BASE_URL =
  rawApiUrl && rawApiUrl.trim() !== "" ? rawApiUrl.trim() : "";

// Only private API consumers notify this observer; legacy failures stay local.
const unauthorizedListeners = new Set<() => void>();
let sessionRevision = 0;
export function apiSessionRevision() { return sessionRevision; }
export function confirmApiSession() { sessionRevision += 1; }
export function onUnauthorized(listener: () => void) {
  unauthorizedListeners.add(listener);
  return () => { unauthorizedListeners.delete(listener); };
}
export function notifyUnauthorized(requestRevision: number) {
  if (requestRevision !== sessionRevision) return;
  sessionRevision += 1;
  unauthorizedListeners.forEach(listener => listener());
}
