import { describe, it, expect } from "vitest";
import {
  AUDIO_DOMAIN_PRESETS,
  validateNyquist,
  validateFrequencyRange,
  validateAudioPhysics,
  AudioDomainPresetKey,
} from "../audioDomainPresets";

describe("Audio Domain Presets and Physics Validation", () => {
  it("defines standard domain presets with exact physical configurations", () => {
    // Bioacoustics preset
    const bio = AUDIO_DOMAIN_PRESETS.bioacoustics;
    expect(bio.target_sr).toBe(22050);
    expect(bio.duration_seconds).toBe(5.0);
    expect(bio.f_min).toBe(800);
    expect(bio.f_max).toBe(10000);
    expect(bio.n_mels).toBe(128);
    expect(bio.n_fft).toBe(2048);
    expect(bio.hop_length).toBe(512);
    expect(bio.hop_seconds).toBe(1.0);
    expect(bio.aggregation_mode).toBe("max");
    expect(bio.gem_p).toBe(3.0);
    expect(bio.loss_type).toBe("focal");
    expect(bio.mixup).toBe(true);
    expect(bio.pitch_shift).toBe(false);

    // Industrial preset
    const ind = AUDIO_DOMAIN_PRESETS.industrial;
    expect(ind.target_sr).toBe(32000);
    expect(ind.duration_seconds).toBe(1.5);
    expect(ind.f_min).toBe(50);
    expect(ind.f_max).toBe(16000);
    expect(ind.n_mels).toBe(128);
    expect(ind.n_fft).toBe(2048);
    expect(ind.hop_length).toBe(512);
    expect(ind.hop_seconds).toBe(0.75);
    expect(ind.aggregation_mode).toBe("mean");
    expect(ind.gem_p).toBe(2.0);
    expect(ind.loss_type).toBe("cross_entropy");
    expect(ind.mixup).toBe(false);
    expect(ind.pitch_shift).toBe(false);

    // Medical cough preset
    const cough = AUDIO_DOMAIN_PRESETS.medical_cough;
    expect(cough.target_sr).toBe(16000);
    expect(cough.duration_seconds).toBe(2.0);
    expect(cough.f_min).toBe(50);
    expect(cough.f_max).toBe(4000);
    expect(cough.n_mels).toBe(128);
    expect(cough.n_fft).toBe(1024);
    expect(cough.hop_length).toBe(256);
    expect(cough.hop_seconds).toBe(0.5);
    expect(cough.aggregation_mode).toBe("max");
    expect(cough.gem_p).toBe(3.0);
    expect(cough.loss_type).toBe("focal");
    expect(cough.mixup).toBe(false);
    expect(cough.pitch_shift).toBe(false);

    // Custom preset exists
    expect(AUDIO_DOMAIN_PRESETS.custom).toBeDefined();
  });

  describe("Nyquist Validation", () => {
    it("validates Nyquist limit: f_max <= target_sr / 2", () => {
      // 10000 <= 22050 / 2 (11025) -> valid
      expect(validateNyquist(10000, 22050)).toBe(true);
      // 16000 <= 32000 / 2 (16000) -> valid
      expect(validateNyquist(16000, 32000)).toBe(true);
      // 9000 > 16000 / 2 (8000) -> invalid
      expect(validateNyquist(9000, 16000)).toBe(false);
    });
  });

  describe("Frequency Range Validation", () => {
    it("validates frequency range: f_min < f_max", () => {
      expect(validateFrequencyRange(50, 4000)).toBe(true);
      expect(validateFrequencyRange(4000, 4000)).toBe(false);
      expect(validateFrequencyRange(5000, 4000)).toBe(false);
    });
  });

  describe("Combined Physics Validation", () => {
    it("returns error details when constraints are violated", () => {
      const validRes = validateAudioPhysics({
        target_sr: 22050,
        f_min: 800,
        f_max: 10000,
      });
      expect(validRes.valid).toBe(true);
      expect(validRes.error).toBeUndefined();

      const nyquistViolation = validateAudioPhysics({
        target_sr: 16000,
        f_min: 50,
        f_max: 9000,
      });
      expect(nyquistViolation.valid).toBe(false);
      expect(nyquistViolation.error).toContain("Nyquist");

      const rangeViolation = validateAudioPhysics({
        target_sr: 22050,
        f_min: 12000,
        f_max: 10000,
      });
      expect(rangeViolation.valid).toBe(false);
      expect(rangeViolation.error).toContain("menor");
    });
  });
});
