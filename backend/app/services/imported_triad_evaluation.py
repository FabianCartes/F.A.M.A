"""Read-only authoritative binding and JOINT evaluation of imported compositions.

Results are intentionally MEMORY ONLY: no Modelo, attempt, association, registry,
activation or history writes. T4c must re-admit all bindings before persistence /
publication; this result is not a catalogue entry or a durable availability claim.
The predictor ID is ``fama_triad_<composition SHA256>`` (not a component DB ID).
"""
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.models.training import Modelo
from app.models.imported_training_source import ImportedModelSource
from app.models.dataset_import import ImportedDataset
from app.services.imported_evaluation import evaluation_recordings
from app.services.recording_evaluator import RecordingEvaluator
from app.services.standard_evaluation_guard import (
    inspect_checkpoint, assert_checkpoint_unchanged, select_admitted_standard_pair,
    admitted_manifest_pair_provenance, ADMITTED_MANIFEST_PAIR_KEY,
)
from app.services.predictors.trained_predictor import TrainedModelPredictor
from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor


class ImportedTriadEvaluationError(ValueError):
    """Uniform, path-free failure for absent/foreign/corrupt/incompatible inputs."""
    code = 'composition_unavailable'

    def __init__(self):
        super().__init__('Composición importada no disponible.')


