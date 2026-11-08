"""Explicit additive archive migration; stop all writers and back up DB first.

Rollback application code only: leave this additive column and retained data intact.
"""
import argparse
from sqlalchemy import Boolean, inspect, text


def validate_archive(connection):
    columns = {c['name']: c for c in inspect(connection).get_columns('imported_dataset')}
    column = columns.get('archived')
    if (column is None or column['nullable']
            or column['type']._type_affinity is not Boolean
            or str(column['default']).lower().strip('()') not in ('false', '0')):
        raise RuntimeError('Incompatible dataset archive schema')


def migrate_archive(engine, *, writers_stopped=False):
    if writers_stopped is not True:
        raise RuntimeError('All writers must be stopped explicitly')
    if engine.dialect.name not in ('sqlite', 'postgresql'):
        raise RuntimeError('Unsupported schema dialect')
    with engine.begin() as connection:
        columns = inspect(connection).get_columns('imported_dataset')
        if not any(c['name'] == 'archived' for c in columns):
            connection.execute(text('ALTER TABLE imported_dataset ADD COLUMN archived BOOLEAN NOT NULL DEFAULT FALSE'))
        validate_archive(connection)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--writers-stopped', action='store_true', required=True)
    args = parser.parse_args()
    from app.database import engine
    migrate_archive(engine, writers_stopped=args.writers_stopped)


if __name__ == '__main__':
    main()
