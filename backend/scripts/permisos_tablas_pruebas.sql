-- Ejecutar como fama_migrador en fama_pruebas después de 0003_autonomy.
DO $fama$
DECLARE
    tablas text[] := ARRAY[
        'acceso_prediccion', 'asignacion_dataset', 'audio', 'conjunto_datos',
        'control_cuentas', 'cuota_acceso', 'evento_seguridad', 'feedback_sync',
        'metrica_entrenamiento', 'modelo', 'prediccion', 'recuperacion_cuenta',
        'retroalimentacion', 'sesion_web', 'solicitud_dataset', 'usuario'
    ];
    revisiones text[];
    tabla text;
    secuencia record;
BEGIN
    IF current_database() <> 'fama_pruebas' OR current_user <> 'fama_migrador' THEN
        RAISE EXCEPTION 'Se requiere fama_migrador en la base fama_pruebas'
            USING ERRCODE = '22023';
    END IF;

    IF to_regclass('public.alembic_version') IS NULL THEN
        RAISE EXCEPTION 'Se requiere aplicar primero la revision 0003_autonomy'
            USING ERRCODE = '55000';
    END IF;
    SELECT array_agg(version_num::text) INTO revisiones FROM public.alembic_version;
    IF revisiones IS DISTINCT FROM ARRAY['0003_autonomy']::text[] THEN
        RAISE EXCEPTION 'Se requiere la revision 0003_autonomy'
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
            RAISE EXCEPTION 'Falta una tabla esperada o su propietario no es fama_migrador'
                USING ERRCODE = '55000';
        END IF;
    END LOOP;

    FOREACH tabla IN ARRAY tablas LOOP
        EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.%I FROM fama_app', tabla);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO fama_app', tabla);
    END LOOP;
    REVOKE ALL PRIVILEGES ON TABLE public.alembic_version FROM fama_app;
    GRANT SELECT ON TABLE public.alembic_version TO fama_app;

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
        EXECUTE format('REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM fama_app',
                       secuencia.esquema, secuencia.nombre);
        EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I.%I TO fama_app',
                       secuencia.esquema, secuencia.nombre);
    END LOOP;
END
$fama$;

SELECT 'runtime_permissions_ready' AS code;
