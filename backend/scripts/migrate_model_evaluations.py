"""Add ONLY model_evaluation. Explicit DATABASE_URL and --apply; no app/dotenv imports.

Operator must back up and drain writers first. Never run automatically at startup.
"""
import argparse
import os
import re

from sqlalchemy import (Table, Column, Integer, String, JSON, DateTime, ForeignKey,
                        CheckConstraint, MetaData, create_engine, inspect)


def evaluation_table(metadata):
    """Shared definition without importing the production database module."""
    return Table(
        'model_evaluation', metadata,
        Column('id_evaluation', Integer, primary_key=True, autoincrement=True),
        Column('id_modelo', Integer, ForeignKey('modelo.id_modelo', ondelete='RESTRICT'), nullable=False),
        Column('schema_version', Integer, nullable=False),
        Column('evaluator_version', String(100), nullable=False),
        Column('checkpoint_sha256', String(64), nullable=False),
        Column('dataset', String(255), nullable=False),
        Column('split', String(10), nullable=False),
        Column('manifest_sha256', String(64), nullable=False),
        Column('classes', JSON, nullable=False),
        Column('predictor_config', JSON, nullable=False),
        Column('preprocessing_config', JSON, nullable=False),
        Column('aggregation_config', JSON, nullable=False),
        Column('sample_count', Integer, nullable=False),
        Column('report', JSON(none_as_null=True), nullable=True),
        Column('status', String(10), nullable=False),
        Column('error_reason', String(2000), nullable=True),
        Column('created_at', DateTime(timezone=True), nullable=False),
        Column('started_at', DateTime(timezone=True), nullable=True),
        Column('finished_at', DateTime(timezone=True), nullable=True),
        Column('code_revision', String(255), nullable=True),
        CheckConstraint("status IN ('pending','running','completed','failed')", name='evaluation_status'),
        CheckConstraint("split IN ('val','test')", name='evaluation_split'),
        CheckConstraint('sample_count > 0 AND schema_version IN (1, 2)', name='evaluation_counts'),
        CheckConstraint("(status = 'completed' AND report IS NOT NULL AND error_reason IS NULL) OR "
                        "(status != 'completed' AND report IS NULL)", name='evaluation_report'),
        CheckConstraint("(status = 'failed' AND error_reason IS NOT NULL) OR "
                        "(status != 'failed' AND error_reason IS NULL)", name='evaluation_error'),
        CheckConstraint("(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR "
                        "(status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR "
                        "(status IN ('completed','failed') AND finished_at IS NOT NULL)", name='evaluation_times'),
    )


# Bounded PostgreSQL catalog spellings, not a SQL-equivalence parser. Unknown
# deparser output fails closed. These fixtures do not replace a real PG test.
_POSTGRES_CHECKS = {
    'evaluation_status': "((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying])::text[]))",
    'evaluation_split': "((split)::text = ANY ((ARRAY['val'::character varying, 'test'::character varying])::text[]))",
    'evaluation_counts': '((sample_count > 0) AND (schema_version = ANY (ARRAY[1, 2])))',
    'evaluation_report': "((((status)::text = 'completed'::text) AND (report IS NOT NULL) AND (error_reason IS NULL)) OR (((status)::text <> 'completed'::text) AND (report IS NULL)))",
    'evaluation_error': "((((status)::text = 'failed'::text) AND (error_reason IS NOT NULL)) OR (((status)::text <> 'failed'::text) AND (error_reason IS NULL)))",
    'evaluation_times': "((((status)::text = 'pending'::text) AND (started_at IS NULL) AND (finished_at IS NULL)) OR (((status)::text = 'running'::text) AND (started_at IS NOT NULL) AND (finished_at IS NULL)) OR (((status)::text = ANY ((ARRAY['completed'::character varying, 'failed'::character varying])::text[])) AND (finished_at IS NOT NULL)))",
}

