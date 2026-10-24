import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

it('permite un directorio de compilación independiente para otro entorno del mismo código', async () => {
  vi.stubEnv('FAMA_NEXT_DIST_DIR', '.next-pruebas');
  vi.resetModules();
  const { default: configuration } = await import('../../next.config');
  expect(configuration.distDir).toBe('.next-pruebas');
});
