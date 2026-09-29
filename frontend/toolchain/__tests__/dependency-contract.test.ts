import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { auditDependencyContract } from "../dependency-contract";

const ROOT = resolve(__dirname, "..", "..");

const lock = JSON.parse(
  readFileSync(resolve(ROOT, "package-lock.json"), "utf8"),
);
const pkg = JSON.parse(readFileSync(resolve(ROOT, "package.json"), "utf8"),
);
const dockerfile = readFileSync(resolve(ROOT, "Dockerfile"), "utf8");

function violations() {
  return auditDependencyContract({
    lock,
    pkg,
    dockerfile,
    target: { os: "linux", cpu: "x64" },
  });
}

function ruleViolations(rule: string) {
  return violations().filter((v) => v.rule === rule);
}

describe("dependency contract of the committed release toolchain", () => {
  it("declares a single Node base image across every build stage", () => {
    const stages = [...dockerfile.matchAll(/^FROM\s+(\S+)/gm)].map((m) => m[1]);

    expect(stages.length).toBeGreaterThan(0);
    expect([...new Set(stages)]).toHaveLength(1);
  });

  it("S1 resolves every declared peer dependency without a version conflict", () => {
    expect(ruleViolations("peer")).toEqual([]);
  });

  it("S2 satisfies engines.node of every locked package with the Docker base image", () => {
    expect(ruleViolations("engine")).toEqual([]);
  });

  it("S3 keeps the declared @types/node major aligned with the Docker Node major", () => {
    expect(ruleViolations("node-types-coherence")).toEqual([]);
  });

  it("reports no violation of any rule", () => {
    expect(violations()).toEqual([]);
  });
});
