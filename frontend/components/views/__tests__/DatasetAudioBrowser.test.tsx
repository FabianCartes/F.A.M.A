import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useRef, useState } from 'react';
import IngestionView from '../IngestionView';
import DatasetAudioDialog from '@/components/ingestion/DatasetAudioDialog';

const originalFetch = global.fetch;
afterEach(() => { cleanup(); global.fetch = originalFetch; vi.restoreAllMocks(); });
const privateBase = '/api/ingestion/imports/datasets/private-id/files';
const sharedBase = '/api/ingestion/datasets/Compartido/files';
type Kind = 'private' | 'shared';
// Historical local audio consumers survive until d/e, outside the ingestion inventory.
function HistoricalAudioConsumer() {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return <><button ref={trigger} onClick={() => setOpen(true)}>Consultar audios locales históricos</button>
    {open && <DatasetAudioDialog dataset={{ kind: 'private', id: 'private-id', name: 'Colección privada' }}
      returnFocus={trigger} onClose={() => setOpen(false)} />}</>;
}
function renderConsumer(kind: Kind = 'private') {
  return render(kind === 'private' ? <HistoricalAudioConsumer /> : <IngestionView />);
}
function row(kind: Kind, name = 'canto.wav', className = 'Aves') {
  return kind === 'private'
    ? { id: name, original_path: `${className}/${name}`, relative_path: `${className}/${name}`, class_name: className, sha256: 'hash', size_bytes: 2_500_000, duplicate: false, is_feedback: false }
    : { name, path: `datasets/Compartido/${className}/${name}`, class_name: className, size_bytes: 2_500_000, is_feedback: false };
}
function page(kind: Kind, changes: Record<string, unknown> = {}) {
  return { files: [row(kind)], classes: ['Aves', 'Motor', 'Retroalimentación'], has_feedback: true,
    total: 51, next_cursor: 'next-page', snapshot: kind === 'private' ? 7 : 'inventory', ...changes };
}
function mockHttp(read?: (kind: Kind, url: URL, init?: RequestInit) => Promise<Response>) {
  const reads: URL[] = [], downloads: string[] = [];
  global.fetch = vi.fn(async (input, init) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname === privateBase || url.pathname === sharedBase) {
      reads.push(url);
      const kind = url.pathname === privateBase ? 'private' : 'shared';
      return read ? read(kind, url, init) : Response.json(page(kind));
    }
    if (url.pathname === `${privateBase}/hash`) { downloads.push(url.pathname); return new Response('audio'); }
    if (url.pathname.endsWith('/datasets')) return Response.json({ datasets: [{ id: 'Compartido', name: 'Compartido', file_count: 51, local_file_count: 0, total_size_bytes: 10 }] });
    if (url.pathname.endsWith('/status')) return Response.json({ connected: false, bucket: '', total_objects: 0, total_bytes: 0 });
    return Response.json([]);
  });
  return { reads, downloads };
}
async function open(kind: Kind) {
  const name = kind === 'private' ? 'Colección privada' : 'Compartido';
  const trigger = kind === 'private' ? screen.getByRole('button', { name: 'Consultar audios locales históricos' })
    : within(await screen.findByRole('table', { name: 'Inventario de datasets' })).getByRole('button', { name: 'Ver archivos' });
  trigger.focus(); fireEvent.click(trigger);
  const dialog = await screen.findByRole('dialog', { name: `Consultar audios · ${name}` });
  await within(dialog).findByRole('table', { name: 'Audios del dataset' });
  return { dialog, trigger };
}

