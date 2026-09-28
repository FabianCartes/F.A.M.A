/**
 * Presets estándar y validadores de física acústica multi-dominio para el entrenamiento bioacústico e industrial.
 */

export type AudioDomainPresetKey = "bioacoustics" | "industrial" | "medical_cough" | "custom";

export interface DomainPresetConfig {
  target_sr: number;
  duration_seconds: number;
  f_min: number;
  f_max: number;
  n_mels: number;
  n_fft: number;
  hop_length: number;
  hop_seconds: number;
  aggregation_mode: "max" | "mean";
  gem_p: number;
  vad_threshold: number;
  loss_type: "focal" | "cross_entropy";
  focal_gamma: number;
  mixup: boolean;
  mixup_alpha: number;
  pitch_shift: boolean;
  label: string;
  description: string;
}

export const AUDIO_DOMAIN_PRESETS: Record<AudioDomainPresetKey, DomainPresetConfig> = {
  bioacoustics: {
    target_sr: 22050,
    duration_seconds: 5.0,
    f_min: 800,
    f_max: 10000,
    n_mels: 128,
    n_fft: 2048,
    hop_length: 512,
    hop_seconds: 1.0,
    aggregation_mode: "max",
    gem_p: 3.0,
    vad_threshold: 0.0,
    loss_type: "focal",
    focal_gamma: 2.0,
    mixup: true,
    mixup_alpha: 0.2,
    pitch_shift: false,
    label: "Bioacústica (Aves)",
    description: "Espectrogramas para fauna silvestre (800-10.000 Hz @ 22.05 kHz)",
  },
  industrial: {
    target_sr: 32000,
    duration_seconds: 1.5,
    f_min: 50,
    f_max: 16000,
    n_mels: 128,
    n_fft: 2048,
    hop_length: 512,
    hop_seconds: 0.75,
    aggregation_mode: "mean",
    gem_p: 2.0,
    vad_threshold: 0.0,
    loss_type: "cross_entropy",
    focal_gamma: 2.0,
    mixup: false,
    mixup_alpha: 0.2,
    pitch_shift: false,
    label: "Diagnóstico Industrial",
    description: "Vibraciones mecánicas y armónicos de motores (50-16.000 Hz @ 32 kHz)",
  },
  medical_cough: {
    target_sr: 16000,
    duration_seconds: 2.0,
    f_min: 50,
    f_max: 4000,
    n_mels: 128,
    n_fft: 1024,
    hop_length: 256,
    hop_seconds: 0.5,
    aggregation_mode: "max",
    gem_p: 3.0,
    vad_threshold: 0.05,
    loss_type: "focal",
    focal_gamma: 2.0,
    mixup: false,
    mixup_alpha: 0.2,
    pitch_shift: false,
    label: "Tos Médica",
    description: "Eventos breves de fonación y tos humana (50-4.000 Hz @ 16 kHz)",
  },
  custom: {
    target_sr: 22050,
    duration_seconds: 5.0,
    f_min: 0,
    f_max: 10000,
    n_mels: 128,
    n_fft: 2048,
    hop_length: 512,
    hop_seconds: 1.0,
    aggregation_mode: "max",
    gem_p: 3.0,
    vad_threshold: 0.0,
    loss_type: "focal",
    focal_gamma: 2.0,
    mixup: false,
    mixup_alpha: 0.2,
    pitch_shift: false,
    label: "Personalizado",
    description: "Configuración manual de hiperparámetros acústicos y ventaneo denso",
  },
};

/**
 * Valida la cota de Nyquist (f_max <= target_sr / 2).
 */
export function validateNyquist(f_max: number, target_sr: number): boolean {
  return f_max <= target_sr / 2;
}

/**
 * Valida que la frecuencia mínima sea estrictamente menor a la máxima.
 */
export function validateFrequencyRange(f_min: number, f_max: number): boolean {
  return f_min < f_max;
}

/**
 * Valida de forma combinada los invariantes de física acústica.
 */
export function validateAudioPhysics(config: {
  target_sr: number;
  f_min: number;
  f_max: number;
}): { valid: boolean; error?: string } {
  if (!validateNyquist(config.f_max, config.target_sr)) {
    return {
      valid: false,
      error: `Violación de Nyquist: f_max (${config.f_max} Hz) supera target_sr / 2 (${config.target_sr / 2} Hz).`,
    };
  }
  if (!validateFrequencyRange(config.f_min, config.f_max)) {
    return {
      valid: false,
      error: `f_min (${config.f_min} Hz) debe ser estrictamente menor que f_max (${config.f_max} Hz).`,
    };
  }
  return { valid: true };
}
