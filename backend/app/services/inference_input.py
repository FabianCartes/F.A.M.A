"""Validate WAV metadata without decoding an unbounded waveform."""
import io

import soundfile as sf


MAX_AUDIO_DURATION_SECONDS = 300


class InvalidInferenceAudio(ValueError):
    pass


def validate_audio(audio_bytes):
    try:
        metadata = sf.info(io.BytesIO(audio_bytes))
    except (sf.LibsndfileError, ValueError, RuntimeError) as error:
        raise InvalidInferenceAudio("Audio inválido. Proporcione un archivo WAV válido.") from error
    if metadata.format not in {"WAV", "WAVEX", "RF64"} or min(
        metadata.frames, metadata.samplerate, metadata.channels
    ) <= 0:
        raise InvalidInferenceAudio("Audio inválido. Proporcione un WAV con muestras válidas.")
    # Integer comparison keeps the inclusive boundary independent of rounding.
    if metadata.frames > MAX_AUDIO_DURATION_SECONDS * metadata.samplerate:
        raise InvalidInferenceAudio("El audio supera la duración máxima de 300 segundos. No se recorta.")
