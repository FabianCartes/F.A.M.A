"""Frozen schema 0006: 0005 plus the optional shared dataset description."""
import sqlalchemy as sa
from migrations.schema_0005 import BOOTSTRAP_TABLES, metadata as previous

metadata = sa.MetaData()
for table in previous.sorted_tables:
    table.to_metadata(metadata)

metadata.tables['conjunto_datos'].append_column(sa.Column('descripcion', sa.String(length=2000), nullable=True))

__all__ = ["BOOTSTRAP_TABLES", "metadata"]
