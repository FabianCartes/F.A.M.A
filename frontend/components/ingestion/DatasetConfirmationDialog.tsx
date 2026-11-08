'use client';

import { useEffect, useId, useRef, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';

/** Shared app dialog shell; confirmations keep their compact default layout. */
export default function DatasetConfirmationDialog({ title, onClose, returnFocus, children, wide = false }: {
  title: string;
  onClose: () => void;
  returnFocus: RefObject<HTMLButtonElement | null>;
  children: ReactNode;
  wide?: boolean;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current!;
    const background = Array.from(document.body.children).filter(element => !element.contains(dialog));
    const inertStates = background.map(element => element.hasAttribute('inert'));
    const overflow = document.body.style.overflow;
    background.forEach(element => element.setAttribute('inert', ''));
    document.body.style.overflow = 'hidden';
    const controls = () => Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), input:not(:disabled), a[href]'));
    controls()[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); }
      if (event.key !== 'Tab') return;
      const elements = controls();
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    const onFocus = (event: FocusEvent) => {
      if (event.target instanceof Node && !dialog.contains(event.target)) controls()[0]?.focus();
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('focusin', onFocus);
    const trigger = returnFocus.current;
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('focusin', onFocus);
      background.forEach((element, index) => { if (!inertStates[index]) element.removeAttribute('inert'); });
      document.body.style.overflow = overflow;
      trigger?.focus();
    };
  }, [onClose, returnFocus]);
  return createPortal(<div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4">
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} className={`w-full ${wide ? "max-w-3xl max-h-[85vh] overflow-y-auto" : "max-w-lg"} space-y-4 rounded-xl border border-[#373a46] bg-[#16171b] p-6 text-sm text-gray-300 shadow-2xl`}>
      <h2 id={titleId} className="text-lg font-semibold text-white">{title}</h2>
      {children}
    </div>
  </div>, document.body);
}
