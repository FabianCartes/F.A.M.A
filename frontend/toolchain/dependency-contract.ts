import semver from "semver";

export type Rule = "peer" | "engine" | "node-types-coherence";

export interface Violation {
  rule: Rule;
  subject: string;
  detail: string;
}

export interface LockPackage {
  name?: string;
  version?: string;
  peerDependencies?: Record<string, string>;
  peerDependenciesMeta?: Record<string, { optional?: boolean }>;
  engines?: { node?: string };
  os?: string[];
  cpu?: string[];
}

export interface TargetPlatform {
  os: string;
  cpu: string;
}

export interface PackageLock {
  lockfileVersion?: number;
  packages: Record<string, LockPackage>;
}

export interface PackageJson {
  devDependencies?: Record<string, string>;
}

export interface ContractInput {
  lock: PackageLock;
  pkg: PackageJson;
  dockerfile: string;
  target?: TargetPlatform;
}

/**
 * The platform the image is built and run on. Platform-gated prebuilt binaries
 * for other operating systems and architectures are recorded in the lockfile
 * but are never installed or executed here, so their `engines` say nothing
 * about this build.
 */
export const DEFAULT_TARGET: TargetPlatform = { os: "linux", cpu: "x64" };

function runsOnTarget(entry: LockPackage, target: TargetPlatform): boolean {
  if (entry.os && !entry.os.includes(target.os)) return false;
  if (entry.cpu && !entry.cpu.includes(target.cpu)) return false;
  return true;
}

const OPEN_SEGMENT = 9999;

/**
 * Every FROM image declared by the Dockerfile, in declaration order.
 */
export function readBaseImages(dockerfile: string): string[] {
  return [...dockerfile.matchAll(/^\s*FROM\s+(\S+)/gim)].map((match) => match[1]);
}

/**
 * The Node major version a base image targets, or null when the image is not
 * a recognisable `node:<tag>` reference. Only the major is trustworthy from a
 * floating tag: `node:22-alpine` may resolve to any 22.x, so patch-level
 * `engines` floors are not decidable here. That residual risk is closed by the
 * real runtime probe recorded in the receipt, not by this function.
 */
export function readNodeMajor(image: string): number | null {
  const withoutDigest = image.split("@")[0];
  const colon = withoutDigest.lastIndexOf(":");
  if (colon === -1) return null;

  const major = /(\d+)/.exec(withoutDigest.slice(colon + 1));
  return major ? Number(major[1]) : null;
}

/**
 * Resolve `name` as seen from `fromPath` using Node's node_modules walk: the
 * nearest scope wins, then each enclosing ancestor, then the tree root.
 */
function resolveFrom(
  lock: PackageLock,
  fromPath: string,
  name: string,
): LockPackage | undefined {
  const names = fromPath
    .replace(/^node_modules\//, "")
    .split("/node_modules/");

  for (let end = names.length; end >= 0; end--) {
    const scope = names.slice(0, end).join("/node_modules/");
    const candidate = scope
      ? `node_modules/${scope}/node_modules/${name}`
      : `node_modules/${name}`;
    if (lock.packages[candidate]) return lock.packages[candidate];
  }

  return undefined;
}

/**
 * A peer that is present but out of range is a violation even when the peer is
 * declared optional: optional means npm may skip installing it, not that a
 * present copy is exempt from the declared range. A missing optional peer is
 * not a violation, matching npm's own resolver.
 */
function auditPeers(lock: PackageLock): Violation[] {
  const violations: Violation[] = [];

  for (const [path, entry] of Object.entries(lock.packages)) {
    for (const [peerName, range] of Object.entries(entry.peerDependencies ?? {})) {
      const resolved = resolveFrom(lock, path, peerName);

      if (!resolved?.version) {
        if (entry.peerDependenciesMeta?.[peerName]?.optional) continue;
        violations.push({
          rule: "peer",
          subject: `${path || "<root>"} -> ${peerName}`,
          detail: `required peer ${peerName}@${range} is not installed`,
        });
        continue;
      }

      if (!semver.satisfies(resolved.version, range, { includePrerelease: true })) {
        violations.push({
          rule: "peer",
          subject: `${path || "<root>"} -> ${peerName}`,
          detail: `${peerName}@${resolved.version} does not satisfy ${range}`,
        });
      }
    }
  }

  return violations;
}

/**
 * Every locked package must be installable on the Node major the image
 * targets. The probe version is the newest release of that major, so a
 * satisfied result means "this major can host the package" rather than
 * "this exact patch can".
 */
function auditEngines(
  lock: PackageLock,
  baseMajor: number,
  target: TargetPlatform,
): Violation[] {
  const probe = `${baseMajor}.${OPEN_SEGMENT}.${OPEN_SEGMENT}`;
  const violations: Violation[] = [];

  for (const [path, entry] of Object.entries(lock.packages)) {
    const range = entry.engines?.node;
    if (!range) continue;
    if (!runsOnTarget(entry, target)) continue;

    if (!semver.satisfies(probe, range, { includePrerelease: true })) {
      violations.push({
        rule: "engine",
        subject: `${path || "<root>"}@${entry.version ?? "?"}`,
        detail: `engines.node "${range}" excludes Node ${probe}`,
      });
    }
  }

  return violations;
}

/**
 * The type definitions for Node and the runtime that compiles them must
 * describe the same major. Divergence here is what lets a build typecheck
 * against an API surface the runtime never provides.
 */
function auditNodeTypesCoherence(
  lock: PackageLock,
  pkg: PackageJson,
  baseMajor: number,
): Violation[] {
  const violations: Violation[] = [];
  const declared = pkg.devDependencies?.["@types/node"];
  const resolved = lock.packages["node_modules/@types/node"]?.version;

  if (declared) {
    const floor = semver.minVersion(declared);
    if (floor && floor.major !== baseMajor) {
      violations.push({
        rule: "node-types-coherence",
        subject: "package.json devDependencies.@types/node",
        detail: `declared ${declared} targets Node ${floor.major}, image targets Node ${baseMajor}`,
      });
    }
  }

  if (resolved && semver.major(resolved) !== baseMajor) {
    violations.push({
      rule: "node-types-coherence",
      subject: "package-lock.json node_modules/@types/node",
      detail: `locked @types/node@${resolved} targets Node ${semver.major(
        resolved,
      )}, image targets Node ${baseMajor}`,
    });
  }

  return violations;
}

/**
 * The single entry point: audit the committed release toolchain and return
 * every way it contradicts itself. An empty array is the only acceptable
 * state, and it means the tree that `npm ci` reproduces is installable and
 * runnable on the Node the image ships.
 */
export function auditDependencyContract(input: ContractInput): Violation[] {
  const { lock, pkg, dockerfile } = input;
  const target = input.target ?? DEFAULT_TARGET;
  const majors = readBaseImages(dockerfile)
    .map(readNodeMajor)
    .filter((major): major is number => major !== null);

  if (majors.length === 0) return [];

  const incoherent = new Set(majors);
  if (incoherent.size > 1) {
    return [
      {
        rule: "engine",
        subject: "Dockerfile",
        detail: `build stages target different Node majors: ${[...incoherent].join(", ")}`,
      },
    ];
  }

  const baseMajor = [...incoherent][0];

  return [
    ...auditPeers(lock),
    ...auditEngines(lock, baseMajor, target),
    ...auditNodeTypesCoherence(lock, pkg, baseMajor),
  ];
}
