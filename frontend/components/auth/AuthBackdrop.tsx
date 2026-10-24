"use client";

import { memo, useSyncExternalStore } from "react";
import SlicedWaves from "@/components/backgrounds/SlicedWaves";

function snapshot() { return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false; }
function subscribe(listener: () => void) {
  const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  media?.addEventListener("change", listener);
  return () => media?.removeEventListener("change", listener);
}

export default memo(function AuthBackdrop({ paused = false }: { paused?: boolean }) {
  const reduced = useSyncExternalStore(subscribe, snapshot, () => true);
  if (reduced || paused) return null;
  return <div className="auth-waves" aria-hidden="true">
    <SlicedWaves color1="#cb49ff" color2="#ff5fa2" color3="#424aff" ribbons={5} spacing={12}
      perspective={0.8} blur={0.8} glow={1.65} position={0.69} mouseInteraction={true}
      barWidth={0.55} ribbonHeight={0.18} spread={0.12} curve={0.4} speed={0.35}
      brightness={1.05} rotation={-1} grain={0.09} fade={0.05} />
  </div>;
});
