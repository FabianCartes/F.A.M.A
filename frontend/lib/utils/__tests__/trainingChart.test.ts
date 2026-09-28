import { describe, it, expect } from "vitest";
import {
  normalizePoint,
  getChartPaths,
  MetricPoint,
} from "../trainingChart";

describe("trainingChart utility (TDD)", () => {
  describe("normalizePoint", () => {
    const height = 100;
    const paddingTop = 14;
    const paddingBottom = 14;

    it("normalizes standard values with invert=true (high values at top)", () => {
      // 100% accuracy -> top of chart (y = paddingTop = 14)
      const y100 = normalizePoint(100, 0, 100, height, paddingTop, paddingBottom, true);
      expect(y100).toBeCloseTo(14, 2);

      // 0% accuracy -> bottom of chart (y = height - paddingBottom = 86)
      const y0 = normalizePoint(0, 0, 100, height, paddingTop, paddingBottom, true);
      expect(y0).toBeCloseTo(86, 2);

      // 50% accuracy -> middle of safe area (y = 14 + 36 = 50)
      const y50 = normalizePoint(50, 0, 100, height, paddingTop, paddingBottom, true);
      expect(y50).toBeCloseTo(50, 2);
    });

    it("normalizes with invert=false (high values at bottom)", () => {
      const y0 = normalizePoint(0, 0, 100, height, paddingTop, paddingBottom, false);
      expect(y0).toBeCloseTo(14, 2);

      const y100 = normalizePoint(100, 0, 100, height, paddingTop, paddingBottom, false);
      expect(y100).toBeCloseTo(86, 2);
    });

    it("strictly clamps values exceeding min or max bounds into [14, 86]", () => {
      const yBelow = normalizePoint(-20, 0, 100, height, paddingTop, paddingBottom, true);
      expect(yBelow).toBeCloseTo(86, 2);

      const yAbove = normalizePoint(150, 0, 100, height, paddingTop, paddingBottom, true);
      expect(yAbove).toBeCloseTo(14, 2);
    });

    it("handles edge cases: minVal === maxVal, NaN, Infinity without NaN results", () => {
      const yEqual = normalizePoint(5, 5, 5, height, paddingTop, paddingBottom, true);
      expect(yEqual).toBeGreaterThanOrEqual(14);
      expect(yEqual).toBeLessThanOrEqual(86);

      const yNaN = normalizePoint(NaN, 0, 100, height, paddingTop, paddingBottom, true);
      expect(isNaN(yNaN)).toBe(false);

      const yInf = normalizePoint(Infinity, 0, 100, height, paddingTop, paddingBottom, true);
      expect(isNaN(yInf)).toBe(false);
    });
  });

  describe("getChartPaths", () => {
    it("returns empty structure when metrics array is empty", () => {
      const result = getChartPaths([], { width: 300, height: 100, totalEpochs: 10 });
      expect(result.segments).toEqual([]);
      expect(result.separators).toEqual([]);
      expect(result.maxLoss).toBe(1.0);
      expect(result.totalPoints).toBe(0);
      expect(result.filteredMetrics).toEqual([]);
    });

    it("renders single model curves with dynamic loss scaling and safe bounds", () => {
      const metrics: MetricPoint[] = [
        { epoca: 1, train_loss: 1.5, val_loss: 2.0, train_acc: 30, val_acc: 40, tiempo_epoca: 2.1 },
        { epoca: 2, train_loss: 1.0, val_loss: 1.2, train_acc: 55, val_acc: 60, tiempo_epoca: 2.0 },
        { epoca: 3, train_loss: 0.6, val_loss: 0.8, train_acc: 75, val_acc: 80, tiempo_epoca: 2.0 },
      ];

      const result = getChartPaths(metrics, {
        width: 300,
        height: 100,
        totalEpochs: 3,
        activeModelFilter: "current",
      });

      expect(result.segments).toHaveLength(1);
      const seg = result.segments[0];
      expect(seg.points).toHaveLength(3);

      // X coordinates should span exactly [0, 300] for epochs 1 to 3
      expect(seg.points[0].x).toBeCloseTo(0, 1);
      expect(seg.points[1].x).toBeCloseTo(150, 1);
      expect(seg.points[2].x).toBeCloseTo(300, 1);

      // Y coordinates for Accuracy: 40% -> 80%
      expect(seg.points[0].yAcc).toBeGreaterThan(seg.points[2].yAcc); // Acc increases, so yAcc decreases (goes up)
      expect(seg.points[0].yAcc).toBeLessThanOrEqual(86);
      expect(seg.points[2].yAcc).toBeGreaterThanOrEqual(14);

      // Dynamic Loss scaling: max val_loss is 2.0 -> maxLoss >= 2.0
      expect(result.maxLoss).toBeCloseTo(2.0, 1);

      // Loss curve: val_loss 2.0 (high) -> near top (y=14), val_loss 0.8 (lower) -> lower (higher y)
      expect(seg.points[0].yLoss).toBeCloseTo(14, 1);
      expect(seg.points[2].yLoss).toBeGreaterThan(seg.points[0].yLoss);
      expect(seg.points[2].yLoss).toBeLessThanOrEqual(86);

      // Polyline strings properly formatted
      expect(seg.accPolyline).toContain("0.0,");
      expect(seg.accPolyline).toContain("300.0,");
      expect(seg.lossPolyline).toContain("0.0,14.0");
    });

    it("auto-scales maxLoss to at least 1.0 when all losses are low", () => {
      const metrics: MetricPoint[] = [
        { epoca: 1, train_loss: 0.3, val_loss: 0.4, train_acc: 85, val_acc: 88, tiempo_epoca: 1.5 },
        { epoca: 2, train_loss: 0.2, val_loss: 0.25, train_acc: 90, val_acc: 92, tiempo_epoca: 1.5 },
      ];

      const result = getChartPaths(metrics, { width: 300, height: 100, totalEpochs: 2 });
      expect(result.maxLoss).toBe(1.0);
    });

    it("auto-scales maxLoss dynamically above 1.0 when loss spikes to 3.5 without saturation", () => {
      const metrics: MetricPoint[] = [
        { epoca: 1, train_loss: 3.2, val_loss: 3.5, train_acc: 10, val_acc: 15, tiempo_epoca: 1.5 },
        { epoca: 2, train_loss: 1.8, val_loss: 2.1, train_acc: 40, val_acc: 45, tiempo_epoca: 1.5 },
      ];

      const result = getChartPaths(metrics, { width: 300, height: 100, totalEpochs: 2 });
      expect(result.maxLoss).toBeCloseTo(3.5, 2);
      const seg = result.segments[0];
      // Peak loss 3.5 should map to y=14, not clip or saturate at 2.0
      expect(seg.points[0].yLoss).toBeCloseTo(14, 1);
    });

    it("separates polylines by model in ensemble and prevents bridging line between models", () => {
      // 2 models in ensemble: Model 1 (2 epochs), Model 2 (2 epochs)
      const metrics: MetricPoint[] = [
        { epoca: 1, model_index: 1, architecture: "EfficientNet-B0", train_loss: 1.0, val_loss: 1.0, train_acc: 50, val_acc: 55, tiempo_epoca: 1 },
        { epoca: 2, model_index: 1, architecture: "EfficientNet-B0", train_loss: 0.7, val_loss: 0.8, train_acc: 70, val_acc: 75, tiempo_epoca: 1 },
        { epoca: 1, model_index: 2, architecture: "ConvNeXt-Nano", train_loss: 1.2, val_loss: 1.3, train_acc: 45, val_acc: 50, tiempo_epoca: 1 },
        { epoca: 2, model_index: 2, architecture: "ConvNeXt-Nano", train_loss: 0.8, val_loss: 0.9, train_acc: 65, val_acc: 70, tiempo_epoca: 1 },
      ];

      const result = getChartPaths(metrics, {
        width: 300,
        height: 100,
        activeModelFilter: "all",
        modelsConfig: [
          { architecture: "EfficientNet-B0", epochs: 2 },
          { architecture: "ConvNeXt-Nano", epochs: 2 },
        ],
      });

      // Should have 2 independent segments
      expect(result.segments).toHaveLength(2);
      expect(result.segments[0].modelIndex).toBe(1);
      expect(result.segments[0].architecture).toBe("EfficientNet-B0");
      expect(result.segments[1].modelIndex).toBe(2);
      expect(result.segments[1].architecture).toBe("ConvNeXt-Nano");

      // Verify Model 1 polyline does NOT include points from Model 2
      expect(result.segments[0].points).toHaveLength(2);
      expect(result.segments[1].points).toHaveLength(2);

      // Model 1 x points: in first half of width
      expect(result.segments[0].points[0].x).toBeLessThan(result.segments[1].points[0].x);
      // All x points <= width (300)
      expect(result.segments[1].points[1].x).toBeLessThanOrEqual(300);

      // Separators between models
      expect(result.separators).toHaveLength(1);
      expect(result.separators[0].modelIndex).toBe(2);
      expect(result.separators[0].x).toBeGreaterThan(0);
      expect(result.separators[0].x).toBeLessThan(300);
    });

    it("filters properly when activeModelFilter specifies a specific model index", () => {
      const metrics: MetricPoint[] = [
        { epoca: 1, model_index: 1, architecture: "EfficientNet-B0", train_loss: 1.0, val_loss: 1.0, train_acc: 50, val_acc: 55, tiempo_epoca: 1 },
        { epoca: 2, model_index: 1, architecture: "EfficientNet-B0", train_loss: 0.7, val_loss: 0.8, train_acc: 70, val_acc: 75, tiempo_epoca: 1 },
        { epoca: 1, model_index: 2, architecture: "ConvNeXt-Nano", train_loss: 1.2, val_loss: 1.3, train_acc: 45, val_acc: 50, tiempo_epoca: 1 },
        { epoca: 2, model_index: 2, architecture: "ConvNeXt-Nano", train_loss: 0.8, val_loss: 0.9, train_acc: 65, val_acc: 70, tiempo_epoca: 1 },
      ];

      // Filter only model 2
      const resultModel2 = getChartPaths(metrics, {
        width: 300,
        height: 100,
        totalEpochs: 2,
        activeModelFilter: 2,
      });

      expect(resultModel2.segments).toHaveLength(1);
      expect(resultModel2.segments[0].modelIndex).toBe(2);
      expect(resultModel2.totalPoints).toBe(2);
      // X for filtered model 2 should start at 0 and end at 300
      expect(resultModel2.segments[0].points[0].x).toBeCloseTo(0, 1);
      expect(resultModel2.segments[0].points[1].x).toBeCloseTo(300, 1);
    });

    it("handles single point at epoch 1 of 10 without division by zero", () => {
      const metrics: MetricPoint[] = [
        { epoca: 1, train_loss: 1.2, val_loss: 1.5, train_acc: 40, val_acc: 45, tiempo_epoca: 1.0 },
      ];

      const result = getChartPaths(metrics, { width: 300, height: 100, totalEpochs: 10 });
      expect(result.segments).toHaveLength(1);
      expect(result.segments[0].points).toHaveLength(1);
      expect(result.segments[0].points[0].x).toBe(0);
      expect(result.segments[0].points[0].yAcc).toBeGreaterThanOrEqual(14);
      expect(result.segments[0].points[0].yAcc).toBeLessThanOrEqual(86);
      expect(result.segments[0].points[0].yLoss).toBeGreaterThanOrEqual(14);
      expect(result.segments[0].points[0].yLoss).toBeLessThanOrEqual(86);
    });

    it("handles totalEpochs=1 without division by zero", () => {
      const metrics: MetricPoint[] = [
        { epoca: 1, train_loss: 1.0, val_loss: 1.0, train_acc: 50, val_acc: 50, tiempo_epoca: 1.0 },
      ];

      const result = getChartPaths(metrics, { width: 300, height: 100, totalEpochs: 1 });
      expect(result.segments).toHaveLength(1);
      expect(result.segments[0].points[0].x).toBe(0);
    });

    it("infers model_index and architecture when legacy backend omits them (epoca resets)", () => {
      // Legacy metrics where model_index is missing, but epoca drops from 3 to 1
      const legacyMetrics: MetricPoint[] = [
        { epoca: 1, train_loss: 1.0, val_loss: 1.0, train_acc: 50, val_acc: 50, tiempo_epoca: 1 },
        { epoca: 2, train_loss: 0.8, val_loss: 0.8, train_acc: 60, val_acc: 60, tiempo_epoca: 1 },
        { epoca: 3, train_loss: 0.6, val_loss: 0.6, train_acc: 70, val_acc: 70, tiempo_epoca: 1 },
        { epoca: 1, train_loss: 1.2, val_loss: 1.1, train_acc: 40, val_acc: 42, tiempo_epoca: 1 },
        { epoca: 2, train_loss: 0.9, val_loss: 0.9, train_acc: 55, val_acc: 56, tiempo_epoca: 1 },
      ];

      const result = getChartPaths(legacyMetrics, {
        width: 300,
        height: 100,
        activeModelFilter: "all",
      });

      expect(result.segments).toHaveLength(2);
      expect(result.segments[0].modelIndex).toBe(1);
      expect(result.segments[1].modelIndex).toBe(2);
      expect(result.segments[0].points).toHaveLength(3);
      expect(result.segments[1].points).toHaveLength(2);
    });
  });
});

