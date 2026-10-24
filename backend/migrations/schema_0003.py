"""Frozen revision 0003; never imports runtime models."""
import sqlalchemy as sa
from migrations.schema_0002 import metadata as previous

metadata = sa.MetaData()
for table in previous.sorted_tables:
    table.to_metadata(metadata)
metadata.tables['feedback_sync'].append_column(sa.Column('incorporated_by', sa.Integer(), nullable=True))
metadata.tables['feedback_sync'].append_column(sa.Column('incorporated_at', sa.DateTime(timezone=True), nullable=True))
sa.Table('solicitud_dataset', metadata,
    sa.Column('id_usuario', sa.Integer(), sa.ForeignKey('usuario.id_usuario', ondelete='CASCADE'), primary_key=True),
    sa.Column('id_conjunto_datos', sa.Integer(), sa.ForeignKey('conjunto_datos.id_conjunto_datos', ondelete='CASCADE'), primary_key=True),
    sa.Column('status', sa.String(12), nullable=False),
    sa.Column('requested_at', sa.BigInteger(), nullable=False),
    sa.Column('decided_at', sa.BigInteger(), nullable=True),
    sa.Column('decided_by', sa.Integer(), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name='chk_solicitud_estado'),
    sa.CheckConstraint("(status = 'pending' AND decided_at IS NULL AND decided_by IS NULL) OR "
                       "(status IN ('approved', 'rejected') AND decided_at IS NOT NULL AND decided_by IS NOT NULL)",
                       name='chk_solicitud_decision'))
sa.Index('ix_solicitud_dataset_id_conjunto_datos', metadata.tables['solicitud_dataset'].c.id_conjunto_datos)
