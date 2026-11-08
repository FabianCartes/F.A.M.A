'use client';

import { useEffect, useRef, useState, type RefObject } from 'react';
import { z } from 'zod';
import DatasetConfirmationDialog from './DatasetConfirmationDialog';
import { audioSchema, importBase, importRequest, pageMetadataSchema, saveDownload } from '@/lib/api/datasetImports';

export type AudioDataset = { kind: 'private' | 'shared'; id: string; name: string };
const facets = pageMetadataSchema.extend({ classes: z.array(z.string()), has_feedback: z.boolean() });
const privatePage = facets.extend({ files: z.array(audioSchema.extend({ is_feedback: z.boolean() })).max(200) });
const sharedPage = facets.extend({ files: z.array(z.object({
  name: z.string(), path: z.string(), class_name: z.string(), size_bytes: z.number().nonnegative(), is_feedback: z.boolean(),
})).max(200) });
type AudioRow = { key: string; name: string; className: string; bytes: number; sha?: string };
type AudioPage = z.infer<typeof facets> & { files: AudioRow[] };
type PageRequest = { filter: string; cursors: (string | null)[]; attempt: number };
const buttonClass = 'rounded-lg border border-[#373a46] px-3 py-2 transition-colors enabled:hover:bg-[#252830] enabled:hover:text-white disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-emerald-300';
function weight(bytes: number) {
  const gb = bytes > 1_000_000_000;
  return `${Math.trunc(bytes / (gb ? 1_000_000_000 : 1_000_000) * 100) / 100} ${gb ? 'GB' : 'MB'}`;
}

