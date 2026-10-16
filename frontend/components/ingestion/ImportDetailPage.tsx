"use client";

import { useEffect, useState, type ReactNode } from "react";
import { z } from "zod";
import { importRequest, pageMetadataSchema } from "@/lib/api/datasetImports";

/** One mounted page per collection; never accumulates member arrays. */
export default function ImportDetailPage<T>({ token, endpoint, collection, label, schema, snapshot, renderItem }: {
  token: string; endpoint: string; collection: string; label: string; schema: z.ZodType<T>;
  snapshot?: string | null; renderItem: (item: T) => ReactNode;
}) {
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [position, setPosition] = useState(0);
  const [result, setResult] = useState<{ cursor: string | null; items: T[]; next: string | null; total: number } | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const cursor = cursors[position];
  const loaded = result?.cursor === cursor;
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      const url = cursor ? `${endpoint}?cursor=${encodeURIComponent(cursor)}` : endpoint;
      const response = await importRequest(token, url, { signal: controller.signal });
      const raw = await response.json();
      const metadata = pageMetadataSchema.parse(raw);
      const items = z.array(schema).max(200).parse(raw[collection]);
      if (snapshot && metadata.snapshot !== snapshot) throw new Error("La vista previa cambió. Actualiza la importación.");
      if (!controller.signal.aborted) {
        setResult({ cursor, items, next: metadata.next_cursor, total: metadata.total });
        setError("");
      }
    }
    void load().catch(reason => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "No se pudo cargar la página.");
    });
    return () => controller.abort();
  }, [token, endpoint, collection, schema, snapshot, cursor, attempt]);

  return <section aria-label={label}>
    <p>{label}: {loaded ? result.total : "cargando…"}</p>
    {error && <p role="alert">{error}</p>}
    {error && <button type="button" onClick={() => setAttempt(value => value + 1)}>Reintentar página de {label}</button>}
    <ul className="max-h-48 overflow-auto break-words">{loaded && result.items.map((item, index) => <li key={index}>{renderItem(item)}</li>)}</ul>
    <button type="button" disabled={!loaded || position === 0} onClick={() => setPosition(value => value - 1)}>Anterior página de {label}</button>
    <button type="button" disabled={!loaded || !result?.next} onClick={() => {
      if (!result?.next) return;
      setCursors([...cursors.slice(0, position + 1), result.next]);
      setPosition(value => value + 1);
    }}>Siguiente página de {label}</button>
  </section>;
}
