"""Transaction gate for cross-process account mutations on PostgreSQL/SQLite."""
from sqlalchemy import Column, Integer, CheckConstraint
from app.database import Base


class ControlCuentas(Base):
    __tablename__ = "control_cuentas"
    __table_args__ = (CheckConstraint("id = 1", name="chk_control_cuentas_unico"),)
    id = Column(Integer, primary_key=True)
