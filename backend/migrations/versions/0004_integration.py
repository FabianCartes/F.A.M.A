"""Join evaluations and durable ZIP metadata with the controlled access schema."""
from alembic import op
from migrations.schema_0003 import metadata as previous
from migrations.schema_0004 import metadata
revision = "0004_integration"
down_revision = "0003_autonomy"

def upgrade():
    bind = op.get_bind()
    for table in metadata.sorted_tables:
        if table.name not in previous.tables:
            table.create(bind, checkfirst=False)
    bind.execute(metadata.tables["dataset_import_job_gate"].insert(), {"id": 1, "version": 1, "generation": 0})
    for name in ("dataset_import_receipt_schema", "dataset_import_chunk_schema"):
        bind.execute(metadata.tables[name].insert(), {"id": 1, "version": 1})

def downgrade():
    raise RuntimeError("La reversión destructiva requiere recuperación explícita del operador")
