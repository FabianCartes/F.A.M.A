import { afterEach, expect, it, vi } from "vitest";
import { importRequest, jsonRequest } from "../datasetImports";

afterEach(() => vi.unstubAllGlobals());

it("uses only same-origin cookies while retaining JSON, abort and cache behavior", async () => {
  const transport = vi.fn(async () => Response.json({ ok: true }));
  vi.stubGlobal("fetch", transport);
  const controller = new AbortController();
  const response = await importRequest("/api/ingestion/imports", {
    ...jsonRequest({ name: "Colección privada" }), signal: controller.signal,
  });
  expect(await response.json()).toEqual({ ok: true });
  const [url, options] = transport.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("/api/ingestion/imports");
  expect(options).toMatchObject({ method: "POST", credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal });
  expect(new Headers(options.headers).get("Authorization")).toBeNull();
  expect(new Headers(options.headers).get("Content-Type")).toBe("application/json");
  expect(options.body).toBe('{"name":"Colección privada"}');
});
