-- Ejecutar como postgres en la base vacía fama_pruebas de la instancia de pruebas.
-- Las contraseñas se asignan después desde Usuarios en Cloud SQL.
-- Las tablas y sus permisos DML se preparan en la etapa de migraciones.
DO $fama$
BEGIN
    IF current_database() <> 'fama_pruebas' THEN
        RAISE EXCEPTION 'Destino incorrecto: este script exige la base fama_pruebas'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS objeto
        JOIN pg_namespace AS esquema ON esquema.oid = objeto.relnamespace
        WHERE esquema.nspname = 'public'
          AND objeto.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
    ) THEN
        RAISE EXCEPTION 'La base ya contiene objetos en public; requiere revisión del operador'
            USING ERRCODE = '55000';
    END IF;

    CREATE ROLE fama_migrador LOGIN NOCREATEDB NOCREATEROLE PASSWORD NULL;
    CREATE ROLE fama_app LOGIN NOCREATEDB NOCREATEROLE PASSWORD NULL;

    GRANT CONNECT ON DATABASE fama_pruebas TO fama_migrador, fama_app;
    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    GRANT USAGE, CREATE ON SCHEMA public TO fama_migrador;
    GRANT USAGE ON SCHEMA public TO fama_app;
END
$fama$;

SELECT rolname AS usuario,
       rolcanlogin AS admite_login,
       rolsuper AS superusuario,
       rolcreatedb AS crea_bases,
       rolcreaterole AS crea_roles,
       has_schema_privilege(rolname, 'public', 'USAGE') AS usa_esquema,
       has_schema_privilege(rolname, 'public', 'CREATE') AS crea_tablas
FROM pg_roles
WHERE rolname IN ('fama_app', 'fama_migrador')
ORDER BY rolname;
