import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

describe("API_BASE_URL configuration and contract", () => {
  const originalEnv = process.env.NEXT_PUBLIC_API_URL;

  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    process.env.NEXT_PUBLIC_API_URL = originalEnv;
    vi.resetModules();
  });

  it("resolves to empty string when NEXT_PUBLIC_API_URL is undefined (allowing Next.js rewrites)", async () => {
    delete process.env.NEXT_PUBLIC_API_URL;
    const { API_BASE_URL } = await import("../api");
    expect(API_BASE_URL).toBe("");
  });

  it("resolves to empty string when NEXT_PUBLIC_API_URL is empty string", async () => {
    process.env.NEXT_PUBLIC_API_URL = "";
    const { API_BASE_URL } = await import("../api");
    expect(API_BASE_URL).toBe("");
  });

  it("resolves to empty string when NEXT_PUBLIC_API_URL contains only whitespace", async () => {
    process.env.NEXT_PUBLIC_API_URL = "   ";
    const { API_BASE_URL } = await import("../api");
    expect(API_BASE_URL).toBe("");
  });

  it("preserves explicit absolute URL when NEXT_PUBLIC_API_URL is provided", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://api.fama.internal:8000";
    const { API_BASE_URL } = await import("../api");
    expect(API_BASE_URL).toBe("http://api.fama.internal:8000");
  });

  it("constructs relative paths with empty API_BASE_URL for reverse proxy compatibility", async () => {
    delete process.env.NEXT_PUBLIC_API_URL;
    const { API_BASE_URL } = await import("../api");
    const endpoint = `${API_BASE_URL}/api/v1/training/hardware`;
    expect(endpoint).toBe("/api/v1/training/hardware");
  });
});
