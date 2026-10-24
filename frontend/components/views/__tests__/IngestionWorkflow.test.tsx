import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import IngestionView from '../IngestionView';

const localDataset = {
  id: 'AvesChilenas', name: 'AvesChilenas', classes: ['Chucao'],
  file_count: 2, local_file_count: 2, total_size_bytes: 2048,
  gcs_file_count: 0, gcs_size_bytes: 0, local_size_bytes: 2048,
  source: 'local', gcs_available: true, is_synced: false, sync_state: 'local_only',
  last_modified: null,
};
let datasets: Record<string, unknown>[];
let requests: { url: string; options?: RequestInit }[];
let limits: { max_file_bytes: number; max_batch_bytes: number };
let uploadResult: Record<string, unknown>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});

describe('Gestión de audios mediante formularios y HTTP', () => {
  beforeEach(() => {
    datasets = [localDataset];
    requests = [];
    limits = { max_file_bytes: 64 * 1024 * 1024, max_batch_bytes: 256 * 1024 * 1024 };
    uploadResult = { status: 'completed', uploaded: 1, skipped: 0, failed: 0, db_persisted: true, files: ['canto.wav'], errors: [] };
    vi.stubGlobal('fetch', vi.fn(async (input, options) => {
      const url = String(input);
      requests.push({ url, options });
      if (url.includes('/api/ingestion/upload')) return json(uploadResult);
      if (url.includes('/api/ingestion/preprocess')) return json({ status: 'completed', total_processed: 2, total_failed: 0, results: [] });
      if (url.includes('/api/ingestion/status')) return json({ connected: true, bucket: 'fama-pruebas', total_objects: 0, total_bytes: 0 });
      if (url.includes('/api/ingestion/datasets')) return json({ datasets, can_create_dataset: true, upload_limits: limits });
      if (url.includes('/api/feedback/')) return json([]);
      throw new Error(`Unexpected HTTP request: ${url}`);
    }));
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it('incorpora la corrección mostrando SQL confirmado, autores y GCS pendiente', async () => {
    const fallback = globalThis.fetch;
    let incorporated = false;
    vi.stubGlobal('fetch', vi.fn(async (input, options) => {
      const url = String(input);
      if (url.endsWith('/api/feedback/1/approve')) { incorporated = true; return json({
        status: 'approved', id_retroalimentacion: 1, destination_path: '/synthetic/feedback_1.wav',
        clase: 'Chucao', local_status: 'incorporated', sync_status: 'pending', db_persisted: true,
      }); }
      if (url.includes('/api/feedback/pending')) return json(incorporated ? [] : [{
        id_retroalimentacion: 1, id_prediccion: 1, dataset_name: 'AvesChilenas',
        ruta_audio_prueba: 'raw_audios/synthetic.wav', audio_filename: 'prueba.wav',
        etiqueta_predicha: 'Chucao', confianza: .8, fue_correcta: true,
        procesado: false, id_usuario: 2,
      }]);
      if (url.includes('/api/feedback/sync')) return json(incorporated ? [{
        id_retroalimentacion: 1, id_prediccion: 1, dataset_name: 'AvesChilenas',
        storage_class: 'Chucao', class_label: 'Chucao', local_status: 'incorporated',
        sync_status: 'pending', attempts: 0, error_code: null, db_persisted: true,
        proposed_by: 2, incorporated_by: 2, incorporated_at: '2026-10-23T00:00:00Z',
      }] : []);
      return fallback(input, options);
    }));
    await act(async () => { render(<IngestionView administrator={false} />); });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Incorporar al dataset' })); });
    const row = within(screen.getByRole('row', { name: /AvesChilenas.*Chucao.*Incorporado localmente/ }));
    expect(row.getByText('Registrado en PostgreSQL')).toBeDefined();
    expect(row.getByText('Pendiente de copia cloud')).toBeDefined();
    expect(row.getByText('Propuesto por cuenta #2 · Incorporado por cuenta #2')).toBeDefined();
  });

  it('distingue los audios locales de una nube vacía y no ofrece descargarlos', async () => {
    await act(async () => { render(<IngestionView />); });
    const row = within(screen.getByRole('row', { name: /AvesChilenas/ }));
    expect(row.getByRole('cell', { name: '0 audios 0 B' })).toBeDefined();
    expect(row.getByRole('cell', { name: '2 audios 2 KB' })).toBeDefined();
    expect(row.getByText('Solo local')).toBeDefined();
    fireEvent.click(row.getByRole('checkbox', { name: 'Seleccionar AvesChilenas' }));
    expect((screen.getByRole('button', { name: 'Descargar desde GCS' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Preprocesar audios locales' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('preprocesa explícitamente la selección local sin pedir una descarga', async () => {
    await act(async () => { render(<IngestionView />); });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Seleccionar AvesChilenas' }));
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Preprocesar audios locales' })); });

    const command = requests.find(request => request.url.endsWith('/api/ingestion/preprocess'));
    expect(command?.options?.method).toBe('POST');
    expect(JSON.parse(String(command?.options?.body))).toEqual({ datasets: ['AvesChilenas'] });
    expect(requests.some(request => request.url.endsWith('/api/ingestion/sync'))).toBe(false);
    expect(screen.getByText('Preprocesamiento completado: 2 audios preparados.')).toBeDefined();
    expect(screen.getByText((_, element) => element?.textContent?.replace(/\s/g, '') === 'TensoresPreprocesados2')).toBeDefined();
  });

  it('el investigador opera su inventario sin consultar estadísticas globales del bucket', async () => {
    await act(async () => { render(<IngestionView administrator={false} />); });

    expect(requests.some(request => request.url.endsWith('/api/ingestion/status'))).toBe(false);
    expect(screen.getByText('Acceso a datasets asignados')).toBeDefined();
    expect(screen.getByRole('row', { name: /AvesChilenas/ })).toBeDefined();
  });

  it('ofrece las clases exactas del dataset elegido y limpia la clase al cambiar de dataset', async () => {
    datasets = [
      { ...localDataset, classes: ['Canastero', 'Chucao'] },
      { ...localDataset, id: 'Motores', name: 'Motores', classes: ['Pistón'] },
    ];
    await act(async () => { render(<IngestionView />); });
    fireEvent.change(screen.getByLabelText('Dataset de destino'), { target: { value: 'AvesChilenas' } });
    const classes = screen.getByRole('combobox', { name: 'Clase de los audios' });
    expect(within(classes).getByRole('option', { name: 'Chucao' })).toBeDefined();
    expect(within(classes).getByRole('option', { name: 'Canastero' })).toBeDefined();
    expect(within(classes).queryByRole('option', { name: 'Pistón' })).toBeNull();
    fireEvent.change(classes, { target: { value: 'Chucao' } });
    fireEvent.change(screen.getByLabelText('Audios'), { target: { files: [new File(['test'], 'canto.wav')] } });
    fireEvent.change(screen.getByLabelText('Dataset de destino'), { target: { value: 'Motores' } });
    const nextClasses = screen.getByRole('combobox', { name: 'Clase de los audios' });
    expect(within(nextClasses).getByRole('option', { name: 'Pistón' })).toBeDefined();
    expect(within(nextClasses).queryByRole('option', { name: 'Chucao' })).toBeNull();
    expect((nextClasses as HTMLSelectElement).value).toBe('');
    expect((screen.getByRole('button', { name: 'Subir audios a GCS' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('respeta la clase exacta seleccionada cuando ya existen variantes históricas de mayúsculas', async () => {
    datasets = [{ ...localDataset, classes: ['Chucao', 'chucao'] }];
    await act(async () => { render(<IngestionView />); });
    fireEvent.change(screen.getByLabelText('Dataset de destino'), { target: { value: 'AvesChilenas' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Clase de los audios' }), { target: { value: 'chucao' } });
    fireEvent.change(screen.getByLabelText('Audios'), { target: { files: [new File(['test'], 'canto.wav')] } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Subir audios a GCS' })); });
    const command = requests.find(request => request.url.endsWith('/api/ingestion/upload'));
    expect((command?.options?.body as FormData).get('class_label')).toBe('chucao');
  });

  it.each(['  chucao  ', 'CHUCAO'])('reutiliza la clase existente si al añadir una clase se escribe %s', async label => {
    await act(async () => { render(<IngestionView />); });
    fireEvent.change(screen.getByLabelText('Dataset de destino'), { target: { value: 'AvesChilenas' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Clase de los audios' }), { target: { value: ':new:' } });
    fireEvent.change(screen.getByLabelText('Nombre de la nueva clase'), { target: { value: label } });
    fireEvent.change(screen.getByLabelText('Audios'), { target: { files: [new File(['test'], 'canto.wav')] } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Subir audios a GCS' })); });
    const command = requests.find(request => request.url.endsWith('/api/ingestion/upload'));
    expect((command?.options?.body as FormData).get('class_label')).toBe('Chucao');
  });

  it.each([
    { id: 'AvesChilenas', classes: [], label: 'Primera clase' },
    { id: ':new:', classes: ['Chucao'], label: 'Clase inicial' },
  ])('permite la primera clase de un dataset sin clases o nuevo ($id)', async ({ id, classes, label }) => {
    datasets = [{ ...localDataset, classes }];
    await act(async () => { render(<IngestionView />); });
    fireEvent.change(screen.getByLabelText('Dataset de destino'), { target: { value: id } });
    if (id === ':new:') fireEvent.change(screen.getByLabelText('Nombre del nuevo dataset'), { target: { value: 'NuevoDataset' } });
    fireEvent.change(screen.getByLabelText('Clase de los audios'), { target: { value: label } });
    fireEvent.change(screen.getByLabelText('Audios'), { target: { files: [new File(['test'], 'canto.wav')] } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Subir audios a GCS' })); });
    const command = requests.find(request => request.url.endsWith('/api/ingestion/upload'));
    expect((command?.options?.body as FormData).get('class_label')).toBe(label);
  });

  it('sube los audios elegidos al dataset y clase indicados y confirma el registro', async () => {
    await act(async () => { render(<IngestionView />); });
    fireEvent.change(screen.getByLabelText('Dataset de destino'), { target: { value: 'AvesChilenas' } });
    fireEvent.change(screen.getByLabelText('Clase de los audios'), { target: { value: 'Chucao' } });
    fireEvent.change(screen.getByLabelText('Audios'), { target: { files: [new File(['synthetic'], 'canto.wav', { type: 'audio/wav' })] } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Subir audios a GCS' })); });

    const command = requests.find(request => request.url.endsWith('/api/ingestion/upload'));
    expect(command?.options?.method).toBe('POST');
    const body = command?.options?.body as FormData;
    expect(body.get('dataset_name')).toBe('AvesChilenas');
    expect(body.get('class_label')).toBe('Chucao');
    expect((body.get('files') as File).name).toBe('canto.wav');
    const upload = within(screen.getByRole('region', { name: 'Subir audios' }));
    expect(upload.getByRole('status').textContent).toContain('1 archivo(s) subido(s)');
    expect(upload.getByRole('status').textContent).toContain('Registro en la base de datos confirmado');
  });

  it('rechaza antes del envío un archivo que excede el límite informado por el servidor', async () => {
    limits = { max_file_bytes: 8, max_batch_bytes: 16 };
    await act(async () => { render(<IngestionView />); });
    fireEvent.change(screen.getByLabelText('Dataset de destino'), { target: { value: 'AvesChilenas' } });
    fireEvent.change(screen.getByLabelText('Clase de los audios'), { target: { value: 'Chucao' } });
    fireEvent.change(screen.getByLabelText('Audios'), { target: { files: [new File(['too-large-audio'], 'canto.wav')] } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Subir audios a GCS' })); });

    expect(requests.some(request => request.url.endsWith('/api/ingestion/upload'))).toBe(false);
    expect(within(screen.getByRole('region', { name: 'Subir audios' })).getByRole('alert').textContent).toContain('límite por archivo');
  });

  it('rechaza un envío cuyo total excede el límite aunque cada audio sea pequeño', async () => {
    limits = { max_file_bytes: 8, max_batch_bytes: 12 };
    await act(async () => { render(<IngestionView />); });
    fireEvent.change(screen.getByLabelText('Dataset de destino'), { target: { value: 'AvesChilenas' } });
    fireEvent.change(screen.getByLabelText('Clase de los audios'), { target: { value: 'Chucao' } });
    fireEvent.change(screen.getByLabelText('Audios'), { target: { files: [new File(['1234567'], 'uno.wav'), new File(['1234567'], 'dos.wav')] } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Subir audios a GCS' })); });

    expect(requests.some(request => request.url.endsWith('/api/ingestion/upload'))).toBe(false);
    expect(within(screen.getByRole('region', { name: 'Subir audios' })).getByRole('alert').textContent).toContain('límite total');
  });

  it('explica una colisión y conserva solo los audios fallidos después de una subida parcial', async () => {
    uploadResult = { status: 'partial', uploaded: 1, skipped: 0, failed: 1, db_persisted: true,
      files: ['uno.wav'], errors: [{ filename: 'dos.wav', code: 'already_exists', error: 'Ya existe un audio con ese nombre y clase; no se ha reemplazado.' }] };
    await act(async () => { render(<IngestionView />); });
    fireEvent.change(screen.getByLabelText('Dataset de destino'), { target: { value: 'AvesChilenas' } });
    fireEvent.change(screen.getByLabelText('Clase de los audios'), { target: { value: 'Chucao' } });
    fireEvent.change(screen.getByLabelText('Audios'), { target: { files: [new File(['one'], 'uno.wav'), new File(['two'], 'dos.wav')] } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Subir audios a GCS' })); });

    const upload = within(screen.getByRole('region', { name: 'Subir audios' }));
    expect(upload.getByRole('alert').textContent).toContain('dos.wav');
    expect(upload.getByRole('alert').textContent).toContain('no se ha reemplazado');
    expect(upload.getByText('1 archivo(s) seleccionado(s): dos.wav')).toBeDefined();
    expect(upload.getByRole('status').textContent).toContain('1 con error');
  });

  it('conserva la selección ante una respuesta inválida y permite reintentar la misma carga', async () => {
    uploadResult = { unexpected: true };
    await act(async () => { render(<IngestionView />); });
    fireEvent.change(screen.getByLabelText('Dataset de destino'), { target: { value: 'AvesChilenas' } });
    fireEvent.change(screen.getByLabelText('Clase de los audios'), { target: { value: 'Chucao' } });
    fireEvent.change(screen.getByLabelText('Audios'), { target: { files: [new File(['one'], 'uno.wav')] } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Subir audios a GCS' })); });
    const upload = within(screen.getByRole('region', { name: 'Subir audios' }));
    expect(upload.getByRole('alert').textContent).toContain('No se pudo confirmar');
    expect(upload.getByText('1 archivo(s) seleccionado(s): uno.wav')).toBeDefined();
    uploadResult = { status: 'completed', uploaded: 0, skipped: 1, failed: 0, db_persisted: true, files: ['uno.wav'], errors: [] };
    await act(async () => { fireEvent.click(upload.getByRole('button', { name: 'Subir audios a GCS' })); });
    expect(upload.getByRole('status').textContent).toContain('1 ya existente(s)');
    expect(upload.queryByText('1 archivo(s) seleccionado(s): uno.wav')).toBeNull();
    expect(requests.filter(item => item.url.endsWith('/api/ingestion/upload'))).toHaveLength(2);
  });
});