class ImportedTriadEvaluation:
    """Explicit injected sessions, manifest store, historical sources and root.

    evaluate(owner, composition_id) returns composition_id/manifest, predictor,
    canonical reports and EvaluationProvenance identities for val/test, plus a
    context of inspected checkpoints and resolved historical sources. Context has
    no live temporary audio paths; do not retain it as authorization. All three
    components (including weight zero) must be individually admitted and usable.
    """
    def __init__(self, sessions, manifests, sources, checkpoints_root):
        self.sessions = sessions
        self.manifests = manifests
        self.sources = sources
        self.checkpoints_root = Path(checkpoints_root)

    def _bind(self, owner, manifest):
        inspections, pairs = [], []
        with self.sessions() as db:
            for component in manifest['components']:
                row = db.get(Modelo, component['model_id'])
                association = db.get(ImportedModelSource, component['model_id'])
                identity = component['imported_source']
                dataset = db.get(ImportedDataset, identity['dataset_id'])
                if (row is None or association is None or dataset is None
                        or dataset.owner_id != owner or row.id_usuario != owner
                        or association.owner_id != owner or identity['owner_id'] != owner
                        or association.dataset_id != identity['dataset_id']
                        or association.snapshot_id != identity['snapshot_id']
                        or association.identity != identity
                        or row.hash_binario != component['checkpoint_sha256']
                        or type(row.tamano_bytes) is not int or row.tamano_bytes <= 0):
                    raise ImportedTriadEvaluationError()
                # Match registry's models/<basename> contract, but do not silently
                # substitute a trusted basename for an explicit foreign file URI.
                route = urlparse(row.ruta_binario_gcp)
                raw = Path(unquote(route.path))
                root = self.checkpoints_root.resolve(strict=True)
                if route.netloc or route.scheme not in ('', 'file') or '..' in raw.parts:
                    raise ImportedTriadEvaluationError()
                if raw.is_absolute():
                    path = raw.resolve(strict=True)
                elif route.scheme or len(raw.parts) > 2 or (len(raw.parts) == 2 and raw.parts[0] != 'models'):
                    raise ImportedTriadEvaluationError()
                else:
                    path = root / raw.name
                inspection = inspect_checkpoint(root, path, row.hash_binario, expected_size=row.tamano_bytes)
                if (inspection.payload.get('imported_source') != identity
                        or inspection.payload['architecture'] != row.arquitectura
                        or row.id_conjunto_datos is not None):
                    raise ImportedTriadEvaluationError()
                pair = select_admitted_standard_pair(row, db, root)
                if pair is None:
                    raise ImportedTriadEvaluationError()
                inspections.append(inspection)
                pairs.append(pair)
        return inspections, pairs

    def bind_current(self, owner, composition_id):
        """Metadata/checkpoint-only binding for durable readmission, never audio IO.

        Preparation.get verifies its content-addressed metadata and split digests;
        individual admitted reports supply the captured recording cohort hashes.
        No source resolve, neural construction/loading or evaluation is performed.
        """
        try:
            composition = self.manifests.get(owner, composition_id)
            manifest = composition['manifest']
            inspections, pairs = self._bind(owner, manifest)
            preparations = []
            for component in manifest['components']:
                identity = component['imported_source']
                preparation = self.sources.preparations.get(owner, identity['snapshot_id'],
                    identity['preparation_version'])
                snapshot = self.sources.preparations.snapshots.get(owner, identity['snapshot_id'])
                if (snapshot['dataset_id'] != identity['dataset_id']
                        or snapshot['manifest_sha256'] != identity['snapshot_manifest_sha256']
                        or preparation['profile'] != identity['profile']
                        or preparation['class_to_index'] != identity['class_to_index']
                        or preparation['provenance'] != identity['provenance']):
                    raise ImportedTriadEvaluationError()
                preparations.append(preparation)
            if any(any(p[key] != preparations[0][key] for key in ('seed', 'policy', 'provenance'))
                   for p in preparations):
                raise ImportedTriadEvaluationError()
            return dict(manifest=manifest, inspections=inspections, pairs=pairs,
                        preparations=preparations)
        except Exception:
            raise ImportedTriadEvaluationError() from None

    def evaluate(self, owner, composition_id):
        try:
            if type(owner) is not int or owner <= 0:
                raise ImportedTriadEvaluationError()
            composition = self.manifests.get(owner, composition_id)
            manifest = composition['manifest']
            inspections, pairs = self._bind(owner, manifest)
            cohort = manifest['cohort']
            sources = self.sources.resolve_triad(owner, cohort['dataset_id'], cohort['snapshot_id'], [
                {'version': c['imported_source']['preparation_version'],
                 'architecture': inspection.payload['architecture']}
                for c, inspection in zip(manifest['components'], inspections)])
            if any(source['identity'] != component['imported_source']
                   for source, component in zip(sources, manifest['components'])):
                raise ImportedTriadEvaluationError()
            components = [TrainedModelPredictor(inspection.path,
                model_id=f"fama_trained_model_{component['model_id']}", is_default=False,
                lazy_load=True, dataset_name=inspection.payload['dataset_name'],
                expected_checkpoint_sha256=component['checkpoint_sha256'])
                for component, inspection in zip(manifest['components'], inspections)]
            predictor = ImportedTriadPredictor(components, manifest['weights'], cohort['classes'],
                'fama_triad_' + composition_id, dataset_name='imported:' + cohort['dataset_id'])
            configs = dict(implementation='ImportedTriadPredictor', version='weighted-full-vector-v1',
                composition_id=composition_id, components=manifest['components'],
                weights=manifest['weights'], cohort=cohort,
                cohort_preparation={key: sources[0]['preparation']['manifest'][key]
                                    for key in ('seed', 'policy', 'provenance')},
                component_predictor_configs=[i.configurations[0] for i in inspections])
            # Every component keeps its own frontend; none impersonates the whole.
            preprocessing = {'components': [i.configurations[1] for i in inspections]}
            aggregation = dict(unit='recording', decision='weighted-full-vector-argmax',
                weights=manifest['weights'], rejection_statuses=['silence', 'noise'],
                rejection_policy='any-component-rejects',
                components=[i.configurations[2] for i in inspections])
            reports, identities = {}, {}
            with evaluation_recordings(sources[0]) as recordings:
                evaluators = {split: RecordingEvaluator(recordings[split], predictor,
                    dataset='imported:' + cohort['dataset_id'], split=split,
                    checkpoint_sha256=composition_id, predictor_config=configs,
                    preprocessing_config=preprocessing, aggregation_config=aggregation)
                    for split in ('val', 'test')}
                for pair in pairs:
                    for split, admitted in (('val', pair.val_identity), ('test', pair.test_identity)):
                        actual = evaluators[split].identity
                        if any(getattr(admitted, key) != getattr(actual, key) for key in (
                                'manifest_sha256', 'sample_count', 'classes', 'dataset')):
                            raise ImportedTriadEvaluationError()
                provenance = admitted_manifest_pair_provenance(
                    *(evaluators[s].identity.manifest_sha256 for s in ('val', 'test')))
                # Load ALL three before any inference, including zero-weight ones.
                predictor.load_weights()
                for split, evaluator in evaluators.items():
                    identity = evaluator.identity
                    evaluator.identity = type(identity).model_validate({**identity.model_dump(),
                        'predictor_config': {**identity.predictor_config, ADMITTED_MANIFEST_PAIR_KEY: provenance}})
                    for inspection in inspections:
                        assert_checkpoint_unchanged(inspection)
                    reports[split] = evaluator.evaluate()
                    identities[split] = evaluator.identity
                    for inspection in inspections:
                        assert_checkpoint_unchanged(inspection)
            self._bind(owner, manifest)  # Do not return success after a lost DB association.
            return dict(composition_id=composition_id, manifest=manifest, predictor=predictor,
                reports=reports, identities=identities,
                context={'inspections': tuple(inspections), 'sources': tuple(sources)})
        except Exception:
            raise ImportedTriadEvaluationError() from None
