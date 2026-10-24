"""Add ONLY model_evaluation. Explicit DATABASE_URL and --apply; no ORM/runtime/dotenv imports.

Operator must back up and drain writers first. Never run automatically at startup.
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import (Table, Column, Integer, String, JSON, DateTime, ForeignKey,
                        CheckConstraint, MetaData, create_engine, inspect)


from app.evaluation_table import evaluation_table


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