/** One presentation; private and shared adapters retain their existing read/download routes. */
export default function DatasetAudioDialog({ dataset, token, onClose, returnFocus }: {
  dataset: AudioDataset; token: string; onClose: () => void; returnFocus: RefObject<HTMLButtonElement | null>;
}) {
  const { id, kind, name } = dataset;
  const [request, setRequest] = useState<PageRequest>({ filter: 'all', cursors: [null], attempt: 0 });
  const [page, setPage] = useState<AudioPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [downloadError, setDownloadError] = useState('');
  const [downloading, setDownloading] = useState(false);
  const lifetime = useRef<AbortController | null>(null);
  const snapshot = useRef<string | number | null>(null);
  const endpoint = kind === 'private'
    ? `${importBase}/datasets/${encodeURIComponent(id)}/files`
    : `/api/ingestion/datasets/${encodeURIComponent(id)}/files`;

  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => controller.abort();
  }, [token, id, kind]);

  useEffect(() => {
    const controller = new AbortController();
    const cursor = request.cursors[request.cursors.length - 1];
    const query = new URLSearchParams({ browse: 'true', limit: '50' });
    if (cursor) query.set('cursor', cursor);
    if (request.filter === 'feedback') query.set('feedback', 'true');
    if (request.filter.startsWith('class:')) query.set('class_name', request.filter.slice(6));
    void importRequest(token, `${endpoint}?${query}`, { signal: controller.signal })
      .then(response => response.json())
      .then(raw => {
        if (controller.signal.aborted) return;
        let result: AudioPage;
        if (kind === 'private') {
          const parsed = privatePage.parse(raw);
          result = { ...parsed, files: parsed.files.map(file => ({ key: file.id,
            name: file.original_path.split('/').pop() || 'audio.wav', className: file.class_name,
            bytes: file.size_bytes, sha: file.sha256 })) };
        } else {
          const parsed = sharedPage.parse(raw);
          result = { ...parsed, files: parsed.files.map(file => ({ key: file.path, name: file.name,
            className: file.class_name, bytes: file.size_bytes })) };
        }
        if (cursor && result.snapshot !== snapshot.current) throw new Error('El dataset cambió. Consulta de nuevo la primera página.');
        if (result.next_cursor && request.cursors.includes(result.next_cursor)) throw new Error('El listado no avanzó. Consulta de nuevo la primera página.');
        snapshot.current = result.snapshot;
        setPage(result);
      })
      .catch(reason => {
        if (!controller.signal.aborted) setError(reason instanceof z.ZodError
          ? 'El servidor devolvió un listado de audios no válido.'
          : reason instanceof Error ? reason.message : 'No se pudo consultar el listado.');
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, endpoint, kind, request]);

  function navigate(next: PageRequest) {
    setLoading(true); setError(''); setDownloadError(''); setRequest(next);
  }
  async function download(file: AudioRow) {
    const controller = lifetime.current;
    if (kind !== 'private' || !file.sha || downloading || !controller || controller.signal.aborted) return;
    setDownloading(true); setDownloadError('');
    try {
      const response = await importRequest(token, `${endpoint}/${encodeURIComponent(file.sha)}`, { signal: controller.signal });
      if (!controller.signal.aborted) await saveDownload(response, file.name);
    } catch (reason) {
      if (!controller.signal.aborted) setDownloadError(reason instanceof Error ? reason.message : 'No se pudo descargar el audio.');
    } finally { if (!controller.signal.aborted) setDownloading(false); }
  }

  return <DatasetConfirmationDialog title={`Consultar audios · ${name}`} onClose={onClose} returnFocus={returnFocus} wide
    headerAction={<button type="button" className={`${buttonClass} shrink-0`} onClick={onClose}>Cerrar consulta</button>}>
    <div className="flex flex-wrap items-center gap-3">
      <label className="flex items-center gap-2">Clase
        <select aria-label="Clase" value={request.filter} disabled={loading || !page}
          className="max-w-full rounded-lg border border-[#373a46] bg-[#121316] px-3 py-2 text-gray-200 focus-visible:outline-2 focus-visible:outline-emerald-300"
          onChange={event => navigate({ filter: event.target.value, cursors: [null], attempt: 0 })}>
          <option value="all">Todas las clases</option>
          {page?.classes.map(item => <option key={item} value={`class:${item}`}>{item}</option>)}
          {page?.has_feedback && <option value="feedback">Retroalimentación (audios incorporados)</option>}
        </select>
      </label>
      <span className="text-xs text-gray-400">{kind === 'private' ? 'Selecciona un audio para descargarlo.' : 'Audios compartidos: solo consulta.'}</span>
    </div>
    {page?.has_feedback && <p className="text-xs text-gray-400">Retroalimentación agrupa audios ya incorporados; la clase original se conserva.</p>}
    {loading ? <p role="status">Consultando audios…</p> : error ? <div className="space-y-3">
      <p role="alert">No se pudieron consultar los audios: {error}</p>
      <button type="button" className={buttonClass} onClick={() => navigate({ ...request, attempt: request.attempt + 1 })}>Reintentar</button>
      {request.cursors.length > 1 && <button type="button" className={buttonClass} onClick={() => navigate({ ...request, cursors: [null] })}>Volver a la primera página</button>}
    </div> : page && <>
      <div className="max-h-[45vh] overflow-auto rounded-lg border border-[#23252e]">
        <table aria-label="Audios del dataset" className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-[#1c1e24] text-gray-400"><tr>
            <th className="px-3 py-3 font-medium">Audio</th><th className="px-3 py-3 font-medium">Clase</th><th className="px-3 py-3 font-medium">Tamaño</th>
          </tr></thead>
          <tbody className="divide-y divide-[#23252e]">{page.files.map(file => <tr key={file.key} className="hover:bg-[#1c1e24]/40">
            <td className="max-w-xs break-words px-3 py-3">{kind === 'private'
              ? <button type="button" aria-label={`Descargar ${file.name}`} disabled={downloading}
                className="text-left text-emerald-400 underline-offset-2 hover:text-emerald-200 hover:underline disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-emerald-300" onClick={() => void download(file)}>{file.name}</button>
              : <span className="text-gray-200">{file.name}</span>}</td>
            <td className="px-3 py-3 text-gray-300">{file.className}</td><td className="whitespace-nowrap px-3 py-3 font-mono text-gray-400">{weight(file.bytes)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      {page.files.length === 0 && <p>{request.filter === 'all' ? 'No hay audios en este dataset.' : 'No hay audios para este filtro.'}</p>}
    </>}
    {downloadError && <p role="alert">{downloadError}</p>}
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#23252e] pt-4">
      {!loading && !error && page && <span className="text-xs text-gray-400">Página {request.cursors.length} · {page.total} {page.total === 1 ? 'audio' : 'audios'}</span>}
      <div className="ml-auto flex gap-2">
        <button type="button" className={buttonClass} disabled={loading || request.cursors.length === 1}
          onClick={() => navigate({ ...request, cursors: request.cursors.slice(0, -1) })}>Anterior</button>
        <button type="button" className={buttonClass} disabled={loading || !!error || !page?.next_cursor}
          onClick={() => { if (page?.next_cursor) navigate({ ...request, cursors: [...request.cursors, page.next_cursor] }); }}>Siguiente</button>
      </div>
    </div>
  </DatasetConfirmationDialog>;
}
