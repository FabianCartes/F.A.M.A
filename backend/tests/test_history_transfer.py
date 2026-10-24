"""Operator CLI over two exclusive PostgreSQL databases; no application mocks."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def history(tmp_path):
    reference = os.environ.get('FAMA_TEST_HISTORY_ADMIN_URL_FILE')
    if not reference:
        pytest.skip('Requires an explicitly selected exclusive PostgreSQL laboratory')
    base = make_url(Path(reference).read_text(encoding='utf-8'))
    assert base.host == '127.0.0.1' and base.database == 'postgres' and base.port not in (5432, 5433, 5434)
    names = ['history_source_' + uuid.uuid4().hex, 'history_target_' + uuid.uuid4().hex]
    admin = create_engine(base, isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:
        for name in names:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    source, target = [create_engine(base.set(database=name)) for name in names]
    from migrations.schema_0002 import metadata, CORE_TABLES
    legacy = MetaData()
    for name in CORE_TABLES:
        metadata.tables[name].to_metadata(legacy)
    legacy.create_all(source)
    from app.schema import upgrade_schema
    assert upgrade_schema(target.url.render_as_string(hide_password=False)).code == 'schema_current'
    instant = datetime(2025, 5, 7, 12, 30, tzinfo=timezone.utc)
    from app.passwords import hash_password
    password_hash = hash_password('PreservedSyntheticAccount2026!')
    values = {
        'usuario': dict(id_usuario=9, correo_electronico='preserved@fama.test', hash_contrasena=password_hash,
                        rol='administrador', nombre_completo='Cuenta histórica', activo=True,
                        fecha_creacion=instant, ultimo_acceso=None),
        'conjunto_datos': dict(id_conjunto_datos=21, nombre='Historical', ruta_gcp='gs://synthetic/datasets/Historical/',
                              estado='disponible', id_usuario_carga=9, fecha_carga=instant, tamano_total_bytes=50,
                              cantidad_audios=1, finalidad='Investigación', base_licitud='consentimiento'),
        'audio': dict(id_audio=25, id_conjunto_datos=21, nombre_archivo='original.wav',
                      ruta_gcp='datasets/Historical/Bird/original.wav', clase='Bird', frecuencia_muestreo=16000,
                      duracion_segundos=1.5, tamano_bytes=50, hash_archivo='a' * 64, fecha_subida=instant),
        'modelo': dict(id_modelo=88, id_usuario=9, id_conjunto_datos=None, clase_objetivo='Bird', actualizacion_de=None,
                       arquitectura='CNN', epocas=1, tasa_aprendizaje=.001, tamano_lote=2, precision=.7, perdida=.3,
                       ruta_binario_gcp='models/original.pth', tamano_bytes=123, hash_binario='b' * 64,
                       activo=True, estado='completado', fecha_entrenamiento=instant),
        'prediccion': dict(id_prediccion=111, ruta_audio_prueba='raw_audios/old.wav', etiqueta_predicha='Bird',
                           confianza=.8, modelo_id='88', dataset_name='Historical', nombre_original='old.wav',
                           fecha_carga=instant, fecha_prediccion=instant),
        'retroalimentacion': dict(id_retroalimentacion=31, id_prediccion=111, id_usuario=9,
                                  etiqueta_corregida='Bird', fue_correcta=True, procesado=True,
                                  fecha_retroalimentacion=instant),
        'feedback_sync': dict(id_retroalimentacion=31, dataset_name='Historical', storage_class='Bird', class_label='Bird',
                              object_key='datasets/Historical/Bird/feedback_31.wav',
                              local_relative_path='Historical/Bird/feedback_31.wav', sha256='c' * 64,
                              status='synced', attempts=3, error_code=None),
        'metrica_entrenamiento': dict(id_metrica=14, id_modelo=88, epoca=1, precision=.7, perdida=.3,
                                     puntuacion_validacion=.6, tiempo_epoca=3.5),
    }
    with source.begin() as connection:
        for name, row in values.items():
            connection.execute(legacy.tables[name].insert().values(**row))
        for table in legacy.tables.values():
            if table.name != 'feedback_sync':
                pk = list(table.primary_key)[0].name
                connection.execute(text('SELECT setval(pg_get_serial_sequence(:table,:column),700,true)'),
                                   {'table':table.name, 'column':pk})
    paths = []
    for label, engine in [('source', source), ('target', target)]:
        path = tmp_path / (label + '-url')
        path.write_text(engine.url.render_as_string(hide_password=False), encoding='utf-8')
        paths.append(path)
    try:
        yield source, target, paths, values
    finally:
        source.dispose()
        target.dispose()
        with admin.connect() as connection:
            for name in names:
                connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def cli(history, operation='plan', *arguments, paths=None):
    source, target, references, _ = history
    references = paths or references
    environment = {k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','TEMP','TMP'}}
    environment.update(PYTHON_DOTENV_DISABLED='1', PYTHONUTF8='1',
                       DATABASE_URL='postgresql://wrong:MustNeverAppear@127.0.0.1:1/wrong')
    result = subprocess.run([sys.executable, '-m', 'app.history_transfer',
        '--source-url-file', str(references[0]), '--target-url-file', str(references[1]), operation, *arguments],
        cwd=BACKEND, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=30)
    return result, json.loads(result.stdout) if result.stdout.strip() else {}


def apply(history, digest):
    return cli(history, 'apply', '--apply', '--confirm-source', history[0].url.database,
               '--confirm-target', history[1].url.database, '--expect-digest', digest)


def test_operator_previews_and_transfers_known_history_without_inventing_permissions(history):
    result, plan = cli(history)
    assert result.returncode == 0, result.stdout + result.stderr
    assert plan['code'] == 'history_transfer_ready'
    assert plan['rows'] == {name:1 for name in history[3]}
    assert plan['warnings']['models_without_dataset'] == 1
    with history[1].connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM usuario')) == 0
    result, report = apply(history, plan['digest'])
    assert result.returncode == 0, result.stdout + result.stderr
    assert report['code'] == 'history_transferred'
    assert report['digest'] == plan['digest']
    for engine in history[:2]:
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT id_usuario FROM usuario')) == 9
    with history[1].connect() as connection:
        from app.passwords import verify_password
        assert verify_password('PreservedSyntheticAccount2026!', connection.scalar(text('SELECT hash_contrasena FROM usuario')))
        assert connection.execute(text('SELECT incorporated_by,incorporated_at,status FROM feedback_sync')).one() == (None,None,'synced')
        assert connection.scalar(text('SELECT id_conjunto_datos FROM modelo')) is None
        for name in ('asignacion_dataset','acceso_prediccion','sesion_web','recuperacion_cuenta','solicitud_dataset'):
            assert connection.scalar(text(f'SELECT count(*) FROM {name}')) == 0
        assert connection.scalar(text("SELECT nextval(pg_get_serial_sequence('usuario','id_usuario'))")) == 701
    assert 'preserved@fama.test' not in result.stdout + result.stderr
    assert history[3]['usuario']['hash_contrasena'] not in result.stdout + result.stderr
    assert 'MustNeverAppear' not in result.stdout + result.stderr


def test_pending_historical_feedback_requires_review_before_transfer(history):
    with history[0].begin() as connection:
        connection.execute(text("UPDATE feedback_sync SET status='pending'"))
    result, report = cli(history)
    assert result.returncode == 1
    assert report == {'code':'history_pending_feedback_requires_review'}
    with history[1].connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM usuario')) == 0


def test_source_without_an_active_administrator_is_not_silently_adopted(history):
    with history[0].begin() as connection:
        connection.execute(text('UPDATE usuario SET activo=false'))
    result, report = cli(history)
    assert result.returncode == 1
    assert report == {'code':'history_active_administrator_required'}


def test_inconsistent_historical_sequence_is_rejected_before_any_copy(history):
    with history[0].begin() as connection:
        connection.execute(text("SELECT setval(pg_get_serial_sequence('usuario','id_usuario'),1,true)"))
    result, report = cli(history)
    assert result.returncode == 1
    assert report == {'code':'history_sequence_invalid'}


@pytest.mark.parametrize('side', [0, 1])
def test_unknown_procedural_objects_are_not_ignored(history, side):
    with history[side].begin() as connection:
        connection.execute(text('CREATE FUNCTION public.unrecognized() RETURNS integer LANGUAGE sql AS $$ SELECT 1 $$'))
    result, report = cli(history)
    assert result.returncode == 1
    assert report == {'code':'history_source_schema_invalid' if side == 0 else 'history_target_schema_invalid'}


def test_changed_source_rejects_stale_plan_without_writing_target(history):
    _, plan = cli(history)
    with history[0].begin() as connection:
        connection.execute(text("UPDATE usuario SET nombre_completo='Changed after preview'"))
    result, report = apply(history, plan['digest'])
    assert result.returncode == 1
    assert report == {'code':'history_source_changed'}
    with history[1].connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM usuario')) == 0


def test_repeated_apply_does_not_merge_or_duplicate_history(history):
    _, plan = cli(history)
    assert apply(history, plan['digest'])[0].returncode == 0
    result, report = apply(history, plan['digest'])
    assert result.returncode == 1
    assert report == {'code':'history_target_not_empty'}
    with history[1].connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM usuario')) == 1
        assert connection.scalar(text('SELECT count(*) FROM prediccion')) == 1


def test_migration_gate_prevents_transfer_while_another_operator_holds_it(history):
    _, plan = cli(history)
    with history[1].begin() as connection:
        connection.execute(text('SELECT pg_advisory_xact_lock(5065941)'))
        result, report = apply(history, plan['digest'])
    assert result.returncode == 1
    assert report == {'code':'history_target_busy'}


def test_late_SQL_failure_rolls_back_rows_and_prior_sequence_restarts(history):
    source, target, paths, _ = history
    role = 'history_writer_' + uuid.uuid4().hex
    password = 'SyntheticRestrictedWriter2026!'
    with target.begin() as connection:
        connection.execute(text(f'CREATE ROLE "{role}" LOGIN PASSWORD :password'), {'password':password})
        connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        connection.execute(text(f'GRANT ALL ON ALL TABLES IN SCHEMA public TO "{role}"'))
        connection.execute(text(f'GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO "{role}"'))
        connection.execute(text(f'ALTER TABLE usuario OWNER TO "{role}"'))
    alternate = paths[1].parent / 'restricted-target'
    alternate.write_text(target.url.set(username=role, password=password).render_as_string(hide_password=False))
    try:
        result, plan = cli(history, paths=[paths[0],alternate])
        assert result.returncode == 0
        result, report = cli(history, 'apply','--apply','--confirm-source',source.url.database,
            '--confirm-target',target.url.database,'--expect-digest',plan['digest'],paths=[paths[0],alternate])
        assert result.returncode == 1
        assert report == {'code':'history_transfer_unavailable'}
        assert password not in result.stdout + result.stderr
        with target.connect() as connection:
            assert connection.scalar(text('SELECT count(*) FROM usuario')) == 0
            assert connection.scalar(text('SELECT count(*) FROM feedback_sync')) == 0
            assert connection.execute(text('SELECT last_value,is_called FROM usuario_id_usuario_seq')).one() == (1,False)
    finally:
        with target.begin() as connection:
            connection.execute(text(f'REASSIGN OWNED BY "{role}" TO postgres'))
            connection.execute(text(f'DROP OWNED BY "{role}"'))
            connection.execute(text(f'DROP ROLE "{role}"'))


@pytest.mark.parametrize('option,value', [('confirm-source','wrong'), ('confirm-target','wrong')])
def test_explicit_database_confirmations_are_checked(history, option, value):
    _, plan = cli(history)
    source = value if option == 'confirm-source' else history[0].url.database
    target = value if option == 'confirm-target' else history[1].url.database
    result, report = cli(history,'apply','--apply','--confirm-source',source,
                         '--confirm-target',target,'--expect-digest',plan['digest'])
    assert result.returncode == 1
    assert report == {'code':'history_confirmation_required'}


def test_known_legacy_cascade_is_transferred_with_current_history_protection(history):
    with history[0].begin() as connection:
        connection.execute(text('ALTER TABLE retroalimentacion DROP CONSTRAINT retroalimentacion_id_prediccion_fkey'))
        connection.execute(text('ALTER TABLE retroalimentacion ADD CONSTRAINT retroalimentacion_id_prediccion_fkey '
                                'FOREIGN KEY(id_prediccion) REFERENCES prediccion(id_prediccion) ON DELETE CASCADE'))
    result, plan = cli(history)
    assert result.returncode == 0, result.stdout
    assert plan['warnings']['historical_feedback_cascade_replaced_by_restrict'] is True
    assert apply(history,plan['digest'])[0].returncode == 0
    from sqlalchemy import inspect
    assert inspect(history[1]).get_foreign_keys('retroalimentacion')[0]['options']['ondelete'] == 'RESTRICT'
