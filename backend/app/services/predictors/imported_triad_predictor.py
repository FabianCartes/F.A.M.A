"""Explicit three-checkpoint fusion; publication and ownership belong to its consumer."""
import math
from pathlib import Path
import numpy as np
from app.schemas.model_info import ModelMetadata
from app.schemas.prediction import PredictionResult
from app.services.predictors.base import AudioPredictor, ModelWeightsError
from app.services.predictors.trained_predictor import TrainedModelPredictor, ClassVectorUnavailable


def _labels(labels):
    if (not labels or any(not isinstance(label, str) or not label for label in labels)
            or len(set(labels)) != len(labels)):
        raise ModelWeightsError('Invalid or duplicate class labels')
    return tuple(labels)


class ImportedTriadPredictor(AudioPredictor):
    """Ordered trained instances, weights summing to one, canonical classes and identity.

    No normalization or partial ensemble. Each instance owns its loading/audio contract.
    T4 must admit owner, artifacts and immutable composition before publication.
    """
    def __init__(self, components, weights, classes, model_id, *, dataset_name=None):
        self.components = tuple(components)
        if len(self.components) != 3 or any(not isinstance(p, TrainedModelPredictor) for p in self.components):
            raise ModelWeightsError('Exactly three trained components are required')
        self.weights = tuple(weights)
        if (len(self.weights) != 3
                or any(isinstance(w, bool) or not isinstance(w, (int, float))
                       or not math.isfinite(w) or w < 0 for w in self.weights)
                or not any(w > 0 for w in self.weights)
                or not math.isclose(sum(self.weights), 1, rel_tol=0, abs_tol=1e-9)):
            raise ModelWeightsError('Invalid triad weights')
        self.classes = _labels(classes)
        if not isinstance(model_id, str) or not model_id.strip():
            raise ModelWeightsError('A composition identity is required')
        self._model_id = model_id
        for component in self.components:
            if set(_labels(component.classes)) != set(self.classes):
                raise ModelWeightsError('Component class labels do not match')
        self._metadata = ModelMetadata(id=model_id, name=model_id,
            description='Imported three-component probability fusion',
            classes=list(self.classes), dataset_name=dataset_name)

    @property
    def metadata(self):
        self._metadata.has_weights = self.has_weights
        return self._metadata

    @property
    def has_weights(self):
        return all(p.has_weights for p in self.components)

    def load_weights(self):
        for component in self.components:
            component.load_weights()

    def predict(self, audio_file_path: Path) -> PredictionResult:
        combined = np.zeros(len(self.classes), dtype=np.float64)
        hashes, rejections = [], []
        for component, weight in zip(self.components, self.weights):
            try:
                result = component.predict_probabilities(audio_file_path)
            except ClassVectorUnavailable as rejection:
                rejections.append(rejection)
                continue  # Still validate every remaining component, even weight zero.
            labels = _labels(result['classes'])
            if set(labels) != set(self.classes):
                raise ModelWeightsError('Component class labels do not match')
            try:
                vector = np.asarray(result['probabilities'], dtype=np.float64)
            except (ValueError, TypeError) as error:
                raise ModelWeightsError('Invalid class probabilities') from error
            if (vector.shape != (len(labels),) or not np.isfinite(vector).all()
                    or (vector < 0).any() or (vector > 1).any()
                    or not math.isclose(float(vector.sum()), 1, rel_tol=0, abs_tol=1e-6)):
                raise ModelWeightsError('Invalid class probabilities')
            combined += weight * vector[[labels.index(label) for label in self.classes]]
            hashes.append(result['loaded_checkpoint_sha256'])
        if rejections:
            # No fabricated probabilities; first ordered explicit rejection wins.
            rejection = rejections[0]
            return PredictionResult(clase=rejection.result.clase, confianza=0.0,
                detalles={'status': rejection.status, 'model_id': self.model_id,
                    'component_ids': [p.model_id for p in self.components],
                    'weights': list(self.weights), 'ensemble_count': 3, 'is_mock': False})
        # Validated vectors and nonnegative weights bound overflow to the admitted
        # sum tolerance (plus floating roundoff). Keep supplied weights unchanged.
        combined = np.clip(combined, 0.0, 1.0)
        winner = int(combined.argmax())
        return PredictionResult(clase=self.classes[winner], confianza=float(combined[winner]),
            detalles={'status': 'classified', 'model_id': self.model_id,
                'component_ids': [p.model_id for p in self.components],
                'weights': list(self.weights), 'ensemble_count': 3,
                'classes': list(self.classes), 'probabilities': combined.tolist(),
                'loaded_checkpoint_sha256s': hashes, 'is_mock': False})
