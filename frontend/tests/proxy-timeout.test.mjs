import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { parse } from 'node:url';
import test from 'node:test';
import loadConfigModule from 'next/dist/server/config.js';
import proxyModule from 'next/dist/server/lib/router-utils/proxy-request.js';

// Actual Next config loader/helper; not a built Next server or browser test.
test('loaded timeout delivers real 35s responses; default 30s aborts', { timeout: 95000 }, async () => {
  const loadConfig = loadConfigModule.default || loadConfigModule;
  const config = await loadConfig('phase-production-server', new URL('..', import.meta.url).pathname);
  const rewrites = await config.rewrites();
  assert.equal(rewrites.length, 1);
  assert.equal(rewrites[0].source, '/api/:path*');
  assert.match(rewrites[0].destination, /^https?:\/\//);
  const sockets = new Set();
  const timers = new Set();
  const servers = [];
  const errors = [];
  const fixture = Buffer.alloc(46);
  fixture.write('RIFF'); fixture.writeUInt32LE(38, 4); fixture.write('WAVEfmt ', 8);
  fixture.writeUInt32LE(16, 16); fixture.writeUInt16LE(1, 20); fixture.writeUInt16LE(1, 22);
  fixture.writeUInt32LE(1, 24); fixture.writeUInt32LE(2, 28); fixture.writeUInt16LE(2, 32);
  fixture.writeUInt16LE(16, 34); fixture.write('data', 36); fixture.writeUInt32LE(2, 40);

  async function listen(handler) {
    const server = http.createServer(handler);
    servers.push(server);
    server.on('connection', socket => {
      sockets.add(socket); socket.on('close', () => sockets.delete(socket));
    });
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    return server.address().port;
  }

  async function request(port, path) {
    const started = performance.now();
    return await new Promise((resolve, reject) => {
      const req = http.request({ hostname: '127.0.0.1', port, path, method: 'POST' }, res => {
        const parts = [];
        res.on('data', data => parts.push(data));
        res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(parts).toString(),
                                    elapsed: performance.now() - started }));
        res.on('error', reject);
      });
      req.on('error', reject); req.setTimeout(80000, () => req.destroy(new Error('test watchdog')));
      req.end(fixture);
    });
  }

  try {
    const backend = await listen((req, res) => {
      const chunks = [];
      req.on('data', data => chunks.push(data));
      req.on('end', () => {
        assert.deepEqual(Buffer.concat(chunks), fixture);
        const timer = setTimeout(() => {
          timers.delete(timer);
          if (!res.destroyed) res.end('slow fake response');
        }, 35000);
        timers.add(timer);
      });
    });
    const proxy = await listen((req, res) => {
      const timeout = req.url === '/baseline' ? undefined : config.experimental.proxyTimeout;
      proxyModule.proxyRequest(req, res, parse(`http://127.0.0.1:${backend}${req.url}`, true),
                               undefined, undefined, timeout).catch(error => errors.push(error.code));
    });
    // Parallel real elapsed waits: same helper, one default and two external rewrite paths.
    const [baseline, prediction, otherApi] = await Promise.all([
      request(proxy, '/baseline'), request(proxy, '/api/predict'), request(proxy, '/api/other'),
    ]);
    assert.equal(baseline.status, 500);
    assert.ok(baseline.elapsed >= 29000 && baseline.elapsed < 34500, `baseline ${baseline.elapsed}ms`);
    assert.ok(errors.length >= 1, 'negative control must observe actual proxy abort');
    for (const result of [prediction, otherApi]) {
      assert.equal(result.status, 200);
      assert.equal(result.body, 'slow fake response');
      assert.ok(result.elapsed >= 35000, `not a simulated clock: ${result.elapsed}ms`);
    }
    assert.equal(config.experimental.proxyTimeout, 300000);
  } finally {
    for (const timer of timers) clearTimeout(timer);
    for (const socket of sockets) socket.destroy();
    await Promise.all(servers.map(server => new Promise(resolve => server.close(resolve))));
  }
});
