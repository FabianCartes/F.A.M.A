import { expect, it } from 'vitest';
import { catalogDatasetSchema, executionSchema, jobSchema, limitsSchema } from '../datasetImports';
import { receiptSchema } from '../datasetImportReceipt';

it('accepts a local receipt and import limits without disk reservations', () => {
  expect(receiptSchema.parse({ import_id: 'local', name: 'birds.zip', size_bytes: 4,
    received_bytes: 0, chunk_bytes: 4, status: 'receiving' })).toEqual({ import_id: 'local',
    name: 'birds.zip', size_bytes: 4, received_bytes: 0, chunk_bytes: 4, status: 'receiving' });
  expect(limitsSchema.parse({ received_bytes: 4, expanded_bytes: 40, entries: 10, depth: 1,
    path_bytes: 100, audio_bytes: 4, audio_seconds: 1, validation_seconds: 10,
    ttl_seconds: 100, concurrent_imports: 1 }).received_bytes).toBe(4);
});

it('keeps historical dataset metadata without a private cloud acknowledgement count', () => {
  expect(catalogDatasetSchema.parse({ id: 'local', name: 'Birds', file_count: 1,
    revision: 2, description: null, class_count: 1, total_size_bytes: 4,
    imported_at: 1700000000 })).toEqual({ id: 'local', name: 'Birds', file_count: 1,
    revision: 2, description: null, class_count: 1, total_size_bytes: 4, imported_at: 1700000000 });
});

it('parses local import and execution results without private sync fields', () => {
  const execution = { id: 'work', import_id: 'local', kind: 'confirm', status: 'succeeded',
    stage: 'completed', progress: 100, result: { dataset_id: 'dataset', added_count: 1 },
    error: null, status_url: '/local/jobs/work' };
  expect(executionSchema.parse(execution)).toEqual(execution);
  expect(executionSchema.safeParse({ ...execution, kind: 'sync' }).success).toBe(false);
  const job = { id: 'local', status: 'imported', dataset_id: 'dataset', added_count: 1,
    preview_token: 'snapshot', preview: { file_count: 1, class_count: 1, error_count: 0,
      warning_count: 0, total_size_bytes: 4 }, error: null, execution };
  expect(jobSchema.parse(job)).toEqual(job);
});
