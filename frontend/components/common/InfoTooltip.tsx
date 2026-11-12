"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface InfoTooltipProps {
  id: string;
  title: string;
  impact: string;
  usage: string;
  keyPoints?: string[];
  className?: string;
}

const MAX_WIDTH = 288;
const MARGIN = 8;
const GAP = 8;

interface Placement { left: number; top: number; width: number; maxHeight: number; arrowLeft: number; below: boolean }

/**
 * Help bubble rendered in ``document.body`` with fixed coordinates clamped to the viewport,
 * so scrollable containers (modal tables) never clip it and it never leaves a phone screen.
 * Hover and keyboard focus show it; a tap pins it until a tap outside or Escape.
 */
export default function InfoTooltip({ id, title, impact, usage, keyPoints = [], className = "" }: InfoTooltipProps) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [placement, setPlacement] = useState<Placement | null>(null);
  const wrapperRef = useRef<HTMLSpanElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const isVisible = hovered || focused || pinned;
  const tooltipId = `tooltip-${id}`;

  const close = useCallback(() => { setHovered(false); setFocused(false); setPinned(false); }, []);

  const place = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1024;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 768;
    const width = Math.min(MAX_WIDTH, viewportWidth - 2 * MARGIN);
    const center = rect.left + rect.width / 2;
    const left = Math.min(Math.max(center - width / 2, MARGIN), viewportWidth - width - MARGIN);
    const height = tooltipRef.current?.offsetHeight || 220;
    const spaceAbove = rect.top - GAP - MARGIN;
    const spaceBelow = viewportHeight - rect.bottom - GAP - MARGIN;
    const below = spaceAbove < height && spaceBelow > spaceAbove;
    const maxHeight = Math.max(below ? spaceBelow : spaceAbove, 120);
    const top = below ? rect.bottom + GAP : Math.max(rect.top - GAP - Math.min(height, maxHeight), MARGIN);
    setPlacement({ left, top, width, maxHeight, below, arrowLeft: Math.min(Math.max(center - left, 12), width - 12) });
  }, []);

  useLayoutEffect(() => {
    if (!isVisible) return;
    place();
    // Measure again once the bubble has its real height.
    const frame = requestAnimationFrame(place);
    return () => cancelAnimationFrame(frame);
  }, [isVisible, place]);

  useEffect(() => {
    if (!isVisible) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node) && !tooltipRef.current?.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [isVisible, close, place]);

  return (
    <span ref={wrapperRef} className={`relative inline-flex items-center align-middle ${className}`}
      onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}>
      <button
        ref={triggerRef}
        type="button"
        aria-label={`Ver ayuda: ${id}`}
        aria-describedby={isVisible ? tooltipId : undefined}
        aria-expanded={isVisible}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onClick={(event) => { event.stopPropagation(); setPinned(value => !value); }}
        className="w-3.5 h-3.5 rounded-full bg-[#23252e] hover:bg-[#323642] text-gray-400 hover:text-gray-200 text-[10px] font-bold inline-flex items-center justify-center leading-none transition-colors cursor-help focus:outline-none focus:ring-1 focus:ring-blue-500 select-none"
      >
        ?
      </button>

      {isVisible && typeof document !== "undefined" && createPortal(
        <div
          ref={tooltipRef}
          id={tooltipId}
          role="tooltip"
          style={{
            position: "fixed",
            left: `${placement?.left ?? MARGIN}px`,
            top: `${placement?.top ?? MARGIN}px`,
            width: `${placement?.width ?? MAX_WIDTH}px`,
            maxHeight: placement ? `${placement.maxHeight}px` : undefined,
            visibility: placement ? "visible" : "hidden",
          }}
          className="z-[100] overflow-y-auto p-3 bg-[#181a20] border border-[#2a2d39] rounded-lg shadow-2xl text-left font-sans font-normal normal-case tracking-normal whitespace-normal"
        >
          {placement && <span aria-hidden="true" style={{ left: `${placement.arrowLeft}px` }}
            className={`absolute -translate-x-1/2 border-4 border-transparent ${placement.below
              ? "bottom-full -mb-[1px] border-b-[#2a2d39]" : "top-full -mt-[1px] border-t-[#2a2d39]"}`} />}

          <p className="text-[12px] font-semibold text-gray-100 mb-1 border-b border-[#2a2d39] pb-1">{title}</p>

          <div className="space-y-1.5 text-[11px] leading-relaxed">
            <p className="text-gray-300"><span className="font-semibold text-blue-400">Impacto: </span>{impact}</p>
            <p className="text-gray-300"><span className="font-semibold text-emerald-400">Uso: </span>{usage}</p>
            {keyPoints.length > 0 && (
              <div className="mt-1.5 pt-1.5 border-t border-[#23252e]">
                <ul className="list-disc pl-3.5 space-y-0.5 text-gray-400 text-[10px]">
                  {keyPoints.map((point, index) => <li key={index}>{point}</li>)}
                </ul>
              </div>
            )}
          </div>
        </div>,
        document.body,
      )}
    </span>
  );
}
