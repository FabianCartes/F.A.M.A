# Base de integración local `fama_pruebas` (PostgreSQL 16.15 en Docker)

Prepara desde cero una base vacía con el esquema vigente (`0007_triad_evaluation`), los roles y permisos del flujo de Cloud SQL y, después, el primer administrador. Sigue la etapa g de la integración mvp ([plan](../arquitectura/integracion-mvp-g-base-integracion-plan.md)). No toca `fama_oficial`, `fama_db` de `docker-compose.yml` ni otros contenedores.

## Requisitos

- Docker y el cliente `psql` (una versión mayor más nueva sirve para conectarse).
- `.venv` del repositorio con `backend/requirements.txt`.
- Puerto `127.0.0.1:5433` libre. El asistente de instalación arma la URL de la base con `127.0.0.1:5433` (el puerto local del proxy de Cloud SQL) y no permite otro puerto.
- Un directorio privado fuera del repositorio para las contraseñas. Los ejemplos usan `~/.fama-integracion-g/secrets/` con permisos `0700`; cada archivo contiene una contraseña aleatoria sin salto de línea.

## Pasos

1. **Servidor.** Superusuario solo para este contenedor:

   ```bash
   D=~/.fama-integracion-g
   docker volume create fama-g-pruebas-data
   docker run -d --name fama-g-pruebas-pg --restart unless-stopped \
     -v fama-g-pruebas-data:/var/lib/postgresql/data \
     -e POSTGRES_PASSWORD_FILE=/run/secrets/su -v $D/secrets/superuser:/run/secrets/su:ro \
     -p 127.0.0.1:5433:5432 postgres:16.15
   ```

2. **Base y dueño.** Único paso con superusuario. El dueño equivale al usuario `postgres` de Cloud SQL: `CREATEROLE`, sin superusuario ni `CREATEDB`.

   ```bash
   export PGHOST=127.0.0.1 PGPORT=5433
   PGPASSWORD=$(cat $D/secrets/superuser) psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
     -v pw="$(cat $D/secrets/operador)" <<'SQL'
   CREATE ROLE fama_operador_pruebas LOGIN CREATEROLE NOSUPERUSER NOCREATEDB PASSWORD :'pw';
   CREATE DATABASE fama_pruebas OWNER fama_operador_pruebas;
   SQL
   ```

3. **Roles.** Desde `backend/`, como el dueño. El script exige la base `fama_pruebas` con `public` vacío y crea `fama_migrador` y `fama_app` sin contraseña.

   ```bash
   PGPASSWORD=$(cat $D/secrets/operador) psql -U fama_operador_pruebas -d fama_pruebas \
     -v ON_ERROR_STOP=1 -f scripts/preparar_roles_pruebas.sql
   PGPASSWORD=$(cat $D/secrets/operador) psql -U fama_operador_pruebas -d fama_pruebas -v ON_ERROR_STOP=1 \
     -v m="$(cat $D/secrets/migrador)" -v a="$(cat $D/secrets/app)" <<'SQL'
   ALTER ROLE fama_migrador PASSWORD :'m';
   ALTER ROLE fama_app PASSWORD :'a';
   SQL
   ```

4. **Migración.** `app.schema` lee solo `DATABASE_URL` (no `.env`). Esperado: `schema_empty`, luego `schema_current` con `0007_triad_evaluation`.

   ```bash
   export DATABASE_URL="postgresql://fama_migrador:$(cat $D/secrets/migrador)@127.0.0.1:5433/fama_pruebas"
   ../.venv/bin/python -m app.schema status
   ../.venv/bin/python -m app.schema upgrade --apply
   ../.venv/bin/python -m app.schema status
   unset DATABASE_URL
   ```

5. **Permisos diarios.** Como `fama_migrador`. Esperado: `runtime_permissions_ready`.

   ```bash
   PGPASSWORD=$(cat $D/secrets/migrador) psql -U fama_migrador -d fama_pruebas \
     -v ON_ERROR_STOP=1 -f scripts/permisos_tablas_pruebas.sql
   ```

   Comprobación: 40 tablas en `public` (39 de aplicación más `alembic_version`) y 16 secuencias.

6. **Asistente y primer administrador.** Seguir el [asistente de primera instalación](asistente_primera_instalacion.md) con un directorio de configuración propio, el usuario `fama_app`, la base `fama_pruebas` y el bucket de pruebas `fama-pruebas` (nunca el bucket definitivo). La comprobación del asistente lista un objeto del bucket, así que necesita una credencial de Google con acceso a ese bucket. `app.node prepare` exige que el archivo se llame `application_default_credentials.json`; en la etapa g se usó una clave JSON de la cuenta de servicio `fama-pruebas-app`, guardada fuera del repositorio con permisos `0600` ([recibo](../receipts/integracion-mvp-g-local.json)). El asistente exige un correo con dominio y una contraseña de 12 caracteres o más; tras `/complete` hay que reiniciar el backend.

## Recrear desde cero

Retira el contenedor y su volumen (pierde todos los datos de esta base) y repite los pasos:

```bash
docker rm -f fama-g-pruebas-pg
docker volume rm fama-g-pruebas-data
```

## Límites

- La versión 16.15 viene de los recibos de octubre de la instancia `fama-postgres-pruebas`; si Cloud SQL actualizó la versión menor, la consola puede mostrar otra.
- Esta base valida migraciones, roles y permisos en PostgreSQL real, no Cloud SQL (proxy, IAM, copias administradas).
- Las pruebas automatizadas de PostgreSQL usan un contenedor desechable aparte; ver «Comprobaciones» en el [plan de la etapa g](../arquitectura/integracion-mvp-g-base-integracion-plan.md).
