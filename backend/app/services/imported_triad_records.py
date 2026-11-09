"""Durable evaluated compositions, deliberately NOT registry publication.

Modelo's mandatory training integers are neutral scaffolding (zero); no observed
training metrics or first-component hyperparameters are attributed to the triad.
The JSON descriptor SHA is the row artifact hash, not a neural checkpoint hash.
An existing import-job gate serializes reservation across processes. A pending
reservation is never retried/overwritten implicitly: an interrupted attempt must
be reconciled explicitly by a future operator workflow, not a catalogue read.
"""
import json

from app.models.training import Modelo, ModelEvaluation
from app.schemas.evaluation import EvaluationIdentity, validate_report
from app.services.dataset_import_jobs import _gate
from app.services.evaluations import EvaluationService
from app.services.imported_triad_evaluation import ImportedTriadEvaluationError
from app.services.predictors.trained_predictor import TrainedModelPredictor
from app.services.predictors.imported_triad_predictor import ImportedTriadPredictor
from app.services.standard_evaluation_guard import (
    ADMITTED_MANIFEST_PAIR_KEY, admitted_manifest_pair_provenance,
    assert_checkpoint_unchanged,
)

IMPORTED_TRIAD = 'ImportedTriad'
PENDING = 'imported_triad_pending'
EVALUATED = 'imported_triad_evaluated'


