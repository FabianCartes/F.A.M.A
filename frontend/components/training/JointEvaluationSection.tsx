import { formatRate, jointMetric, jointStatusLabel, type JointEvaluation } from "@/components/training/triadHistory";

const SPLITS = [["val", "Validación"], ["test", "Prueba"]] as const;
const METRICS = [["f1_macro", "F1 macro"], ["balanced_accuracy", "Exactitud balanceada"]] as const;

/** Joint (fused-output) report of one composition, with validation and test kept apart. */
export default function JointEvaluationSection({ evaluation }: { evaluation?: JointEvaluation }) {
  return (
    <section aria-label="Evaluación conjunta" className="bg-[#111215] border border-[#23252e] rounded-xl p-4 mb-4">
      <h3 className="text-white font-semibold mb-3">Evaluación conjunta</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {SPLITS.map(([key, label]) => {
          const split = evaluation?.[key] ?? null;
          const valid = jointMetric(split, "accuracy") !== null;
          const rejection = valid && split ? (typeof split.rejection_rate === "number" && Number.isFinite(split.rejection_rate) ? split.rejection_rate : null) : null;
          return (
            <div key={key} className="space-y-1 text-xs">
              <div className="text-gray-400">{label}</div>
              <div className={valid ? "text-emerald-400 text-sm font-semibold" : "text-amber-400 text-sm"}>{jointStatusLabel(split)}</div>
              {valid && split && <>
                {METRICS.map(([name, text]) => {
                  const value = jointMetric(split, name);
                  return value === null ? null : <div key={name} className="text-gray-300">{text}: <span>{formatRate(value)}</span></div>;
                })}
                {rejection !== null && <div className="text-gray-300">Rechazos: <span>{formatRate(rejection)}</span></div>}
                {Number.isInteger(split.sample_count) && <div className="text-gray-500">{`${split.sample_count} grabaciones`}</div>}
              </>}
              {split?.status === "failed" && split.error_reason && <div className="text-red-300">{split.error_reason}</div>}
            </div>
          );
        })}
      </div>
    </section>
  );
}