it.each<Kind>(['private', 'shared'])('closes the audio consultation from the upper-right header for %s', async kind => {
  mockHttp(); renderConsumer(kind);
  const { dialog, trigger } = await open(kind);
  const close = within(dialog).getByRole('button', { name: 'Cerrar consulta' });
  const header = within(dialog).getByRole('heading', { level: 2 }).parentElement!;
  expect(header.tagName).toBe('HEADER');
  expect(header.className).toContain('justify-between');
  expect(header.lastElementChild).toBe(close);
  expect(dialog.querySelectorAll('button').item(0)).toBe(close);
  expect(document.activeElement).toBe(close);
  fireEvent.click(close);
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

it.each<Kind>(['private', 'shared'])('uses the existing modal and filtered server pages for %s', async kind => {
  const { reads } = mockHttp(async (source, url) => Response.json(page(source, url.searchParams.has('class_name')
    ? { total: 1, next_cursor: null }
    : url.searchParams.has('cursor') ? { files: [row(source, 'segundo.wav', 'Motor')], next_cursor: null } : {})));
  renderConsumer(kind);
  const { dialog, trigger } = await open(kind);
  expect(dialog.getAttribute('aria-modal')).toBe('true');
  expect(dialog.className).toContain('bg-[#16171b]');
  expect(within(dialog).getAllByRole('columnheader').map(item => item.textContent)).toEqual(['Audio', 'Clase', 'Tamaño']);
  expect(within(dialog).getByText('2.5 MB')).toBeDefined();
  expect(reads[0].searchParams.get('browse')).toBe('true');
  expect(reads[0].searchParams.get('limit')).toBe('50');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Siguiente' }));
  await within(dialog).findByText('segundo.wav');
  expect(reads.at(-1)?.searchParams.get('cursor')).toBe('next-page');
  expect(within(dialog).getByText('Página 2 · 51 audios')).toBeDefined();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Anterior' }));
  await within(dialog).findByText('canto.wav');
  expect(reads.at(-1)?.searchParams.has('cursor')).toBe(false);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Siguiente' }));
  await within(dialog).findByText('segundo.wav');
  const selector = within(dialog).getByRole('combobox', { name: 'Clase' });
  fireEvent.change(selector, { target: { value: 'class:Aves' } });
  await within(dialog).findByText('Página 1 · 1 audio');
  expect(reads.at(-1)?.searchParams.get('class_name')).toBe('Aves');
  expect(reads.at(-1)?.searchParams.has('cursor')).toBe(false);
  expect(within(selector).getByRole('option', { name: 'Motor' })).toBeDefined();
  expect((within(dialog).getByRole('button', { name: 'Anterior' }) as HTMLButtonElement).disabled).toBe(true);
  const close = within(dialog).getByRole('button', { name: 'Cerrar consulta' });
  const last = kind === 'private' ? within(dialog).getByRole('button', { name: 'Descargar canto.wav' }) : selector;
  close.focus(); fireEvent.keyDown(close, { key: 'Tab', shiftKey: true });
  expect(document.activeElement).toBe(last);
  fireEvent.keyDown(last, { key: 'Tab' }); expect(document.activeElement).toBe(close);
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).toBeNull(); expect(document.activeElement).toBe(trigger);
});

it('separates the virtual feedback group from a real identically named class', async () => {
  const { reads } = mockHttp(async (kind, url) => Response.json(page(kind, {
    files: [row(kind, 'incorporado.wav', 'Aves')], total: 1, next_cursor: null,
    has_feedback: url.searchParams.get('class_name') !== 'Motor',
  })));
  renderConsumer(); const { dialog } = await open('private');
  const selector = within(dialog).getByRole('combobox', { name: 'Clase' });
  const virtual = within(selector).getByRole('option', { name: 'Retroalimentación (audios incorporados)' }) as HTMLOptionElement;
  fireEvent.change(selector, { target: { value: virtual.value } });
  await waitFor(() => expect(reads.at(-1)?.searchParams.get('feedback')).toBe('true'));
  expect(reads.at(-1)?.searchParams.has('class_name')).toBe(false);
  expect(within(dialog).getByText('Aves', { selector: 'td' })).toBeDefined();
  fireEvent.change(selector, { target: { value: 'class:Retroalimentación' } });
  await waitFor(() => expect(reads.at(-1)?.searchParams.get('class_name')).toBe('Retroalimentación'));
  expect(reads.at(-1)?.searchParams.has('feedback')).toBe(false);
});

it('downloads historical local filenames through the existing SHA route, never shared rows', async () => {
  const { downloads } = mockHttp();
  const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:audio');
  const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const historical = renderConsumer(); const { dialog } = await open('private');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Descargar canto.wav' }));
  await waitFor(() => expect(click).toHaveBeenCalledOnce());
  expect(downloads).toEqual([`${privateBase}/hash`]); expect(create).toHaveBeenCalledOnce(); expect(revoke).toHaveBeenCalledWith('blob:audio');
  const [, options] = vi.mocked(global.fetch).mock.calls.find(([url]) => String(url).endsWith('/hash'))!;
  expect(new Headers(options?.headers).get('Authorization')).toBeNull();
  historical.unmount(); renderConsumer('shared');
  const shared = await open('shared');
  expect(within(shared.dialog).queryByRole('button', { name: /Descargar/ })).toBeNull();
  expect(within(shared.dialog).queryByRole('link')).toBeNull();
  fireEvent.click(within(shared.dialog).getByText('canto.wav'));
  expect(downloads).toHaveLength(1);
});

it('reports read failure, retries, distinguishes empty results and omits unknown feedback', async () => {
  let failed = true;
  mockHttp(async kind => failed
    ? Response.json({ detail: 'Listado temporalmente no disponible.' }, { status: 503 })
    : Response.json(page(kind, { files: [], classes: ['Aves'], has_feedback: false, total: 0, next_cursor: null })));
  renderConsumer(); fireEvent.click(screen.getByRole('button', { name: 'Consultar audios locales históricos' }));
  const dialog = await screen.findByRole('dialog');
  await within(dialog).findByText(/Listado temporalmente no disponible/);
  expect(within(dialog).queryByText('No hay audios en este dataset.')).toBeNull();
  failed = false; fireEvent.click(within(dialog).getByRole('button', { name: 'Reintentar' }));
  await within(dialog).findByText('No hay audios en este dataset.');
  expect(within(dialog).queryByRole('option', { name: /audios incorporados/ })).toBeNull();
  fireEvent.change(within(dialog).getByRole('combobox'), { target: { value: 'class:Aves' } });
  await within(dialog).findByText('No hay audios para este filtro.');
});

it('shows local download errors without removing audio or retrying automatically', async () => {
  mockHttp(); const fallback = global.fetch;
  global.fetch = vi.fn(async (input, init) => String(input).endsWith('/hash')
    ? Response.json({ detail: 'Audio local no disponible.' }, { status: 404 }) : fallback(input, init));
  renderConsumer(); const { dialog } = await open('private');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Descargar canto.wav' }));
  await within(dialog).findByText(/Audio local no disponible/);
  expect(within(dialog).getByRole('button', { name: 'Descargar canto.wav' })).toBeDefined();
  expect(vi.mocked(global.fetch).mock.calls.filter(([url]) => String(url).endsWith('/hash'))).toHaveLength(1);
});

it('ignores a late page response after close and releases the inert background', async () => {
  let finish!: (value: Response) => void;
  mockHttp(() => new Promise(resolve => { finish = resolve; }));
  const view = renderConsumer();
  fireEvent.click(screen.getByRole('button', { name: 'Consultar audios locales históricos' }));
  const dialog = await screen.findByRole('dialog');
  await waitFor(() => expect(finish).toBeTypeOf('function'));
  expect(within(dialog).getByRole('status').textContent).toBe('Consultando audios…');
  expect(view.container.hasAttribute('inert')).toBe(true);
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(view.container.hasAttribute('inert')).toBe(false);
  await act(async () => { finish(Response.json(page('private'))); });
  expect(screen.queryByRole('dialog')).toBeNull(); expect(screen.queryByText('canto.wav')).toBeNull();
});
