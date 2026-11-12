import type { ModelHistoryItem } from "@/lib/schemas/training";

export interface HistoryComposition {
  id: number;
  version: number;
  job_id: string;
  components: { id_modelo: number; weight: number }[];
}
export interface TriadHistoryGroup {
  composition: HistoryComposition;
  members: ModelHistoryItem[];
}

/** Group only fully visible, unambiguous compositions supplied by the server. */
export function groupTriadHistory(history: ModelHistoryItem[], value: unknown): TriadHistoryGroup[] {
  if (!Array.isArray(value)) return [];
  const groups: TriadHistoryGroup[] = [];
  const used = new Set<number>();
  for (const candidate of value) {
    if (!candidate || typeof candidate !== "object") continue;
    const c = candidate as HistoryComposition;
    if (!Number.isInteger(c.id) || !Number.isInteger(c.version) || typeof c.job_id !== "string" || !c.job_id || !Array.isArray(c.components) || c.components.length !== 3) continue;
    if (c.components.some(x => !x || !Number.isInteger(x.id_modelo) || typeof x.weight !== "number" || !Number.isFinite(x.weight) || x.weight < 0)) continue;
    const ids = c.components.map(x => x.id_modelo);
    if (new Set(ids).size !== 3 || ids.some(id => used.has(id)) || Math.abs(c.components.reduce((sum, x) => sum + x.weight, 0) - 1) > 1e-9) continue;
    const members = ids.map(id => history.filter(item => item.id === id));
    if (members.some(items => items.length !== 1)) continue;
    ids.forEach(id => used.add(id));
    groups.push({ composition: c, members: members.map(items => items[0]) });
  }
  return groups;
}
