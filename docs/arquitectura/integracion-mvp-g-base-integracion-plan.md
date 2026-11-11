# Integración MVP — etapa g: base de datos de integración `fama_pruebas`

Objetivo: preparar desde cero una base PostgreSQL 16.15 vacía con el esquema 0005, los roles y permisos del flujo oficial y el primer administrador, y comprobar la aplicación de punta a punta. Rama `mvp` (base `8c99efb`), sin push ni PR. Estrategia de entrega: commits locales por unidad; la revisión de la rama se hace al terminar el plan completo. Runner: `backend/tests/run_isolated_training_checks.py`.

## Specs
- S1 — Etapa 1 local, según la sección 8 del plan de integración (copia de Kevin fuera del repo, `~/Downloads/plan-integracion-afinamiento-integral.md`): «Base nueva y vacía. No se reutiliza la base local actual ni se toca `fama_oficial`.» PostgreSQL 16 en Docker, base `fama_pruebas`, «de modo que los scripts se usan sin cambios».
- S2 — Versión: 16.15, tomada de los recibos `instalacion_etapa4_roles_20261022.json`, `instalacion_etapa5_conexiones_20261022.json` e `instalacion_etapa6_permisos_20261022.json` (instancia `fama-postgres-pruebas`, `POSTGRES_16`, `16.15`). Supuesto: Cloud SQL no ha cambiado de menor desde el 22 de octubre; no se consultó la consola.
- S3 — Pasos 1–8 del plan: superusuario solo para crear la base vacía y un dueño no superusuario con `CREATEROLE`; `preparar_roles_pruebas.sql` como ese dueño; contraseñas de `fama_migrador` y `fama_app`; `python -m app.schema status`, `upgrade --apply`, `status` (0001 a 0005); `permisos_tablas_pruebas.sql` como `fama_migrador` con resultado `runtime_permissions_ready`; arranque con `fama_app` vía `DATABASE_URL_FILE`; primer administrador con `python -m app.node --config-dir <dir> setup-code --web-origin <origen>` y `/api/installation/configuration`, `/check`, `/complete`.
- S4 — La verificación de instalación debe aceptar una base 0005 correcta. Hoy rechaza toda base 0005 porque espera 14 secuencias (`backend/app/installation.py:253`) y la 0005 agrega `triad_composition.id`.
- S5 — Pasos 9–11: bucket de pruebas propio en `GCS_BUCKET_NAME`, separado del real; smoke «crear administrador e investigador, importar ZIP, publicar, asignar, sincronizar, entrenar, respaldar el modelo en GCS y predecir»; recreación desde cero (`docker compose down -v` y repetir).
- S6 — Etapa 2 Cloud SQL: mismos scripts y smoke sobre una base vacía vía Cloud SQL Auth Proxy 2.26.2; la ubicación se decide al terminar la etapa local, tras hablar con el compañero (decisiones 6 y 7). No se copia un dump.
- S7 — Corregir los manuales del procedimiento que describen cortes previos (0002/0003, 15–16 tablas, 9 secuencias).

