"""Migration callable against synthetic historical schemas only."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text


def migration():
    path = Path(__file__).resolve().parents[1] / 'scripts/migrate_model_evaluations.py'
    spec = importlib.util.spec_from_file_location('evaluation_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_additive_idempotent_migration_preserves_legacy(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "legacy.sqlite"}')
    try:
        with engine.begin() as db:
            db.execute(text('CREATE TABLE modelo (id_modelo INTEGER PRIMARY KEY, precision FLOAT, activo BOOLEAN)'))
            db.execute(text('CREATE TABLE metrica_entrenamiento (id_metrica INTEGER PRIMARY KEY, precision FLOAT)'))
            db.execute(text('INSERT INTO modelo VALUES (1,86.75,1)'))
            db.execute(text('INSERT INTO metrica_entrenamiento VALUES (1,55)'))
        before = {t: inspect(engine).get_columns(t) for t in ('modelo', 'metrica_entrenamiento')}
        assert migration().migrate(engine) is True
        assert migration().migrate(engine) is False
        assert {t: inspect(engine).get_columns(t) for t in before}.keys() == before.keys()
        for table, columns in before.items():
            assert [(c['name'], str(c['type']), c['nullable']) for c in inspect(engine).get_columns(table)] == [
                (c['name'], str(c['type']), c['nullable']) for c in columns]
        with engine.connect() as db:
            assert db.execute(text('SELECT * FROM modelo')).all() == [(1,86.75,1)]
            assert db.execute(text('SELECT * FROM metrica_entrenamiento')).all() == [(1,55)]
            assert db.execute(text('SELECT * FROM model_evaluation')).all() == []
    finally:
        engine.dispose()


def test_changed_check_grouping_is_rejected_without_altering_table(tmp_path):
    from sqlalchemy import MetaData, Table, Column, Integer, CheckConstraint
    module = migration()
    engine = create_engine(f'sqlite:///{tmp_path / "grouping.sqlite"}')
    metadata = MetaData()
    Table('modelo', metadata, Column('id_modelo', Integer, primary_key=True))
    table = module.evaluation_table(metadata)
    for constraint in list(table.constraints):
        if isinstance(constraint, CheckConstraint) and constraint.name == 'evaluation_report':
            table.constraints.remove(constraint)
    table.append_constraint(CheckConstraint(
        "(status = 'completed' AND report IS NOT NULL AND error_reason IS NULL OR "
        "status != 'completed') AND report IS NULL", name='evaluation_report'))
    metadata.create_all(engine)
    try:
        before = inspect(engine).get_check_constraints('model_evaluation')
        with pytest.raises(ValueError, match='Incompatible evaluation check constraints'):
            module.migrate(engine)
        assert inspect(engine).get_check_constraints('model_evaluation') == before
    finally:
        engine.dispose()


def test_installed_v1_table_requires_separate_upgrade_without_mutation(tmp_path):
    from sqlalchemy import MetaData, Table, Column, Integer, CheckConstraint
    module = migration()
    engine = create_engine(f'sqlite:///{tmp_path / "v1.sqlite"}')
    metadata = MetaData()
    Table('modelo', metadata, Column('id_modelo', Integer, primary_key=True))
    table = module.evaluation_table(metadata)
    for constraint in list(table.constraints):
        if isinstance(constraint, CheckConstraint) and constraint.name == 'evaluation_counts':
            table.constraints.remove(constraint)
    table.append_constraint(CheckConstraint('sample_count > 0 AND schema_version = 1',
                                            name='evaluation_counts'))
    metadata.create_all(engine)
    try:
        before = inspect(engine).get_check_constraints('model_evaluation')
        with pytest.raises(ValueError, match='Incompatible evaluation check constraints'):
            module.migrate(engine)
        assert inspect(engine).get_check_constraints('model_evaluation') == before
    finally:
        engine.dispose()


def test_preexisting_extra_uniqueness_is_incompatible(tmp_path):
    from sqlalchemy import MetaData, Table, Column, Integer
    module = migration()
    engine = create_engine(f'sqlite:///{tmp_path / "unique.sqlite"}')
    metadata = MetaData()
    Table('modelo', metadata, Column('id_modelo', Integer, primary_key=True))
    table = module.evaluation_table(metadata)
    table.c.dataset.unique = True
    from sqlalchemy import UniqueConstraint
    table.append_constraint(UniqueConstraint('dataset'))
    metadata.create_all(engine)
    try:
        with pytest.raises(ValueError, match='Incompatible'):
            module.migrate(engine)
    finally:
        engine.dispose()


@pytest.mark.parametrize('missing', ['foreign_key', 'checks'])
def test_full_column_table_with_missing_constraints_fails_closed(tmp_path, missing):
    from sqlalchemy import MetaData, Table, Column, Integer, CheckConstraint, ForeignKeyConstraint
    module = migration()
    engine = create_engine(f'sqlite:///{tmp_path / "constraints.sqlite"}')
    metadata = MetaData()
    Table('modelo', metadata, Column('id_modelo', Integer, primary_key=True))
    table = module.evaluation_table(metadata)
    constraint_type = ForeignKeyConstraint if missing == 'foreign_key' else CheckConstraint
    for constraint in list(table.constraints):
        if isinstance(constraint, constraint_type):
            table.constraints.remove(constraint)
    metadata.create_all(engine)
    try:
        with pytest.raises(ValueError, match='Incompatible'):
            module.migrate(engine)
    finally:
        engine.dispose()


@pytest.mark.parametrize('name,sql', [
    ('evaluation_status', "((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying])::text[]))"),
    ('evaluation_split', "((split)::text = ANY ((ARRAY['val'::character varying, 'test'::character varying])::text[]))"),
    ('evaluation_counts', '((sample_count > 0) AND (schema_version = ANY (ARRAY[1, 2])))'),
    ('evaluation_report', "((((status)::text = 'completed'::text) AND (report IS NOT NULL) AND (error_reason IS NULL)) OR (((status)::text <> 'completed'::text) AND (report IS NULL)))"),
    ('evaluation_error', "((((status)::text = 'failed'::text) AND (error_reason IS NOT NULL)) OR (((status)::text <> 'failed'::text) AND (error_reason IS NULL)))"),
    ('evaluation_times', "((((status)::text = 'pending'::text) AND (started_at IS NULL) AND (finished_at IS NULL)) OR (((status)::text = 'running'::text) AND (started_at IS NOT NULL) AND (finished_at IS NULL)) OR (((status)::text = ANY ((ARRAY['completed'::character varying, 'failed'::character varying])::text[])) AND (finished_at IS NOT NULL)))"),
])
def test_postgresql_catalog_spelling_fixtures_structural_only(name, sql):
    """Hand-authored catalog fixtures; no PostgreSQL database was exercised."""
    from sqlalchemy import MetaData, CheckConstraint
    from sqlalchemy.dialects.postgresql import dialect
    module = migration()
    table = module.evaluation_table(MetaData())
    checks = [{'name': str(c.name), 'sqltext': str(c.sqltext)}
              for c in table.constraints if isinstance(c, CheckConstraint)]
    target = next(c for c in checks if c['name'] == name)
    target['sqltext'] = sql
    assert module._checks_match(table, dialect(), checks)
    # Whitespace outside literals is harmless; literal content is significant.
    target['sqltext'] = sql.replace(' AND ', '\n AND\t')
    assert module._checks_match(table, dialect(), checks)
    target['sqltext'] = '(' + sql + ')'
    assert not module._checks_match(table, dialect(), checks)  # unknown spelling


@pytest.mark.parametrize('sql', [
    "((((status)::text = 'completed'::text) AND (report IS NOT NULL) AND (error_reason IS NULL) OR ((status)::text <> 'completed'::text)) AND (report IS NULL))",
    "((status)::text = ANY ((ARRAY['pend ing'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying])::text[]))",
])
def test_postgresql_unknown_or_changed_fixture_rejected_structural_only(sql):
    from sqlalchemy import MetaData, CheckConstraint
    from sqlalchemy.dialects.postgresql import dialect
    module = migration()
    table = module.evaluation_table(MetaData())
    checks = [{'name': str(c.name), 'sqltext': str(c.sqltext)}
              for c in table.constraints if isinstance(c, CheckConstraint)]
    name = 'evaluation_status' if 'pend ing' in sql else 'evaluation_report'
    next(c for c in checks if c['name'] == name)['sqltext'] = sql
    assert not module._checks_match(table, dialect(), checks)


def test_cli_requires_explicit_apply_and_url(tmp_path):
    import subprocess
    import sys
    script = Path(__file__).resolve().parents[1] / 'scripts/migrate_model_evaluations.py'
    env = {'PYTHONDONTWRITEBYTECODE': '1'}
    missing_apply = subprocess.run([sys.executable, str(script)], env=env,
                                   capture_output=True, text=True)
    assert missing_apply.returncode == 2 and '--apply' in missing_apply.stderr
    missing_url = subprocess.run([sys.executable, str(script), '--apply'], env=env,
                                 capture_output=True, text=True)
    assert missing_url.returncode == 2 and 'DATABASE_URL must be supplied explicitly' in missing_url.stderr


@pytest.mark.parametrize('definition', [
    'id_evaluation INTEGER PRIMARY KEY',
    'id_evaluation INTEGER PRIMARY KEY, status VARCHAR(10) NOT NULL',
])
def test_incompatible_preexisting_table_fails_closed(tmp_path, definition):
    engine = create_engine(f'sqlite:///{tmp_path / "incompatible.sqlite"}')
    try:
        with engine.begin() as db:
            db.execute(text('CREATE TABLE modelo (id_modelo INTEGER PRIMARY KEY)'))
            db.execute(text(f'CREATE TABLE model_evaluation ({definition})'))
        before = inspect(engine).get_columns('model_evaluation')
        with pytest.raises(ValueError, match='Incompatible'):
            migration().migrate(engine)
        assert [c['name'] for c in inspect(engine).get_columns('model_evaluation')] == [c['name'] for c in before]
    finally:
        engine.dispose()
