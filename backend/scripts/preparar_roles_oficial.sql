-- Ejecutar como postgres, exclusivamente en la base vacía fama_oficial.
-- No asigna contraseñas, migra tablas ni modifica fama_pruebas.
DO $fama$
BEGIN
    IF current_database() <> 'fama_oficial' THEN
        RAISE EXCEPTION 'Destino incorrecto: se exige la base fama_oficial'
            USING ERRCODE = '22023';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles
               WHERE rolname IN ('fama_oficial_app', 'fama_oficial_migrador')) THEN
        RAISE EXCEPTION 'Las identidades oficiales ya existen; revisar antes de continuar'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class AS objeto
               JOIN pg_namespace AS esquema ON esquema.oid = objeto.relnamespace
               WHERE esquema.nspname = 'public')
       OR EXISTS (SELECT 1 FROM pg_proc AS objeto
                  JOIN pg_namespace AS esquema ON esquema.oid = objeto.pronamespace
                  WHERE esquema.nspname = 'public')
       OR EXISTS (SELECT 1 FROM pg_type AS objeto
                  JOIN pg_namespace AS esquema ON esquema.oid = objeto.typnamespace
                  WHERE esquema.nspname = 'public')
       OR EXISTS (SELECT 1 FROM pg_namespace
                  WHERE nspname NOT IN ('public', 'information_schema')
                    AND left(nspname, 3) <> 'pg_') THEN
        RAISE EXCEPTION 'La base contiene objetos; se requiere una base oficial vacía'
            USING ERRCODE = '55000';
    END IF;

    CREATE ROLE fama_oficial_migrador LOGIN NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD NULL;
    CREATE ROLE fama_oficial_app LOGIN NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD NULL;
    REVOKE ALL ON DATABASE fama_oficial FROM PUBLIC;
    REVOKE ALL ON SCHEMA public FROM PUBLIC;
    GRANT CONNECT ON DATABASE fama_oficial TO fama_oficial_migrador, fama_oficial_app;
    GRANT USAGE, CREATE ON SCHEMA public TO fama_oficial_migrador;
    GRANT USAGE ON SCHEMA public TO fama_oficial_app;
END
$fama$;

SELECT rolname AS usuario,
       rolcanlogin AS admite_login,
       rolsuper AS superusuario,
       rolcreatedb AS crea_bases,
       rolcreaterole AS crea_roles,
       has_database_privilege(rolname, 'fama_oficial', 'CONNECT') AS conecta_base,
       has_schema_privilege(rolname, 'public', 'USAGE') AS usa_esquema,
       has_schema_privilege(rolname, 'public', 'CREATE') AS crea_tablas
FROM pg_roles
WHERE rolname IN ('fama_oficial_app', 'fama_oficial_migrador')
ORDER BY rolname;
