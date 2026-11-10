-- Ejecutar como fama_oficial_migrador en fama_oficial después de 0004_integration.
DO $fama$
DECLARE
    tablas text[] := ARRAY[
        'acceso_prediccion',
        'asignacion_dataset',
        'audio',
        'conjunto_datos',
        'control_cuentas',
        'cuota_acceso',
        'dataset_export',
        'dataset_export_session',
        'dataset_import',
        'dataset_import_chunk',
        'dataset_import_chunk_activity',
        'dataset_import_chunk_schema',
        'dataset_import_class',
        'dataset_import_file',
        'dataset_import_issue',
        'dataset_import_job',
        'dataset_import_job_gate',
        'dataset_import_metadata_backfill',
        'dataset_import_receipt',
        'dataset_import_receipt_schema',
        'dataset_import_summary',
        'evento_seguridad',
        'feedback_sync',
        'imported_dataset',
        'imported_dataset_member',
        'imported_dataset_revision',
        'imported_dataset_revision_object',
        'imported_dataset_summary',
        'metrica_entrenamiento',
        'model_evaluation',
        'modelo',
        'prediccion',
        'recuperacion_cuenta',
        'retroalimentacion',
        'sesion_web',
        'solicitud_dataset',
        'usuario'
    ];
    revisiones text[];
    tabla text;
    secuencia record;
BEGIN
    IF current_database() <> 'fama_oficial' OR current_user <> 'fama_oficial_migrador' THEN
        RAISE EXCEPTION 'Se requiere fama_oficial_migrador en la base fama_oficial'
            USING ERRCODE = '22023';
    END IF;

    IF to_regclass('public.alembic_version') IS NULL THEN
        RAISE EXCEPTION 'Se requiere aplicar primero la revision 0004_integration'
            USING ERRCODE = '55000';
    END IF;
    SELECT array_agg(version_num::text) INTO revisiones FROM public.alembic_version;
    IF revisiones IS DISTINCT FROM ARRAY['0004_integration']::text[] THEN
        RAISE EXCEPTION 'Se requiere la revision 0004_integration'
            USING ERRCODE = '55000';
    END IF;

    FOREACH tabla IN ARRAY (tablas || ARRAY['alembic_version']) LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_class AS objeto
            JOIN pg_namespace AS esquema ON esquema.oid = objeto.relnamespace
            WHERE esquema.nspname = 'public' AND objeto.relname = tabla
                AND objeto.relkind IN ('r', 'p')
                AND pg_get_userbyid(objeto.relowner) = current_user
        ) THEN
            RAISE EXCEPTION 'Falta una tabla esperada o su propietario no es fama_oficial_migrador'
                USING ERRCODE = '55000';
        END IF;
    END LOOP;

    FOREACH tabla IN ARRAY tablas LOOP
        EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.%I FROM fama_oficial_app', tabla);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO fama_oficial_app', tabla);
    END LOOP;
    REVOKE ALL PRIVILEGES ON TABLE public.alembic_version FROM fama_oficial_app;
    GRANT SELECT ON TABLE public.alembic_version TO fama_oficial_app;

    FOR secuencia IN
        SELECT ns.nspname AS esquema, sec.relname AS nombre
        FROM pg_class AS sec
        JOIN pg_namespace AS ns ON ns.oid = sec.relnamespace
        JOIN pg_depend AS dep ON dep.classid = 'pg_class'::regclass
            AND dep.objid = sec.oid AND dep.refclassid = 'pg_class'::regclass
            AND dep.deptype IN ('a', 'i')
        JOIN pg_class AS origen ON origen.oid = dep.refobjid
        JOIN pg_namespace AS nt ON nt.oid = origen.relnamespace
        WHERE sec.relkind = 'S' AND nt.nspname = 'public'
            AND origen.relname = ANY(tablas)
    LOOP
        EXECUTE format('REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM fama_oficial_app',
                       secuencia.esquema, secuencia.nombre);
        EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I.%I TO fama_oficial_app',
                       secuencia.esquema, secuencia.nombre);
    END LOOP;
END
$fama$;

SELECT 'runtime_permissions_ready' AS code;
