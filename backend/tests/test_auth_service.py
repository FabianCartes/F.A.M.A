import sys
from pathlib import Path
from datetime import timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import Base


@pytest.fixture
def db_session():
    """Crea una base de datos SQLite en memoria aislada para las pruebas unitarias."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    from app.models.user import Usuario

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_password_hashing_and_verification():
    """Valida que el hash de contraseñas sea seguro, use sal y verifique correctamente."""
    from app.services.auth import hash_password, verify_password

    plain_pass = "BioAcustica2026!"
    hashed = hash_password(plain_pass)

    assert hashed != plain_pass
    assert verify_password(plain_pass, hashed) is True
    assert verify_password("PasswordIncorrecta", hashed) is False

    # Valida que dos llamadas con la misma clave generen hashes distintos por la sal
    another_hash = hash_password(plain_pass)
    assert hashed != another_hash
    assert verify_password(plain_pass, another_hash) is True


def test_token_generation_and_decoding():
    """Valida la generación de tokens JWT seguros y su posterior decodificación."""
    from app.services.auth import create_access_token, decode_access_token

    payload_data = {
        "sub": "42",
        "email": "investigador@fama.cl",
        "rol": "investigador",
    }
    token = create_access_token(data=payload_data, expires_delta=timedelta(minutes=15))
    assert isinstance(token, str)
    assert len(token) > 20

    decoded = decode_access_token(token)
    assert decoded["sub"] == "42"
    assert decoded["email"] == "investigador@fama.cl"
    assert decoded["rol"] == "investigador"
    assert "exp" in decoded


def test_token_expiration_and_tampering():
    """Valida que tokens expirados o con firma manipulada sean rechazados."""
    from app.services.auth import create_access_token, decode_access_token

    payload_data = {"sub": "1", "email": "admin@fama.cl", "rol": "administrador"}

    # Token ya expirado
    expired_token = create_access_token(data=payload_data, expires_delta=timedelta(seconds=-10))
    with pytest.raises(ValueError, match="expirado|expired"):
        decode_access_token(expired_token)

    # Token con firma alterada
    valid_token = create_access_token(data=payload_data, expires_delta=timedelta(minutes=10))
    parts = valid_token.split(".")
    tampered_token = f"{parts[0]}.{parts[1]}.badsignature"
    with pytest.raises(ValueError, match="(?i)firma|signature|inv[aá]lid"):
        decode_access_token(tampered_token)


def test_usuario_model_attributes_and_defaults(db_session):
    """Verifica que el modelo Usuario cumpla con la especificación de atributos y restricciones."""
    from app.models.user import Usuario

    user = Usuario(
        email="test_investigador@fama.cl",
        password_hash="dummy_hash_123",
        nombre_completo="Dra. Jane Doe",
        rol="investigador",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.id is not None
    assert user.email == "test_investigador@fama.cl"
    assert user.nombre_completo == "Dra. Jane Doe"
    assert user.rol == "investigador"
    assert user.activo is True
    assert user.creado_en is not None


def test_usuario_role_validation(db_session):
    """Verifica que el rol deba ser estrictamente 'administrador' o 'investigador'."""
    from app.models.user import Usuario

    with pytest.raises(ValueError, match="(?i)rol inv[aá]lido"):
        Usuario(
            email="hacker@fama.cl",
            password_hash="dummy_hash",
            nombre_completo="Unknown",
            rol="superadmin",
        )


def test_seed_initial_admin_when_empty(db_session):
    """Verifica el seeding automático del administrador cuando la tabla de usuarios está vacía."""
    from app.models.user import Usuario
    from app.services.auth import seed_initial_admin, verify_password

    # Confirmar que la tabla está vacía
    assert db_session.query(Usuario).count() == 0

    admin = seed_initial_admin(db_session)
    assert admin is not None
    assert admin.rol == "administrador"
    assert admin.activo is True
    assert admin.email in ["admin@fama.cl", "admin@ubiobio.cl"]
    assert verify_password("AdminFama2026!", admin.password_hash)

    # Segundo llamado no debe duplicar al administrador
    count_after_first = db_session.query(Usuario).count()
    assert count_after_first == 1

    second_call = seed_initial_admin(db_session)
    assert db_session.query(Usuario).count() == 1
    assert second_call.id == admin.id


def test_authenticate_user(db_session):
    """Valida la función de autenticación de usuario con credenciales correctas e incorrectas."""
    from app.services.auth import create_user, authenticate_user

    user = create_user(
        db=db_session,
        email="profesor@fama.cl",
        password="SecurePassword2026!",
        nombre_completo="Profesor Guía",
        rol="investigador",
    )
    assert user.id is not None

    # Credenciales correctas
    auth_ok = authenticate_user(db=db_session, email="profesor@fama.cl", password="SecurePassword2026!")
    assert auth_ok is not None
    assert auth_ok.id == user.id

    # Contraseña incorrecta
    auth_bad_pass = authenticate_user(db=db_session, email="profesor@fama.cl", password="WrongPassword!")
    assert auth_bad_pass is None

    # Correo inexistente
    auth_bad_email = authenticate_user(db=db_session, email="inexistente@fama.cl", password="SecurePassword2026!")
    assert auth_bad_email is None

    # Usuario inactivo
    user.activo = False
    db_session.commit()
    auth_inactive = authenticate_user(db=db_session, email="profesor@fama.cl", password="SecurePassword2026!")
    assert auth_inactive is None
