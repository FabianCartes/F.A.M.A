# Integración MVP — etapa h: documentación de la integración

Objetivo: dejar la documentación coherente con lo integrado en `mvp` (U0, a–f y lo hecho de g): ADR sin números duplicados, el ADR de GCS como fuente única, notas de sustitución en los manuales del catálogo privado e índices al día. Rama `mvp` (base `faf8751` o posterior), sin push ni PR; commits locales. Solo documentación: comprobación estructural (rutas, enlaces, índices), sin pruebas de código.

## Specs
- S1 — Plan de integración, sección 4 h (copia de Kevin fuera del repo, `~/Downloads/plan-integracion-afinamiento-integral.md`): «ADR nuevo (sección 7) y renumeración de los ADR de mvp».
- S2 — «Unir `docs/KANBAN.md` y `docs/README.md`; actualizar el índice.»
- S3 — «Notas de sustitución en los manuales del catálogo privado (`importacion-datasets-zip.md`, `entrenamiento-datasets-importados.md`, `worker-importacion-zip-local.md`, `transferencias-datasets.md`).»
- S4 — «Toda la documentación bajo `docs/`; no se crea `odd/`.»
- S5 — Ajuste respecto del plan original: el ADR 0070 ya lo ocupa la etapa f. Los 7 ADR de mvp duplicados pasan a 0071–0077 y el ADR nuevo es el **0078** (el plan decía 0070–0076 y 0077).
- S6 — Kevin, 2026-11-11: «Cerremos h por mientras entonces pero hagamoslo en una nueva sesion». La etapa g queda abierta (bloqueada por el acceso a `fama-pruebas`); la revisión final de la rama se hace cuando g también esté cerrada.

## Estado verificado al planificar (`faf8751`)
- Duplicados 0052–0058. Del compañero (se conservan): `0052-sesiones-web-revocables-y-registro-administrado`, `0053-asignaciones-explicitas-y-propiedad-de-entrenamiento`, `0054-gestion-de-cuentas-y-recuperacion-administrada`, `0055-cuotas-persistentes-de-login-y-recuperacion`, `0056-auditoria-minima-y-limpieza-transaccional-acotada`, `0057-acceso-web-del-mismo-origen-y-fondo-aislado`, `0058-configuracion-persistente-y-migraciones-explicitas`.
- De mvp (se renumeran en este orden):
  - `0052-preparacion-local-de-datasets-importados` → 0071
  - `0053-procedencia-durable-de-entrenamiento-importado` → 0072
  - `0054-sesion-web-compatible-con-bearer-importados` → 0073
  - `0055-postgresql-separado-para-bootstrap-de-entrenamiento` → 0074
  - `0056-audio-local-privado-de-inferencia` → 0075
  - `0057-identidad-inmutable-de-composiciones-importadas` → 0076
  - `0058-cache-de-hash-de-checkpoints-por-identidad-de-archivo` → 0077
- Unos 20 archivos `.md` enlazan `adr/005[2-8]-…`; cada enlace a un ADR de mvp debe apuntar al nombre nuevo (los del compañero no cambian). Buscar también referencias en texto («ADR 0054») que se refieran a los de mvp, y referencias en código o recibos JSON.
- ADR 0078, contenido según la sección 7 del plan: contexto de los dos catálogos (privado local-first con copia en `private-imports/{owner}/{ds}/`; compartido con GCS como original en `datasets/{ds}/{clase}/`); decisión: GCS como fuente única, el ZIP confirmado se publica en `datasets/` y `conjunto_datos` con nombre único global, acceso por rol y asignación (el importador queda asignado; decisión 2), entrenamiento desde la copia local sincronizada con `partition_version` (etapa d); alternativas descartadas: mantener el catálogo privado o ambos; consecuencias: se pierde la privacidad por dueño, se retiran la reserva de disco `dataset_storage_*` (decisión 8), la exportación ZIP (decisión 9, anotada en el KANBAN para retomarla) y la identidad Bearer (decisión 4). Sustituye las partes de GCS de los ADR 0027 y 0044 y el 0073 (antes 0054, sesión compatible con Bearer); se relaciona con los ADR 0061–0064 y 0069 del compañero y con el 0070. Marcar en los ADR sustituidos su estado («Sustituido por 0078»), sin reescribirlos.
- Manuales de S3: ya contienen alguna mención a sustitución (`importacion-datasets-zip.md` 2, `entrenamiento-datasets-importados.md` 9, `worker-importacion-zip-local.md` 2, `transferencias-datasets.md` 1 coincidencias de «sustitu/reemplaz/retirad»). Revisar cada una antes de agregar; la nota va al inicio, breve, y enlaza el ADR 0078 y el manual vigente.
- `docs/KANBAN.md` y `docs/README.md` ya se fusionaron en U0 y se actualizaron por etapa; S2 es revisar el índice completo (entradas de las etapas U0–h, duplicados o estados obsoletos como el que tenía la tríada) y agregar 0071–0078.

## Tasks
- T1 | S1,S5 | inline | pending | Renumerar con `git mv` los 7 ADR de mvp y actualizar todos los enlaces y referencias; comprobar que no queden números duplicados ni enlaces rotos.
- T2 | S1 | inline | pending | Escribir el ADR 0078 y marcar los ADR sustituidos.
- T3 | S3 | inline | pending | Notas de sustitución en los 4 manuales.
- T4 | S2,S4,S6 | inline | pending | Índice de `docs/README.md` y KANBAN (h cerrada, g bloqueada por acceso), recibo breve si corresponde.

## Comprobaciones
- Ningún prefijo de 4 dígitos repetido en `docs/adr/`.
- Todo enlace relativo `.md` de `docs/` resuelve (script de verificación de enlaces sobre los archivos tocados y sobre los que enlazan `adr/`).
- `grep` sin resultados para los nombres antiguos de los ADR de mvp.

## Log
- L1 — Kevin: «Es buena idea avanzar con h teniendo g incompleta?». Respuesta: sí; h no depende de lo pendiente en g; no cerrar el plan ni hacer la revisión final con g abierta.
- L2 — Kevin: «Cerremos h por mientras entonces pero hagamoslo en una nueva sesion». Plan y traspaso en `faf8751`+1; Engram `integration/afinamiento-integral-handoff-h`.
