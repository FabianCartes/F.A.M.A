-- Explicit operator repair; run against the verified training-development target.
-- No schema/data mutation and no database-wide or table-wide UPDATE grant.
-- The caller must select and verify the database identity and stop API writers.
\set ON_ERROR_STOP on
BEGIN;
DO $$
BEGIN
    IF current_database() !~ '^fama_training_dev_[0-9]{14}$' THEN
        RAISE EXCEPTION 'Refusing an unselected training-development database';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'fama_training_app'
          AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
          AND NOT rolreplication AND NOT rolbypassrls
    ) THEN
        RAISE EXCEPTION 'Expected non-administrative application role is absent';
    END IF;
    IF to_regclass('public.training_snapshot') IS NULL THEN
        RAISE EXCEPTION 'Run the explicit snapshot schema migration first';
    END IF;
    IF EXISTS (
        SELECT 1 FROM unnest(ARRAY['id', 'owner_id', 'dataset_id',
            'dataset_revision', 'name', 'description']) AS protected(column_name)
        WHERE has_column_privilege('fama_training_app',
            'public.training_snapshot', protected.column_name, 'UPDATE')
    ) THEN
        RAISE EXCEPTION 'Unexpected pre-existing application identity-update privilege';
    END IF;
END $$;

GRANT UPDATE (state, file_count, total_size_bytes, classes, manifest_sha256)
    ON TABLE public.training_snapshot TO fama_training_app;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM unnest(ARRAY['state', 'file_count', 'total_size_bytes',
            'classes', 'manifest_sha256']) AS required(column_name)
        WHERE NOT has_column_privilege('fama_training_app',
            'public.training_snapshot', required.column_name, 'UPDATE')
    ) THEN
        RAISE EXCEPTION 'Snapshot finalization privilege verification failed';
    END IF;
END $$;
COMMIT;
