"use client";

import { useCallback, useEffect, useState } from "react";

/** A display-only deadline; the backend remains authoritative for quotas. */
export function useRetryAfter() {
  const [until, setUntil] = useState(0);
  const [remaining, setRemaining] = useState(0);
  const wait = useCallback((seconds: number) => {
    const bounded = Math.max(1, Math.min(86400, seconds));
    setUntil(Date.now() + bounded * 1000);
    setRemaining(bounded);
  }, []);
  useEffect(() => {
    if (!until) return;
    const refresh = () => {
      const next = Math.max(0, Math.ceil((until - Date.now()) / 1000));
      setRemaining(next);
      if (!next) window.clearInterval(timer);
    };
    const timer = window.setInterval(refresh, 1000);
    document.addEventListener("visibilitychange", refresh);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", refresh); };
  }, [until]);
  return [remaining, wait] as const;
}
