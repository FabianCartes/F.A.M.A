import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import Base, get_db
from app.main import app
from app.models.user import Usuario
from app.services.auth import hash_password, create_access_token


@pytest.fixture
def test_db():
    """Crea una base de datos en memoria compartida y reemplaza la dependencia get_db."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(test_db):
    with TestClient(app) as test_client:
        yield test_client


def test_login_success(client, test_db):
    """POST /api/auth/login retorna 200 con token JWT y datos de usuario."""
    user = Usuario(
        email="ornitologo@fama.cl",
        password_hash=hash_password("Pass1234!"),
        nombre_completo="Carlos Ornitólogo",
        rol="investigador",
        activo=True,
    )
    test_db.add(user)
    test_db.commit()

    res = client.post(
        "/api/auth/login",
        json={"email": "ornitologo@fama.cl", "password": "Pass1234!"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "user" in data
    assert data["user"]["email"] == "ornitologo@fama.cl"
    assert data["user"]["rol"] == "investigador"
    assert data["user"]["nombre_completo"] == "Carlos Ornitólogo"


def test_login_invalid_credentials(client, test_db):
    """POST /api/auth/login retorna 401 si las credenciales son incorrectas."""
    user = Usuario(
        email="admin@fama.cl",
        password_hash=hash_password("AdminSecret!"),
        nombre_completo="Admin FAMA",
        rol="administrador",
        activo=True,
    )
    test_db.add(user)
    test_db.commit()

    # Password equivocada
    res = client.post(
        "/api/auth/login",
        json={"email": "admin@fama.cl", "password": "WrongPassword"},
    )
    assert res.status_code == 401
    assert "detail" in res.json()

    # Email inexistente
    res2 = client.post(
        "/api/auth/login",
        json={"email": "noexiste@fama.cl", "password": "AdminSecret!"},
    )
    assert res2.status_code == 401


def test_login_inactive_user(client, test_db):
    """POST /api/auth/login retorna 401 si el usuario está desactivado."""
    user = Usuario(
        email="inactivo@fama.cl",
        password_hash=hash_password("Inactive123!"),
        nombre_completo="Usuario Inactivo",
        rol="investigador",
        activo=False,
    )
    test_db.add(user)
    test_db.commit()

    res = client.post(
        "/api/auth/login",
        json={"email": "inactivo@fama.cl", "password": "Inactive123!"},
    )
    assert res.status_code in [401, 403]


def test_get_current_user_me(client, test_db):
    """GET /api/auth/me retorna los datos del usuario autenticado vía Bearer token."""
    user = Usuario(
        email="dra_lucia@fama.cl",
        password_hash=hash_password("LuciaSecret!"),
        nombre_completo="Dra. Lucía Bio",
        rol="investigador",
        activo=True,
    )
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)

    token = create_access_token(data={"sub": str(user.id), "email": user.email, "rol": user.rol})

    # Petición autenticada
    headers = {"Authorization": f"Bearer {token}"}
    res = client.get("/api/auth/me", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "dra_lucia@fama.cl"
    assert data["nombre_completo"] == "Dra. Lucía Bio"
    assert data["rol"] == "investigador"
    assert data["activo"] is True

    # Petición sin token
    res_no_auth = client.get("/api/auth/me")
    assert res_no_auth.status_code == 401

    # Petición con token inválido
    res_bad_token = client.get("/api/auth/me", headers={"Authorization": "Bearer token.invalido.123"})
    assert res_bad_token.status_code == 401


def test_register_endpoint(client, test_db):
    """POST /api/auth/register crea un nuevo usuario y retorna 201."""
    payload = {
        "email": "nuevo_investigador@fama.cl",
        "password": "PasswordFuerte2026!",
        "nombre_completo": "Investigador Nuevo",
        "rol": "investigador",
    }
    res = client.post("/api/auth/register", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["email"] == "nuevo_investigador@fama.cl"
    assert data["nombre_completo"] == "Investigador Nuevo"
    assert data["rol"] == "investigador"
    assert data["activo"] is True
    assert "password_hash" not in data  # Nunca exponer hash en respuesta

    # Intento de duplicar correo
    res_dup = client.post("/api/auth/register", json=payload)
    assert res_dup.status_code == 400
    assert "registrado" in res_dup.json()["detail"].lower() or "existe" in res_dup.json()["detail"].lower()


def test_register_invalid_role(client, test_db):
    """POST /api/auth/register rechaza roles no permitidos según la Tesis."""
    payload = {
        "email": "invalido@fama.cl",
        "password": "PasswordFuerte2026!",
        "nombre_completo": "Invalido",
        "rol": "superusuario",
    }
    res = client.post("/api/auth/register", json=payload)
    assert res.status_code in [400, 422]
