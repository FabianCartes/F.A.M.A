"""One current request per researcher/dataset; decision history lives in audit."""
from sqlalchemy import Column, Integer, BigInteger, String, ForeignKey, CheckConstraint
from app.database import Base


class SolicitudDataset(Base):
    __tablename__ = "solicitud_dataset"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="chk_solicitud_estado"),
        CheckConstraint("(status = 'pending' AND decided_at IS NULL AND decided_by IS NULL) OR "
                        "(status IN ('approved', 'rejected') AND decided_at IS NOT NULL AND decided_by IS NOT NULL)",
                        name="chk_solicitud_decision"),
    )
    id_usuario = Column(Integer, ForeignKey("usuario.id_usuario", ondelete="CASCADE"), primary_key=True)
    id_conjunto_datos = Column(Integer, ForeignKey("conjunto_datos.id_conjunto_datos", ondelete="CASCADE"),
                              primary_key=True, index=True)
    status = Column(String(12), nullable=False)
    requested_at = Column(BigInteger, nullable=False)
    decided_at = Column(BigInteger, nullable=True)
    decided_by = Column(Integer, nullable=True)
