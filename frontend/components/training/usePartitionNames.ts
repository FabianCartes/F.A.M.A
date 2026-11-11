"use client";

import { useEffect, useState } from "react";
import { z } from "zod";
import { API_BASE_URL, apiFetch } from "@/lib/api";
import { versionShortName, type PartitionVersionSummary } from "@/lib/partitionVersions";

const listSchema = z.object({ versions: z.array(z.object({
  version: z.string(),
  counts: z.object({ train: z.number(), val: z.number(), test: z.number().optional() }),
  policy: z.object({ validation_percent: z.number().optional(), test_percent: z.number().optional() }).optional(),
})) });

/** Short names (version → «Versión N · 60/20/20 %») for the partitions used by these models. */
export function usePartitionNames(models: { dataset_name?: string | null; partition_version?: string | null }[]) {
  const [names, setNames] = useState<Record<string, string>>({});
  const datasets = [...new Set(models.filter(model => model.partition_version && model.dataset_name)
    .map(model => model.dataset_name as string))].sort().join("\n");

  useEffect(() => {
    if (!datasets) return;
    const controller = new AbortController();
    void Promise.all(datasets.split("\n").map(async dataset => {
      try {
        const response = await apiFetch(`${API_BASE_URL}/api/training/datasets/${encodeURIComponent(dataset)}/partitions`, { signal: controller.signal });
        const parsed = listSchema.safeParse(response.ok ? await response.json() : null);
        return parsed.success ? parsed.data.versions as PartitionVersionSummary[] : [];
      } catch {
        return [];
      }
    })).then(lists => {
      if (controller.signal.aborted) return;
      const next: Record<string, string> = {};
      for (const versions of lists) for (const item of versions) next[item.version] = versionShortName(versions, item);
      setNames(next);
    });
    return () => controller.abort();
  }, [datasets]);

  return names;
}
