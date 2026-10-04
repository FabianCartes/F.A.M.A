"""Migration of an existing SQLite table, without application/schema startup."""
from sqlalchemy import create_engine, inspect, text
from scripts.migrate_prediction_dataset import migrate


def test_existing_schema_adds_nullable_snapshot_without_guessing_and_is_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE prediccion (id_prediccion INTEGER PRIMARY KEY, modelo_id VARCHAR(100))"))
        connection.execute(text("INSERT INTO prediccion VALUES (1, 'chilean-birds-cnn')"))
    assert migrate(engine) is True
    columns = {column["name"]: column for column in inspect(engine).get_columns("prediccion")}
    assert columns["dataset_name"]["nullable"] is True
    with engine.connect() as connection:
        assert connection.execute(text("SELECT dataset_name FROM prediccion WHERE id_prediccion=1")).scalar() is None
    assert migrate(engine) is False
    engine.dispose()
