import type { ModelHistoryItem } from "@/lib/schemas/training";

export interface JointSplitEvaluation {
  status: string;
  sample_count: number;
  metrics: Record<string, unknown> | null;
  rejection_rate: number | null;
  error_reason: string | null;
}
export interface JointEvaluation {
  val: JointSplitEvaluation | null;
  test: JointSplitEvaluation | null;
}
export interface HistoryComposition {
  id: number;
  version: number;
  job_id: string;
  /** `<Dataset> · Tríada <n> — <architectures>`; absent for older servers. */
  name?: string;
  components: { id_modelo: number; weight: number }[];
  /** Stored joint reports of this exact composition; absent for older servers. */
  evaluation?: JointEvaluation;
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

const rate = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;

/** A metric of a completed joint report, or null when the report is absent or malformed. */
export function jointMetric(split: JointSplitEvaluation | null | undefined, name: string): number | null {
  if (!split || split.status !== "completed" || !split.metrics || typeof split.metrics !== "object") return null;
  return rate(split.metrics[name]);
}

export const formatRate = (value: number) => `${(value * 100).toFixed(2)}%`;

/** Short state of one split; never invents a precision for pending, failed or malformed reports. */
export function jointStatusLabel(split: JointSplitEvaluation | null | undefined): string {
  if (!split || typeof split !== "object") return "Sin evaluación conjunta";
  if (split.status === "pending" || split.status === "running") return "Evaluación conjunta pendiente";
  if (split.status === "failed") return "Evaluación conjunta fallida";
  if (split.status !== "completed") return "Sin evaluación conjunta";
  const accuracy = jointMetric(split, "accuracy");
  return accuracy === null ? "Sin informe válido" : formatRate(accuracy);
}
