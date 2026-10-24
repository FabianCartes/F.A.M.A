const rawApiUrl = process.env.NEXT_PUBLIC_API_URL;

export const API_BASE_URL =
  rawApiUrl && rawApiUrl.trim() !== "" ? rawApiUrl.trim().replace(/\/+$/, "") : "";

const unauthorizedListeners = new Set<() => void>();
let sessionGeneration = 0;

export function sameOriginUrl(url: string): void {
  const target = new URL(url, window.location.origin);
  if (target.origin !== window.location.origin || target.username || target.password ||
      !["https:", "http:"].includes(target.protocol)) {
    throw new Error("La API debe usar el mismo origen de la aplicación.");
  }
}

export function confirmApiSession(): void { sessionGeneration += 1; }

export function onUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener);
  return () => { unauthorizedListeners.delete(listener); };
}

/** Protected application requests: cookies only, same origin, no cached user data. */
export async function apiFetch(url: string, options?: RequestInit): Promise<Response> {
  sameOriginUrl(url);
  const generation = sessionGeneration;
  const response = await fetch(url, { ...options, credentials: "same-origin", cache: "no-store", redirect: "error" });
  if (response.status === 401 && generation === sessionGeneration) {
    sessionGeneration += 1;
    unauthorizedListeners.forEach((listener) => listener());
  }
  return response;
}