## Estado verificado al planificar (`8c99efb`, exploración de solo lectura)
- `preparar_roles_pruebas.sql` exige `current_database() = 'fama_pruebas'` y `public` vacío; crea `fama_migrador` y `fama_app` con `PASSWORD NULL`. No existe un script para el paso 1 ni para las contraseñas: en Docker son `CREATE DATABASE`, `CREATE ROLE ... CREATEROLE` y `ALTER ROLE ... PASSWORD`.
- `app.schema`: `HEAD = 0005_triad_composition`; lee solo `DATABASE_URL` (no `.env`). La 0005 nunca se ha aplicado en PostgreSQL.
- `permisos_tablas_pruebas.sql` ya exige 0005 y cubre 38 tablas de negocio, incluida `triad_composition`, más `alembic_version`; las secuencias se toman de `pg_depend`.
- **Bloqueante (S4):** `installation.py:253` fija `len(sequences) == 14`; con 0005 serían 15 (9 de 0002, 5 de 0004, 1 de 0005), así que `/check` devuelve `database_runtime_permissions_invalid` y `/complete` se niega. Se confirma con RED antes de corregir.
- Contenedores existentes: `docker-compose.yml` crea `fama_db` en `postgres:16-alpine` y publica 5432; los verificadores aislados usan `postgres:16-alpine` sin puerto. Ninguno fija 16.15. La base de g se levanta aparte, con imagen `postgres:16.15`, otro puerto y su propio volumen, sin tocar `fama-db` ni contenedores ajenos.
- Manuales desactualizados: `permisos_aplicacion_postgresql.md` (0003 y 16 tablas), `asistente_primera_instalacion.md` (0002 y 15 tablas), `preparacion_instalacion_y_migraciones.md` (enumera 0001–0003 en un párrafo).
- La app nativa lee `backend/.env`; hay que arrancarla con variables explícitas para no mezclar su `DATABASE_URL`.

## Decisiones abiertas (una a la vez, antes de la tarea afectada)
1. S4, antes de T1: derivar el número esperado de secuencias de la metadata de HEAD (recomendado: no vuelve a romperse en la próxima migración) o fijar 15.
2. S5, antes de T4: nombre del bucket de pruebas y credencial a usar (la confirma Kevin; no se reutiliza el bucket real).

## Tasks
- T1 | S4 | inline | pending | RED: prueba pública de `InstallationService.check` sobre el esquema 0005 con permisos correctos que hoy devuelve `database_runtime_permissions_invalid`; GREEN según la decisión 1. Risk: item 2 (guarda de permisos de la instalación).
- T2 | S1-S3 | inline | pending | Levantar `postgres:16.15` local con volumen propio, crear base y dueño, roles, contraseñas (archivos en directorio privado fuera del repo), migrar 0001→0005, permisos, arranque con `fama_app` y primer administrador. Recibo `docs/receipts/integracion-mvp-g-local.json` sin secretos. Risk: item 5 (entorno).
- T3 | S7 | inline | pending | Manual del procedimiento local en `docs/manuales/` y corrección de los conteos de los manuales desactualizados.
- T4 | S5 | inline | pending (decisión 2) | Bucket de pruebas, investigador, smoke de punta a punta y recreación desde cero.
- T5 | S6 | pending (decisiones 6 y 7 del plan general) | Cloud SQL tras la etapa local.

## Comprobaciones
- Backend: runner aislado con los selectores de instalación y permisos (`tests/test_installation*.py`, `tests/test_permisos_tablas_pruebas.py`, `tests/test_preparacion_roles_pruebas.py`); comparar contra la base `8c99efb`.
- Las pruebas de roles y permisos con `FAMA_TEST_ROLES_POSTGRES_URL` pueden correr contra el contenedor de g.
- Efectos de T2: un contenedor y un volumen locales con nombre propio; se registran sus identificadores en el recibo y se retiran solo con autorización.

## Log
- L1 — Kevin, 2026-11-11: «Sigamos avanzando con el plan, la revision se debe realizar al terminar el plan, el plan esta en ~/Downloads/plan-integracion-afinamiento-integral.md / Aunque tambien se realizaron algunos ajustes, por lo que consulta en engram».
- L2 — Kevin: «Eso no aparece en la rama de fix/afinamiento y no recuerdo el resto del nombre». La versión 16.15 se tomó de los recibos de octubre (S2).
- L3 — Kevin: «Procede con la exploracion para armar el plan para implementar g». Explorador de solo lectura (mapa de pasos, scripts, manuales y variables); el padre comprobó `installation.py:253` y `schema_0005.py:10`. Ajustes heredados de f: la 0005 no crea tablas de snapshots y agrega `triad_composition`; el ADR 0070 ya está ocupado (afecta la numeración de h).
