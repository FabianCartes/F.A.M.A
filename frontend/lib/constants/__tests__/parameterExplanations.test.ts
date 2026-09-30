import { describe, it, expect } from "vitest";
import {
  PARAMETER_EXPLANATIONS,
  type ParameterExplanation,
} from "../parameterExplanations";

describe("Parameter Explanations Catalog", () => {
  const requiredKeys = [
    // Audio physics
    "target_sr",
    "duration_seconds",
    "f_min",
    "f_max",
    "hop_seconds",
    "aggregation_mode",
    "gem_p",
    "vad_threshold",
    "loss_type",
    "focal_gamma",
    "mixup",
    "pitch_shift",
    // Hyperparameters
    "learning_rate",
    "weight_decay",
    "epochs",
    "batch_size",
    "framework",
    "architecture",
    "ensemble_size",
  ];

  it("contains all required audio and hyperparameter keys", () => {
    for (const key of requiredKeys) {
      expect(PARAMETER_EXPLANATIONS[key]).toBeDefined();
    }
  });

  it("has concise and well-structured content for each parameter", () => {
    for (const key of requiredKeys) {
      const item: ParameterExplanation = PARAMETER_EXPLANATIONS[key];
      expect(item.title).toBeTruthy();
      expect(item.impact).toBeTruthy();
      expect(item.usage).toBeTruthy();
      expect(item.impact.length).toBeGreaterThan(15);
      expect(item.usage.length).toBeGreaterThan(15);
      expect(Array.isArray(item.keyPoints)).toBe(true);
      expect(item.keyPoints.length).toBeGreaterThan(0);
    }
  });
});
