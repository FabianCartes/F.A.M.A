"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { z } from "zod";
import { datasetsPageSchema, importBase, importRequest, type ImportDataset } from "@/lib/api/datasetImports";
import DatasetExportPanel from "./DatasetExportPanel";

const buttonClass = "rounded-lg border border-emerald-800/60 bg-emerald-950/40 px-3 py-2 text-xs font-semibold text-emerald-400 hover:bg-emerald-900/50 transition-colors focus-visible:outline-2 focus-visible:outline-emerald-300 disabled:opacity-40 disabled:cursor-not-allowed";

export default function DatasetExportDialog({ sessionToken = "" }: { sessionToken?: string } = {}) {
  return <ExportDialog key={sessionToken} token={sessionToken} />;
}

function ExportDialog({ token }: { token: string }) {
  const [open, setOpen] = useState(false);
  const [activated, setActivated] = useState(false);
  const [datasets, setDatasets] = useState<ImportDataset[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [sessionRequired, setSessionRequired] = useState(false);
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const titleId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    async function load() {
      try {
        const response = await importRequest(token, `${importBase}/access`, { signal: controller.signal });
        const access = z.object({ development_mode: z.boolean(), authenticated: z.boolean().default(false), available: z.boolean().default(true), reason: z.string().optional() }).parse(await response.json());
        if (controller.signal.aborted) return;
        if (!access.available) throw new Error(access.reason ?? "El servicio ZIP no está disponible en este equipo.");
        const required = !access.development_mode && !access.authenticated && !token;
        setSessionRequired(required);
        if (required) return;
        const catalog = await importRequest(token, `${importBase}/datasets${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`, { signal: controller.signal });
        const page = datasetsPageSchema.parse(await catalog.json());
        if (!controller.signal.aborted) {
          setDatasets(page.datasets); setNextCursor(page.next_cursor);
        }
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "No se pudieron consultar los datasets.");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [open, token, reload, cursor]);

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previousOverflow = document.body.style.overflow;
    const background = Array.from(document.body.children).filter(element => !element.contains(dialog));
    const inertStates = background.map(element => element.hasAttribute("inert"));
    background.forEach(element => element.setAttribute("inert", ""));
    document.body.style.overflow = "hidden";
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(
      "button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], [tabindex='0']"
    ));
    focusable()[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
      if (event.key !== "Tab") return;
      const elements = focusable();
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    const onFocus = (event: FocusEvent) => {
      if (event.target instanceof Node && !dialog.contains(event.target)) focusable()[0]?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("focusin", onFocus);
    const trigger = triggerRef.current;
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("focusin", onFocus);
      background.forEach((element, index) => { if (!inertStates[index]) element.removeAttribute("inert"); });
      document.body.style.overflow = previousOverflow;
      trigger?.focus();
    };
  }, [open]);

  return <>
    <button ref={triggerRef} type="button" className={buttonClass + " w-full sm:w-auto"}
      aria-haspopup="dialog" aria-expanded={open} onClick={() => {
        setActivated(true); setLoading(true); setError(""); setOpen(true);
      }}>Descargar versión como ZIP</button>
    {activated && createPortal(<div data-testid="dataset-export-backdrop" style={{ display: open ? undefined : "none" }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={event => { if (event.target === event.currentTarget) setOpen(false); }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId}
        className="w-full max-w-3xl max-h-[90dvh] overflow-y-auto rounded-2xl border border-[#23252e] bg-[#16171b] text-xs text-gray-300 shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-[#23252e] bg-[#16171b] px-5 py-4">
          <h2 id={titleId} className="text-sm font-bold text-white">Descargar versión como ZIP</h2>
          <button type="button" className={buttonClass} aria-label="Cerrar exportación" onClick={() => setOpen(false)}>Cerrar</button>
        </div>
        <div className="p-5 space-y-4">
          <p>Descarga una versión sincronizada a tu equipo. Cerrar esta ventana no cancela la exportación.</p>
          {loading && <p role="status">Consultando datasets…</p>}
          {sessionRequired && <p role="status">Inicia sesión en F.A.M.A. para gestionar tus importaciones y exportaciones ZIP.</p>}
          {error && <p role="alert">{error}</p>}
          {error && <button type="button" className={buttonClass} disabled={loading} onClick={() => {
            setError(""); setLoading(true); setReload(value => value + 1);
          }}>Reintentar conexión</button>}
          {datasets && !sessionRequired && <>
            <div className="flex flex-wrap gap-2">
              <button type="button" className={buttonClass} disabled={loading || cursor === null} onClick={() => {
                setError(""); setLoading(true); setCursor(null);
              }}>Primera página de datasets</button>
              <button type="button" className={buttonClass} disabled={loading || !nextCursor || !!error} onClick={() => {
                setError(""); setLoading(true); setCursor(nextCursor);
              }}>Siguiente página de datasets</button>
            </div>
            <DatasetExportPanel token={token} datasets={datasets} />
          </>}
        </div>
      </div>
    </div>, document.body)}
  </>;
}
