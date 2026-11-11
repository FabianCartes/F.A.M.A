/** Shared names for saved partition versions (training block and model history). */
export interface PartitionVersionSummary {
  version: string;
  counts: { train: number; val: number; test?: number };
  policy?: { validation_percent?: number; test_percent?: number };
}

/** Versions arrive newest first; numbering from the oldest keeps a name stable. */
export function versionName(versions: PartitionVersionSummary[], item: PartitionVersionSummary) {
  return `Versión ${versions.length - versions.findIndex(entry => entry.version === item.version)}`;
}

/** The chosen policy names the version; versions without one show their actual shares. */
export function versionShares(item: PartitionVersionSummary) {
  const total = item.counts.train + item.counts.val + (item.counts.test ?? 0);
  const val = item.policy?.validation_percent ?? Math.round(item.counts.val * 100 / total);
  const test = item.counts.test ? item.policy?.test_percent ?? Math.round(item.counts.test * 100 / total) : 0;
  return { total, train: 100 - val - test, val, test };
}

/** «Versión N · 60/20/20 %», short enough for a phone. */
export function versionShortName(versions: PartitionVersionSummary[], item: PartitionVersionSummary) {
  const { train, val, test } = versionShares(item);
  return `${versionName(versions, item)} · ${[train, val, ...(test ? [test] : [])].join("/")} %`;
}
