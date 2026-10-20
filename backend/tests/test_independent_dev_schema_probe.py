"""S1/S3: synthetic public checker, no migration entry point or real connection."""
import hashlib
import json
import pytest
from sqlalchemy import create_engine, text

ERROR = "Development imports are not ready. Preserve data; inspect the schema and authorize pending migrations separately. No migration or backfill was applied.\n"

def digest(engine):
    with engine.connect() as connection:
        dump = "\n".join(connection.connection.driver_connection.iterdump())
    return hashlib.sha256(dump.encode()).hexdigest()

def prepared():
    from app.database import Base
    from app import models
    from app.models.dataset_import_metadata import MetadataBackfill
    from app.models.dataset_import_job import ImportJobGate
    from app.models.dataset_import_receipt import ImportReceiptSchema
    from app.models.dataset_import_chunk import ImportChunkSchema
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(MetadataBackfill.__table__.insert().values(version=1,source_sha256="0"*64,report={}))
        connection.execute(ImportJobGate.__table__.insert().values(id=1,version=1,generation=0))
        connection.execute(ImportReceiptSchema.__table__.insert().values(id=1,version=1))
        connection.execute(ImportChunkSchema.__table__.insert().values(id=1,version=1))
        connection.execute(text("INSERT INTO imported_dataset (id,owner_id,name,description,revision,files) VALUES ('synthetic',-1,'preserve','',0,'[]')"))
        connection.execute(text("INSERT INTO imported_dataset_summary (dataset_id,revision,file_count,class_count,total_size_bytes) VALUES ('synthetic',0,0,0,0)"))
    return engine

@pytest.mark.parametrize("damage,expected", [
    ("ready",None),
    ("empty","Missing import tables"),
    ("table","Missing import tables"),
    ("marker","Missing verified import schema marker"),
    ("extra-marker","Missing verified import schema marker"),
    ("summary","Missing normalized summary; operator reconciliation required"),
])
def test_S1_verify_never_repairs_or_mutates(damage,expected):
    from scripts.check_dev_import_database import verify
    engine = create_engine("sqlite://") if damage == "empty" else prepared()
    try:
        with engine.begin() as connection:
            if damage == "table": connection.execute(text("DROP TABLE dataset_import_chunk"))
            if damage == "marker": connection.execute(text("DELETE FROM dataset_import_receipt_schema"))
            if damage == "extra-marker": connection.execute(text("INSERT INTO dataset_import_metadata_backfill VALUES (2,'extra','{}')"))
            if damage == "summary": connection.execute(text("DELETE FROM imported_dataset_summary"))
        before = digest(engine)
        if expected is None:
            assert verify(engine) == {"ready": True, "verification": "import_schema_and_markers"}
        else:
            with pytest.raises(ValueError) as error: verify(engine)
            assert str(error.value) == expected
        assert digest(engine) == before
    finally:
        engine.dispose()

@pytest.mark.parametrize("invalid", [None,"production","disabled","remote","query","missing-summary"])
def test_S1_main_synthetic_engine_and_sanitized_errors(monkeypatch,tmp_path,capsys,invalid):
    from scripts.check_dev_import_database import main
    root = tmp_path / "backend/data-dev/dataset-imports"
    root.mkdir(parents=True,mode=0o700)
    monkeypatch.setenv("FAMA_ENV", "production" if invalid == "production" else "development")
    monkeypatch.setenv("FAMA_IMPORT_DEV_MODE", "0" if invalid == "disabled" else "1")
    url = "postgresql://tester:private%40synthetic@db:5432/fama_db"
    if invalid == "remote": url = url.replace("@db:","@remote.invalid:")
    if invalid == "query": url += "?sslmode=require"
    monkeypatch.setenv("DATABASE_URL",url)
    monkeypatch.setenv("FAMA_IMPORT_ROOT",str(root))
    engine = prepared()
    if invalid == "missing-summary":
        with engine.begin() as connection: connection.execute(text("DELETE FROM imported_dataset_summary"))
    before = digest(engine)
    calls = []
    def factory(*args,**kwargs):
        calls.append((args,kwargs))
        return engine
    monkeypatch.setattr("sqlalchemy.create_engine", factory)
    monkeypatch.setattr(engine,"dispose",lambda:None)
    try:
        if invalid is None:
            assert main([]) == 0
            output = capsys.readouterr()
            assert output.out == json.dumps({"ready":True,"verification":"import_schema_and_markers"},sort_keys=True)+"\n"
            assert output.err == ""
            assert calls == [(("postgresql+psycopg2://tester:private%40synthetic@db:5432/fama_db",),{"connect_args":{"connect_timeout":5}})]
        else:
            with pytest.raises(SystemExit) as error: main([])
            assert error.value.code == 1
            output = capsys.readouterr()
            assert (output.out,output.err) == ("",ERROR)
            if invalid != "missing-summary": assert calls == []
        assert digest(engine) == before
    finally:
        engine.pool.dispose()