# Exact pg_get_constraintdef bodies observed in PostgreSQL after SQLAlchemy
# removes the surrounding CHECK (...) wrapper. Keep this allowlist literal.
_POSTGRES_CATALOG_CHECKS = {
    'evaluation_status': "status::text = ANY (ARRAY['pending'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying]::text[])",
    'evaluation_split': "split::text = ANY (ARRAY['val'::character varying, 'test'::character varying]::text[])",
    'evaluation_counts': 'sample_count > 0 AND (schema_version = ANY (ARRAY[1, 2]))',
    'evaluation_report': "status::text = 'completed'::text AND report IS NOT NULL AND error_reason IS NULL OR status::text <> 'completed'::text AND report IS NULL",
    'evaluation_error': "status::text = 'failed'::text AND error_reason IS NOT NULL OR status::text <> 'failed'::text AND error_reason IS NULL",
    'evaluation_times': "status::text = 'pending'::text AND started_at IS NULL AND finished_at IS NULL OR status::text = 'running'::text AND started_at IS NOT NULL AND finished_at IS NULL OR (status::text = ANY (ARRAY['completed'::character varying, 'failed'::character varying]::text[])) AND finished_at IS NOT NULL",
}


def _check_spelling(sql):
    """Ignore whitespace outside quoted literals; retain grouping and all tokens."""
    return re.sub(r"'(?:''|[^'])*'|\s+",
                  lambda match: '' if match.group().isspace() else match.group(), sql)


def _checks_match(table, dialect, checks):
    expected = {str(c.name): {_check_spelling(str(c.sqltext.compile(dialect=dialect)))}
                for c in table.constraints if isinstance(c, CheckConstraint)}
    if dialect.name == 'postgresql':
        for catalog_spellings in (_POSTGRES_CHECKS, _POSTGRES_CATALOG_CHECKS):
            for name, sql in catalog_spellings.items():
                expected[name].add(_check_spelling(sql))
    # Reject missing, extra and duplicate names, as well as unknown spellings.
    return (len(checks) == len(expected) and {c['name'] for c in checks} == expected.keys()
            and all(_check_spelling(c['sqltext']) in expected[c['name']] for c in checks))


def migrate(engine):
    """Transactional additive creation; reject preexisting incompatible schemas."""
    if engine.dialect.name not in ('sqlite', 'postgresql'):
        raise ValueError('Only PostgreSQL and SQLite are supported')
    metadata = MetaData()
    # FK target declaration only; never created or changed by this migration.
    Table('modelo', metadata, Column('id_modelo', Integer, primary_key=True))
    table = evaluation_table(metadata)
    with engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table('modelo'):
            raise ValueError('Existing modelo table is required')
        if not inspector.has_table(table.name):
            table.create(connection)
            return True
        actual = inspector.get_columns(table.name)
        if {c['name'] for c in actual} != {c.name for c in table.columns}:
            raise ValueError('Incompatible model_evaluation columns')
        for column in actual:
            expected = table.c[column['name']]
            if (column['nullable'] != expected.nullable or
                    str(column['type'].compile(dialect=engine.dialect)) != str(expected.type.compile(dialect=engine.dialect)) or
                    column.get('default') is not None and not (
                        engine.dialect.name == 'postgresql' and expected.primary_key and
                        str(column['default']).startswith('nextval('))):
                raise ValueError('Incompatible model_evaluation column definition')
        if inspector.get_pk_constraint(table.name)['constrained_columns'] != ['id_evaluation']:
            raise ValueError('Incompatible evaluation primary key')
        fks = inspector.get_foreign_keys(table.name)
        if len(fks) != 1 or not (fks[0]['constrained_columns'] == ['id_modelo'] and
                                fks[0]['referred_table'] == 'modelo' and
                                fks[0]['referred_columns'] == ['id_modelo'] and
                                fks[0]['options'].get('ondelete') == 'RESTRICT'):
            raise ValueError('Incompatible evaluation foreign key')
        if inspector.get_unique_constraints(table.name) or any(
                index.get('unique') for index in inspector.get_indexes(table.name)):
            raise ValueError('Incompatible evaluation uniqueness constraints')
        if not _checks_match(table, engine.dialect, inspector.get_check_constraints(table.name)):
            raise ValueError('Incompatible evaluation check constraints')
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    url = os.environ.get('DATABASE_URL')
    if not url:
        parser.error('DATABASE_URL must be supplied explicitly; no dotenv/default')
    engine = create_engine(url)
    try:
        print('evaluation table added' if migrate(engine) else 'evaluation table already present')
    finally:
        engine.dispose()
