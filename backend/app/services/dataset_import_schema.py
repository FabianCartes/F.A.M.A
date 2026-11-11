"""Read-only checks of the import tables against the ORM, without repairing anything."""
import re

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, select


def verify_table(conn, table):
    inspector = inspect(conn)
    columns = {column["name"]: column for column in inspector.get_columns(table.name)}
    if set(columns) != set(table.columns.keys()):
        raise ValueError("incompatible_job_schema")
    for column in table.columns:
        actual = columns[column.name]
        if actual["nullable"] != column.nullable:
            raise ValueError("incompatible_job_nullability")
        effective_type = column.type._variant_mapping.get(conn.dialect.name, column.type)
        if not isinstance(actual["type"], type(effective_type)):
            raise ValueError("incompatible_job_column_type")
    if inspector.get_pk_constraint(table.name)["constrained_columns"] != [column.name for column in table.primary_key]:
        raise ValueError("incompatible_job_primary_key")
    expected_foreign = {(tuple(column.name for column in constraint.columns),
                         tuple(element.column.table.name for element in constraint.elements),
                         tuple(element.column.name for element in constraint.elements))
                        for constraint in table.foreign_key_constraints}
    actual_foreign = {(tuple(item["constrained_columns"]),
                       (item["referred_table"],) * len(item["referred_columns"]),
                       tuple(item["referred_columns"]))
                      for item in inspector.get_foreign_keys(table.name)}
    if actual_foreign != expected_foreign:
        raise ValueError("incompatible_job_foreign_keys")
    def normalize(sql):
        # PostgreSQL renders varchar IN checks as text = ANY (ARRAY[...]).
        # Compare the equivalent reflected form without weakening the values.
        sql = re.sub(r"::(?:character varying|text)(?:\[\])?", "", sql.lower())
        sql = "".join(sql.split()).replace("(", "").replace(")", "")
        return sql.replace("=anyarray[", "in").replace("]", "")
    actual_checks = {normalize(check["sqltext"]) for check in inspector.get_check_constraints(table.name)}
    expected_checks = {normalize(str(check.sqltext)) for check in table.constraints
                       if isinstance(check, CheckConstraint)}
    if not expected_checks.issubset(actual_checks):
        raise ValueError("incompatible_job_constraints")
    actual_unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
    expected_unique = {tuple(column.name for column in item.columns) for item in table.constraints
                       if isinstance(item, UniqueConstraint)}
    if not expected_unique.issubset(actual_unique):
        raise ValueError("incompatible_job_uniqueness")
    indexes = {item["name"]: item for item in inspector.get_indexes(table.name)}
    for index in table.indexes:
        actual = indexes.get(index.name)
        if (actual is None or bool(actual["unique"]) != index.unique
                or actual["column_names"] != [column.name for column in index.columns]):
            raise ValueError("incompatible_job_indexes")
        predicate = index.dialect_options[conn.dialect.name].get("where")
        actual_predicate = actual.get("dialect_options", {}).get(conn.dialect.name + "_where")
        if predicate is not None and (actual_predicate is None
                or normalize(str(actual_predicate)) != normalize(str(predicate))):
            raise ValueError("incompatible_job_index_predicate")


def verify_import_schema(connection):
    """Raise ``ValueError`` unless every import table matches the ORM and carries its version marker."""
    from app.models.dataset_import import DatasetImport, ImportedDataset
    from app.models.dataset_import_metadata import BACKFILL_MODELS, MetadataBackfill
    from app.models.dataset_import_job import JOB_MODELS, ImportJobGate
    from app.models.dataset_import_receipt import RECEIPT_MODELS, ImportReceiptSchema
    from app.models.dataset_import_chunk import CHUNK_MODELS, ImportChunkSchema

    models = (DatasetImport, ImportedDataset, *BACKFILL_MODELS, *JOB_MODELS, *RECEIPT_MODELS, *CHUNK_MODELS)
    if not {model.__tablename__ for model in models} <= set(inspect(connection).get_table_names()):
        raise ValueError("Missing import tables")
    for model in models:
        verify_table(connection, model.__table__)
    # The Alembic revisions seed only the three markers the runtime reads; the
    # metadata backfill marker is optional, but never any other version.
    if connection.execute(select(MetadataBackfill.version)).scalars().all() not in ([], [1]):
        raise ValueError("Missing verified import schema marker")
    for model in (ImportJobGate, ImportReceiptSchema, ImportChunkSchema):
        if connection.execute(select(model.version)).scalars().all() != [1]:
            raise ValueError("Missing verified import schema marker")