class ImportedTriadRecords:
    """Injected sessions/store/T4b evaluator; all public failures are uniform.

    evaluate_and_persist(owner, composition_id) owns the actual T4b evaluation.
    read_admitted(owner, model_id) never evaluates or creates attempts. Both return
    model (detached), manifest, lazy predictor with the DB registry key, pair_ids
    (val, test), and split provenance. Returned mutable data is NOT authority.
    """
    def __init__(self, sessions, manifests, evaluation):
        self.sessions, self.manifests, self.evaluation = sessions, manifests, evaluation

    @classmethod
    def for_training(cls, checkpoints_root):
        """Worker-local lazy configuration; reuse the catalogue's exact reader factory.

        Only training creates the private descriptor child. No sessions or model
        objects enter spawn configuration, and importing this module opens no DB.
        """
        from app.database import SessionLocal
        from app.services.imported_training_source import configured_sources
        from app.services.training_snapshots import _root_directory
        from app.services.registry import ModelRegistry
        sources = configured_sources(SessionLocal)
        with _root_directory(sources.preparations.root / 'triad-manifests'):
            pass
        return ModelRegistry()._triad_service(checkpoints_root)

    def complete_training(self, owner, components, *, cancelled=lambda: False):
        """Capture ordered references; persistence independently rebinds authority."""
        descriptor = self.manifests.create(owner, [dict(model_id=c['model_id'],
            checkpoint_sha256=c['sha256'], imported_source=c['source']) for c in components],
            [c['weight'] for c in components])
        saved = self.evaluate_and_persist(owner, descriptor['id'], cancelled=cancelled)
        return self.read_admitted(owner, saved['model'].id_modelo)

    def _artifact(self, owner, composition_id):
        composition = self.manifests.get(owner, composition_id)
        data = json.dumps(composition['manifest'], sort_keys=True, ensure_ascii=False,
                          allow_nan=False, separators=(',', ':')).encode('utf-8')
        # Store.get has already verified canonical bytes, SHA, root and owner.
        return composition['manifest'], (self.manifests.root / (composition_id + '.json')).as_uri(), len(data)

    def _matches(self, row, owner, composition_id, pointer, size, *, pending=False):
        if (row is None or type(owner) is not int or owner <= 0
                or row.id_usuario != owner or row.arquitectura != IMPORTED_TRIAD
                or row.estado != (PENDING if pending else EVALUATED)
                or row.id_conjunto_datos is not None or row.activo
                or row.hash_binario != composition_id or row.ruta_binario_gcp != pointer
                or type(row.tamano_bytes) is not int or row.tamano_bytes <= 0
                or row.tamano_bytes != size):
            raise ImportedTriadEvaluationError()

    def _unique(self, db, owner, composition_id, model_id):
        ids = db.query(Modelo.id_modelo).filter_by(id_usuario=owner,
            arquitectura=IMPORTED_TRIAD, hash_binario=composition_id).all()
        if ids != [(model_id,)]:
            raise ImportedTriadEvaluationError()

    def _pair(self, db, row, binding):
        manifest, inspections, pairs = (binding[k] for k in ('manifest', 'inspections', 'pairs'))
        composition_id = row.hash_binario
        cohort = manifest['cohort']
        first = pairs[0]
        # Individually admitted reports prove exactly the same evaluated cohort.
        for pair in pairs:
            for split in ('val', 'test'):
                identity = getattr(pair, split + '_identity')
                reference = getattr(first, split + '_identity')
                if any(getattr(identity, key) != getattr(reference, key)
                       for key in ('manifest_sha256', 'sample_count', 'classes', 'dataset')):
                    raise ImportedTriadEvaluationError()
        provenance = admitted_manifest_pair_provenance(
            first.val_identity.manifest_sha256, first.test_identity.manifest_sha256)
        predictor_config = dict(implementation='ImportedTriadPredictor', version='weighted-full-vector-v1',
            composition_id=composition_id, components=manifest['components'], weights=manifest['weights'],
            cohort=cohort, cohort_preparation={key: binding['preparations'][0][key]
                for key in ('seed', 'policy', 'provenance')},
            component_predictor_configs=[i.configurations[0] for i in inspections],
            **{ADMITTED_MANIFEST_PAIR_KEY: provenance})
        preprocessing = {'components': [i.configurations[1] for i in inspections]}
        aggregation = dict(unit='recording', decision='weighted-full-vector-argmax',
            weights=manifest['weights'], rejection_statuses=['silence', 'noise'],
            rejection_policy='any-component-rejects', components=[i.configurations[2] for i in inspections])
        rows = db.query(ModelEvaluation).filter_by(id_modelo=row.id_modelo).all()
        # No optimistic newest-pair selection: ambiguous/incomplete histories deny.
        if len(rows) != 2 or {r.split for r in rows} != {'val', 'test'}:
            raise ImportedTriadEvaluationError()
        admitted, identities = {}, {}
        for attempt in rows:
            reference = getattr(first, attempt.split + '_identity')
            expected = EvaluationIdentity.model_validate({**reference.model_dump(),
                'id_modelo': row.id_modelo, 'checkpoint_sha256': composition_id,
                'predictor_config': predictor_config, 'preprocessing_config': preprocessing,
                'aggregation_config': aggregation})
            actual = EvaluationIdentity.model_validate({key: getattr(attempt, key)
                                                        for key in EvaluationIdentity.model_fields})
            if (attempt.status != 'completed' or actual != expected
                    or attempt.error_reason is not None or attempt.started_at is None
                    or attempt.finished_at is None):
                raise ImportedTriadEvaluationError()
            report = validate_report(attempt.report, actual)
            if not report['coverage']['complete']:
                raise ImportedTriadEvaluationError()
            admitted[attempt.split] = attempt.id_evaluation
            identities[attempt.split] = actual.model_dump()
        return (admitted['val'], admitted['test']), identities

    def read_admitted(self, owner, model_id):
        try:
            if type(model_id) is not int or model_id <= 0 or type(owner) is not int or owner <= 0:
                raise ImportedTriadEvaluationError()
            with self.sessions() as db:
                row = db.get(Modelo, model_id)
                if row is None or row.id_usuario != owner or row.arquitectura != IMPORTED_TRIAD:
                    raise ImportedTriadEvaluationError()
                composition_id = row.hash_binario
                self._unique(db, owner, composition_id, model_id)
                manifest, pointer, size = self._artifact(owner, composition_id)
                self._matches(row, owner, composition_id, pointer, size)
                binding = self.evaluation.bind_current(owner, row.hash_binario)
                if binding['manifest'] != manifest:
                    raise ImportedTriadEvaluationError()
                pair_ids, provenance = self._pair(db, row, binding)
                components = [TrainedModelPredictor(i.path,
                    model_id=f"fama_trained_model_{c['model_id']}", is_default=False,
                    lazy_load=True, dataset_name=i.payload['dataset_name'],
                    expected_checkpoint_sha256=c['checkpoint_sha256'])
                    for c, i in zip(manifest['components'], binding['inspections'])]
                predictor = ImportedTriadPredictor(components, manifest['weights'], manifest['cohort']['classes'],
                    f'fama_trained_model_{model_id}', dataset_name='imported:' + manifest['cohort']['dataset_id'])
                # Final authoritative rebind + descriptor check; never trust a cached result.
                fresh = self.evaluation.bind_current(owner, composition_id)
                if self._artifact(owner, composition_id) != (manifest, pointer, size):
                    raise ImportedTriadEvaluationError()
                for inspection in binding['inspections']:
                    assert_checkpoint_unchanged(inspection)
                db.refresh(row)
                self._unique(db, owner, composition_id, model_id)
                self._matches(row, owner, composition_id, pointer, size)
                if self._pair(db, row, fresh) != (pair_ids, provenance):
                    raise ImportedTriadEvaluationError()
                db.expunge(row)
                return dict(model=row, manifest=manifest, predictor=predictor,
                            pair_ids=pair_ids, provenance=provenance)
        except Exception:
            raise ImportedTriadEvaluationError() from None

    admit = read_admitted

    def revise_weights(self, owner, model_id, weights):
        """Create (or idempotently return) a new admitted version with new weights.

        Service level only; HTTP/UI exposure is deliberately deferred to T5. The
        source must be freshly admitted for this owner. Same ordered components,
        new weights (existing manifest rules, no normalization) and its own joint
        evaluation/persistence. The previous composition, reports and manifest are
        never touched; no training, preparation, activation or default change.
        Every failure is the uniform private error.
        """
        try:
            source = self.read_admitted(owner, model_id)
            descriptor = self.manifests.create(owner, source['manifest']['components'], weights)
            saved = self.evaluate_and_persist(owner, descriptor['id'])
            return self.read_admitted(owner, saved['model'].id_modelo)
        except Exception:
            raise ImportedTriadEvaluationError() from None

    def evaluate_and_persist(self, owner, composition_id, *, cancelled=lambda: False):
        def check_cancelled():
            if cancelled():
                raise ImportedTriadEvaluationError()
        try:
            check_cancelled()
            manifest, pointer, size = self._artifact(owner, composition_id)
            # Idempotent reads do not rerun evaluation or append attempts.
            with self.sessions() as db:
                existing = db.query(Modelo).filter_by(id_usuario=owner,
                    arquitectura=IMPORTED_TRIAD, hash_binario=composition_id).all()
                if existing:
                    if len(existing) != 1:
                        raise ImportedTriadEvaluationError()
                    return self.read_admitted(owner, existing[0].id_modelo)
            result = self.evaluation.evaluate(owner, composition_id)
            check_cancelled()
            if result['manifest'] != manifest or self._artifact(owner, composition_id) != (manifest, pointer, size):
                raise ImportedTriadEvaluationError()
            self.evaluation.bind_current(owner, composition_id)
            for inspection in result['context']['inspections']:
                assert_checkpoint_unchanged(inspection)
            with self.sessions.begin() as db:
                _gate(db)  # Existing DB write lock, not an instance-local lock.
                existing = db.query(Modelo).filter_by(id_usuario=owner,
                    arquitectura=IMPORTED_TRIAD, hash_binario=composition_id).all()
                if len(existing) > 1:
                    raise ImportedTriadEvaluationError()
                if existing:
                    key = existing[0].id_modelo
                    if existing[0].estado != EVALUATED:
                        raise ImportedTriadEvaluationError()
                else:
                    row = Modelo(id_usuario=owner, id_conjunto_datos=None, arquitectura=IMPORTED_TRIAD,
                        clase_objetivo='imported composition', epocas=0, tasa_aprendizaje=0.0,
                        tamano_lote=0, precision=None, perdida=None, ruta_binario_gcp=pointer,
                        hash_binario=composition_id, tamano_bytes=size, activo=False, estado=PENDING)
                    db.add(row)
                    db.flush()
                    key = row.id_modelo
            if existing:
                return self.read_admitted(owner, key)
            # EvaluationService owns the append-only lifecycle and report validation.
            # A persistence failure retains a non-admitted pending reservation/history.
            with self.sessions() as db:
                evaluations = EvaluationService(db)
                for split in ('val', 'test'):
                    check_cancelled()
                    identity = {**result['identities'][split].model_dump(), 'id_modelo': key}
                    attempt = evaluations.create(identity)
                    evaluations.start(attempt['id_evaluation'])
                    evaluations.complete(attempt['id_evaluation'], result['reports'][split])
            check_cancelled()
            binding = self.evaluation.bind_current(owner, composition_id)
            if self._artifact(owner, composition_id) != (manifest, pointer, size):
                raise ImportedTriadEvaluationError()
            for inspection in result['context']['inspections']:
                assert_checkpoint_unchanged(inspection)
            with self.sessions.begin() as db:
                _gate(db)
                row = db.get(Modelo, key)
                self._matches(row, owner, composition_id, pointer, size, pending=True)
                self._pair(db, row, binding)
                check_cancelled()
                row.estado = EVALUATED
            return self.read_admitted(owner, key)
        except Exception:
            raise ImportedTriadEvaluationError() from None

    create = evaluate_and_persist
