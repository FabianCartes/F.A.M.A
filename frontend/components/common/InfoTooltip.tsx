"use client";

import React, { useState, useRef, useEffect } from "react";

export interface InfoTooltipProps {
  id: string;
  title: string;
  impact: string;
  usage: string;
  keyPoints?: string[];
  className?: string;
  position?: "auto" | "top" | "bottom";
  align?: "auto" | "center" | "left" | "right";
}

export default function InfoTooltip({
  id,
  title,
  impact,
  usage,
  keyPoints = [],
  className = "",
  position = "auto",
  align = "auto",
}: InfoTooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [computedPlacement, setComputedPlacement] = useState<{
    vertical: "top" | "bottom";
    horizontal: "center" | "left" | "right";
  }>({
    vertical: position === "auto" ? "top" : position,
    horizontal: align === "auto" ? "center" : align,
  });

  const tooltipId = `tooltip-${id}`;

  const show = () => setIsVisible(true);
  const hide = () => setIsVisible(false);

  useEffect(() => {
    if (!isVisible) return;

    let v: "top" | "bottom" = position === "auto" ? "top" : position;
    let h: "center" | "left" | "right" = align === "auto" ? "center" : align;

    if (triggerRef.current && (position === "auto" || align === "auto")) {
      const rect = triggerRef.current.getBoundingClientRect();
      const tooltipWidth = 288;
      const tooltipHeight = 220;

      const mainEl = triggerRef.current.closest("main");
      const safeLeft = (mainEl ? mainEl.getBoundingClientRect().left : 0) + 16;
      const safeRight =
        (mainEl
          ? mainEl.getBoundingClientRect().right
          : typeof window !== "undefined"
          ? window.innerWidth
          : 1024) - 16;
      const safeTop = (mainEl ? mainEl.getBoundingClientRect().top : 0) + 10;

      if (position === "auto") {
        if (rect.top - safeTop < tooltipHeight) {
          v = "bottom";
        } else {
          v = "top";
        }
      }

      if (align === "auto") {
        const centerLeft = rect.left + rect.width / 2 - tooltipWidth / 2;
        if (centerLeft < safeLeft) {
          h = "left";
        } else if (centerLeft + tooltipWidth > safeRight) {
          h = "right";
        } else {
          h = "center";
        }
      }
    }

    setComputedPlacement({ vertical: v, horizontal: h });
  }, [isVisible, position, align]);

  const vClass = computedPlacement.vertical === "bottom" ? "top-full mt-2" : "bottom-full mb-2";
  const hClass =
    computedPlacement.horizontal === "left"
      ? "-left-2"
      : computedPlacement.horizontal === "right"
      ? "-right-2"
      : "left-1/2 -translate-x-1/2";

  const arrowVClass =
    computedPlacement.vertical === "bottom"
      ? "bottom-full -mb-[1px] border-b-[#2a2d39]"
      : "top-full -mt-[1px] border-t-[#2a2d39]";

  const arrowHClass =
    computedPlacement.horizontal === "left"
      ? "left-3.5"
      : computedPlacement.horizontal === "right"
      ? "right-3.5"
      : "left-1/2 -translate-x-1/2";

  return (
    <div
      className={`relative inline-flex items-center align-middle ${isVisible ? "z-40" : "z-10"} ${className}`}
      onMouseEnter={show}
      onMouseLeave={hide}
    >
      <button
        ref={triggerRef}
        type="button"
        aria-label={`Ver ayuda: ${id}`}
        aria-describedby={isVisible ? tooltipId : undefined}
        onFocus={show}
        onBlur={hide}
        className="w-3.5 h-3.5 rounded-full bg-[#23252e] hover:bg-[#323642] text-gray-400 hover:text-gray-200 text-[10px] font-bold inline-flex items-center justify-center leading-none transition-colors cursor-help focus:outline-none focus:ring-1 focus:ring-blue-500 select-none"
      >
        ?
      </button>

      {isVisible && (
        <div
          id={tooltipId}
          role="tooltip"
          className={`absolute z-50 ${vClass} ${hClass} w-72 p-3 bg-[#181a20] border border-[#2a2d39] rounded-lg shadow-2xl text-left pointer-events-none transition-all duration-150 animate-in fade-in`}
        >
          {/* Arrow */}
          <div className={`absolute ${arrowVClass} ${arrowHClass} border-4 border-transparent`} />

          <p className="text-[12px] font-semibold text-gray-100 mb-1 border-b border-[#2a2d39] pb-1">
            {title}
          </p>

          <div className="space-y-1.5 text-[11px] leading-relaxed">
            <p className="text-gray-300">
              <span className="font-semibold text-blue-400">Impacto: </span>
              {impact}
            </p>

            <p className="text-gray-300">
              <span className="font-semibold text-emerald-400">Uso: </span>
              {usage}
            </p>

            {keyPoints.length > 0 && (
              <div className="mt-1.5 pt-1.5 border-t border-[#23252e]">
                <ul className="list-disc pl-3.5 space-y-0.5 text-gray-400 text-[10px]">
                  {keyPoints.map((point, index) => (
                    <li key={index}>{point}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
