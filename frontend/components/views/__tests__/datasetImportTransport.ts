import { expect, vi } from "vitest";

/** Durable HTTP fixture: admission, status and final import are separate reads. */
export function durableFetch(handler: (input: string, options?: RequestInit) => Promise<Response>) {
  const executions = new Map<string, { execution: Record<string, unknown>; source: Record<string, unknown> }>();
  return vi.fn(async (input: string, options?: RequestInit) => {
    const path = new URL(input, "http://synthetic.test").pathname;
    const stored = executions.get(path);
    if (stored && !options?.method) return Response.json(stored.execution);
    if (!options?.method) {
      const latest = [...executions.values()].reverse().find(item => item.execution.import_id === path.split("/").pop());
      if (latest) return Response.json({ ...latest.source, execution: latest.execution });
    }
    const response = await handler(input, options);
    const operation = path.match(/\/imports\/([^/]+)\/(preview|confirm|sync)$/);
    if (options?.method !== "POST" || !operation || response.status !== 200) return response;
    const body = JSON.parse(String(options.body));
    expect(body.request_key).toEqual(expect.any(String));
    expect(body.request_key.length).toBeGreaterThan(0);
    const source = await response.json();
    const status_url = `/api/ingestion/imports/${operation[1]}/jobs/execution-${executions.size + 1}`;
    const execution = { id: `execution-${executions.size + 1}`, import_id: operation[1], kind: operation[2],
      status: source.sync_status === "error" ? "failed" : "succeeded", stage: "completed", progress: 100,
      result: {}, error: source.sync_status === "error" ? { code: "execution_failed" } : null, status_url };
    executions.set(status_url, { execution, source });
    return Response.json({ ...execution, status: "queued", stage: "queued", progress: 0, error: null }, { status: 202 });
  });
}
