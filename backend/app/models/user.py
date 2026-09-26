from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, CheckConstraint
from sqlalchemy.orm import synonym, validates

from app.database import Base


class Usuario(Base):
    """
    Modelo relacional para la tabla 'usuario' en PostgreSQL.
    Corresponde a la Tabla 6.2 de la Tesis (CU_SES_01 / CU_ADM_01).
    Define los roles de acceso: 'administrador' e 'investigador'.
    """
    __tablename__ = "usuario"
    __table_args__ = (
        CheckConstraint("rol IN ('administrador', 'investigador')", name="chk_usuario_rol"),
    )

    id = Column("id_usuario", Integer, primary_key=True, autoincrement=True, index=True)
    email = Column("correo_electronico", String(150), unique=True, nullable=False, index=True)
    password_hash = Column("hash_contrasena", String(255), nullable=False)
    rol = Column(String(50), nullable=False, default="investigador")
    nombre_completo = Column(String(150), nullable=False, default="")
    activo = Column(Boolean, nullable=False, default=True)
    creado_en = Column(
        "fecha_creacion",
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    ultimo_acceso = Column(DateTime(timezone=True), nullable=True)

    # Sinónimos para plena compatibilidad con la nomenclatura relacional de la tesis
    id_usuario = synonym("id")
    correo_electronico = synonym("email")
    hash_contrasena = synonym("password_hash")
    fecha_creacion = synonym("creado_en")

    @validates("rol")
    def validate_rol(self, key, value):
        allowed_roles = ("administrador", "investigador")
        if value not in allowed_roles:
            raise ValueError(
                f"Rol inválido: '{value}'. Roles permitidos: {list(allowed_roles)}"
            )
        return value

    def to_dict(self) -> dict:
        """Serializa el usuario a diccionario excluyendo el hash de contraseña."""
        return {
            "id": self.id,
            "email": self.email,
            "nombre_completo": self.nombre_completo,
            "rol": self.rol,
            "activo": self.activo,
            "creado_en": self.creado_en.isoformat() if self.creado_en else None,
            "ultimo_acceso": self.ultimo_acceso.isoformat() if self.ultimo_acceso else None,
        }

    def __repr__(self) -> str:
        return (
            f"<Usuario(id={self.id}, email='{self.email}', "
            f"rol='{self.rol}', activo={self.activo})>"
        )
