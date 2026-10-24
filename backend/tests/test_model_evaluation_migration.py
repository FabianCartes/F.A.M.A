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


# SQLAlchemy's PostgreSQL inspector exposes sqltext without the outer CHECK (...) wrapper.
# These bodies are the exact pg_get_constraintdef results captured from PostgreSQL.
_POSTGRES_INSPECTOR_CHECKS = [
    ('evaluation_counts', 'sample_count > 0 AND (schema_version = ANY (ARRAY[1, 2]))'),
    ('evaluation_error', "status::text = 'failed'::text AND error_reason IS NOT NULL OR status::text <> 'failed'::text AND error_reason IS NULL"),
    ('evaluation_report', "status::text = 'completed'::text AND report IS NOT NULL AND error_reason IS NULL OR status::text <> 'completed'::text AND report IS NULL"),
    ('evaluation_split', "split::text = ANY (ARRAY['val'::character varying, 'test'::character varying]::text[])"),
    ('evaluation_status', "status::text = ANY (ARRAY['pending'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying]::text[])"),
    ('evaluation_times', "status::text = 'pending'::text AND started_at IS NULL AND finished_at IS NULL OR status::text = 'running'::text AND started_at IS NOT NULL AND finished_at IS NULL OR (status::text = ANY (ARRAY['completed'::character varying, 'failed'::character varying]::text[])) AND finished_at IS NOT NULL"),
]


def _run_postgresql_catalog_verification(monkeypatch, checks):
    from sqlalchemy import MetaData
    from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
    module = migration()
    table = module.evaluation_table(MetaData())

    class Inspector:
        def has_table(self, name):
            return name in {'modelo', 'model_evaluation'}

        def get_columns(self, name):
            return [{'name': column.name, 'nullable': column.nullable,
                     'type': column.type, 'default': None} for column in table.columns]

        def get_pk_constraint(self, name):
            return {'constrained_columns': ['id_evaluation']}

        def get_foreign_keys(self, name):
            return [{'constrained_columns': ['id_modelo'], 'referred_table': 'modelo',
                     'referred_columns': ['id_modelo'], 'options': {'ondelete': 'RESTRICT'}}]

        def get_unique_constraints(self, name):
            return []

        def get_indexes(self, name):
            return []

        def get_check_constraints(self, name):
            return [{'name': check_name, 'sqltext': sqltext} for check_name, sqltext in checks]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Engine:
        dialect = postgresql_dialect()

        def begin(self):
            return Connection()

    monkeypatch.setattr(module, 'inspect', lambda connection: Inspector())
    return module.migrate(Engine())


def test_migration_accepts_exact_postgresql_catalog_check_bodies(monkeypatch):
    assert _run_postgresql_catalog_verification(
        monkeypatch, _POSTGRES_INSPECTOR_CHECKS) is False


@pytest.mark.parametrize('case', ['changed_condition', 'missing_status', 'changed_split',
                                  'changed_schema_versions', 'regrouped_and_or'])
def test_migration_rejects_nonmatching_postgresql_catalog_checks(monkeypatch, case):
    checks = list(_POSTGRES_INSPECTOR_CHECKS)
    if case == 'changed_condition':
        index = next(i for i, (name, _) in enumerate(checks) if name == 'evaluation_counts')
        checks[index] = (checks[index][0], checks[index][1].replace('sample_count > 0', 'sample_count >= 0'))
    elif case == 'missing_status':
        checks = [check for check in checks if check[0] != 'evaluation_status']
    elif case == 'changed_split':
        index = next(i for i, (name, _) in enumerate(checks) if name == 'evaluation_split')
        checks[index] = (checks[index][0], checks[index][1].replace("'test'", "'other'"))
    elif case == 'changed_schema_versions':
        index = next(i for i, (name, _) in enumerate(checks) if name == 'evaluation_counts')
        checks[index] = (checks[index][0], checks[index][1].replace('ARRAY[1, 2]', 'ARRAY[1, 3]'))
    else:
        index = next(i for i, (name, _) in enumerate(checks) if name == 'evaluation_report')
        checks[index] = (checks[index][0], "(status::text = 'completed'::text AND report IS NOT NULL AND error_reason IS NULL OR status::text <> 'completed'::text) AND report IS NULL")

    with pytest.raises(ValueError, match='Incompatible evaluation check constraints'):
        _run_postgresql_catalog_verification(monkeypatch, checks)


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
