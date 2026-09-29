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
 * Valida que la duración de la ventana de análisis esté en un rango físico válido (> 0 y entre 0.5 y 30.0 s).
 */
export function validateWindowDuration(duration_seconds: number): boolean {
  return (
    typeof duration_seconds === "number" &&
    !isNaN(duration_seconds) &&
    duration_seconds >= 0.5 &&
    duration_seconds <= 30.0
  );
}

/**
 * Valida que el exponente GeM esté en un rango físicamente estable (1.0 <= p <= 10.0). No puede ser 0.
 */
export function validateGemP(p: number): boolean {
  return typeof p === "number" && !isNaN(p) && p >= 1.0 && p <= 10.0;
}

/**
 * Valida que el salto temporal del ventaneo esté en un rango válido (0.1 <= hop <= 10.0 s). No puede ser 0.
 */
export function validateHopSeconds(hop: number): boolean {
  return typeof hop === "number" && !isNaN(hop) && hop >= 0.1 && hop <= 10.0;
}

/**
 * Valida que el umbral VAD energético esté en el rango [0.0, 1.0].
 */
export function validateVadThreshold(threshold: number): boolean {
  return typeof threshold === "number" && !isNaN(threshold) && threshold >= 0.0 && threshold <= 1.0;
}

/**
 * Valida que el parámetro focal gamma esté en el rango [0.0, 5.0].
 */
export function validateFocalGamma(gamma: number): boolean {
  return typeof gamma === "number" && !isNaN(gamma) && gamma >= 0.0 && gamma <= 5.0;
}

/**
 * Valida de forma combinada los invariantes de física acústica.
 */
export function validateAudioPhysics(config: {
  target_sr: number;
  f_min: number;
  f_max: number;
  duration_seconds?: number;
}): { valid: boolean; error?: string; field?: "f_max" | "f_min" | "target_sr" | "duration_seconds" } {
  if (isNaN(config.target_sr)) {
    return {
      valid: false,
      field: "target_sr",
      error: "El campo 'Tasa de Muestreo' no puede estar vacío.",
    };
  }
  if (config.target_sr < 8000 || config.target_sr > 48000) {
    return {
      valid: false,
      field: "target_sr",
      error: "Tasa de Muestreo: Debe estar entre 8.000 Hz y 48.000 Hz.",
    };
  }
  if (config.duration_seconds !== undefined) {
    if (isNaN(config.duration_seconds) || config.duration_seconds <= 0) {
      return {
        valid: false,
        field: "duration_seconds",
        error: "Duración de Ventana: No puede ser 0 segundos ni negativa (mínimo 0.5 s).",
      };
    }
    if (config.duration_seconds < 0.5 || config.duration_seconds > 30.0) {
      return {
        valid: false,
        field: "duration_seconds",
        error: "Duración de Ventana: Debe estar en el rango de 0.5 s a 30.0 s.",
      };
    }
  }
  if (isNaN(config.f_min)) {
    return {
      valid: false,
      field: "f_min",
      error: "El campo 'Frecuencia Mínima' no puede estar vacío.",
    };
  }
  if (config.f_min < 0) {
    return {
      valid: false,
      field: "f_min",
      error: "Frecuencia Mínima: No puede ser negativa.",
    };
  }
  if (isNaN(config.f_max)) {
    return {
      valid: false,
      field: "f_max",
      error: "El campo 'Frecuencia Máxima' no puede estar vacío.",
    };
  }
  if (!validateNyquist(config.f_max, config.target_sr)) {
    return {
      valid: false,
      field: "f_max",
      error: `Violación de Nyquist: La Frecuencia Máxima (${config.f_max.toLocaleString("es-CL")} Hz) supera la mitad de la Tasa de Muestreo (${(config.target_sr / 2).toLocaleString("es-CL")} Hz).`,
    };
  }
  if (!validateFrequencyRange(config.f_min, config.f_max)) {
    return {
      valid: false,
      field: "f_min",
      error: `Rango Espectral: La Frecuencia Mínima (${config.f_min.toLocaleString("es-CL")} Hz) debe ser estrictamente menor que la Frecuencia Máxima (${config.f_max.toLocaleString("es-CL")} Hz).`,
    };
  }
  return { valid: true };
}

