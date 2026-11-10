import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import DatasetImportPanel from '@/components/ingestion/DatasetImportPanel';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each([
  [6442450944, 10737418240, 100663296, ['ZIP: hasta 6,44 GB', 'Contenido descomprimido: hasta 10,73 GB', 'Cada audio WAV: hasta 100,66 MB']],
  [1000000000, 1000000001, 1000000, ['ZIP: hasta 1000 MB', 'Contenido descomprimido: hasta 1 GB', 'Cada audio WAV: hasta 1 MB']],
])('summarizes instructions and shows only weight limits with decimal MB/GB (%s)', async (zip, expanded, audio, expected) => {
  const fetcher = vi.fn(async (input: string) => {
    const path = new URL(input, 'http://localhost').pathname;
    if (path.endsWith('/access')) return Response.json({ development_mode: true });
    if (path.endsWith('/limits')) return Response.json({ received_bytes: zip, expanded_bytes: expanded,
      audio_bytes: audio, entries: 2000, depth: 12, path_bytes: 240, audio_seconds: 600,
      validation_seconds: 900, concurrent_imports: 4, ttl_seconds: 86400, free_bytes: 536870912 });
    return Response.json({ imports: [], next_cursor: null, total: 0, snapshot: 'empty' });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<DatasetImportPanel />);
  fireEvent.click(screen.getByRole('button', { name: 'Importar dataset' }));
  const limits = await screen.findByRole('list', { name: 'Límites de peso' });
  expect(within(limits).getAllByRole('listitem').map(item => item.textContent)).toEqual(expected);
  expect(screen.getByRole('list', { name: 'Cómo preparar el ZIP' })).toBeDefined();
  expect(screen.getByText(/se importará automáticamente solo si supera la validación/)).toBeDefined();
  expect(screen.getByText(/Importar no inicia preparación ni entrenamiento/)).toBeDefined();
  const dialog = screen.getByRole('dialog');
  expect(dialog.textContent).not.toMatch(/Límites del servidor|profundidad|rutas 240|validación 900|Temporales:|reserva libre:|operación de almacenamiento simultánea/);
  expect(fetcher.mock.calls).toHaveLength(3);
});
