# Consumidor exclusivo de sincronización GCS

El consumidor separado está desplegado en el MVP local. La prueba pública sintética completó recepción, validación, publicación local y sincronización en GCS. Una respuesta **202 solo acredita admisión**: el resultado comprobado fue `succeeded`, con revisión completa, generaciones, SHA-256 y tamaños verificados.

No sustituye al worker ZIP, no entrena modelos ni activa feedback. PostgreSQL y el frontend de desarrollo siguen locales. Este recorrido no certifica un despliegue de producción.

## Modos del CLI

`backend/scripts/run_dataset_import_worker.py` requiere base de datos, raíz privada de importaciones y raíz privada de intentos. No imprimir URLs con credenciales ni trasladar recetas privadas al repositorio.

| Modo | Trabajos reclamados |
| --- | --- |
| Sin modo específico | Comportamiento general anterior: cualquier tipo elegible |
| `--local-only` | Solo preview/confirm; no construye almacenamiento cloud |
| `--sync-only` | Solo sync; no reclama preview/confirm, ni siquiera expirados |
| `--cleanup-only` | Limpieza explícita anterior; no se combina con otros modos |

`--watch` requiere `--local-only` o `--sync-only`. `--poll-seconds` admite valores finitos entre 1 y 3600; `--execution-seconds`, mayores que 0 y hasta 3600. SIGINT/SIGTERM conservan la parada después del intento y la restauración de handlers. `{"claimed": true}` indica un intento, no su éxito: consultar `status_url`.

## Migración local aplicada

El preflight encontró cero trabajos sync pendientes/activos, pero faltaban dos tablas y permisos de actualización. Tras autorización explícita:

1. Se generó un respaldo PostgreSQL custom de 948368 bytes y se restauró en PostgreSQL aislado de la misma imagen: 31 tablas y conteos de filas iguales. El dump conserva propietarios/ACL; la restauración de prueba omitió aplicarlos y, por tanto, no valida una restauración de roles o ACL.
2. Se comprobó la migración existente y su repetición en la copia. El script administrativo no estaba empaquetado en la imagen: se montó como solo lectura en el proceso temporal, sin modificar la imagen de la API.
3. Se detuvieron los escritores conforme a la guarda de la migración. La API terminó mediante SIGTERM y exit 0; el worker ZIP se inició después con los mismos argumentos y protecciones. No hubo SIGKILL, cambio de startup ni activación de feedback.
4. Se crearon `imported_dataset_revision` e `imported_dataset_revision_object`, inicialmente vacías, sin backfill. Los SHA-256 del contenido de las 31 tablas existentes coincidieron antes y después del DDL, con escritores detenidos.
5. Se restauraron los mismos contenedores y configuración de API/DB. El historial y catálogo privados anteriores coincidieron y CUDA siguió disponible.

No se migra PostgreSQL a GCP. El CLI no crea tablas ni amplía privilegios automáticamente. Ante un fallo transaccional, conservar el estado y diagnosticar; no ejecutar un restore destructivo ni eliminar tablas por iniciativa propia. El respaldo contiene datos privados y no se versiona.

### Privilegios mínimos de sincronización

El rol de aplicación conserva sus permisos anteriores y recibe únicamente:

| Tabla | Permisos adicionales |
| --- | --- |
| `imported_dataset_revision` | SELECT, INSERT; UPDATE de `verified_count`, `verified_bytes`, `manifest_key`, `manifest_generation`, `manifest_sha256`, `manifest_size_bytes`, `status` |
| `imported_dataset_revision_object` | SELECT, INSERT; UPDATE de `object_generation`, `verified_sha256`, `verified_size_bytes` |
| `dataset_import_file` | UPDATE de `sync_status` |
| `imported_dataset_member` | UPDATE de `sync_status`, `object_key`, `object_generation` |

No se concede administración, DELETE sobre las revisiones ni UPDATE general de las tablas nuevas. Se comprobaron negativas para modificar el nombre de la revisión y la clase de la membresía. No se cambia IAM: montar una credencial RO protege el archivo, no limita sus permisos cloud.

## Proceso separado

- Modo `--sync-only --watch`, con cero sync antiguos al arrancar.
- CPU, usuario 1000, root filesystem RO, capabilities eliminadas, `no-new-privileges`, sin GPU ni puertos publicados.
- Importaciones locales compartidas y staging propio como superficies RW; credenciales PostgreSQL/GCS y CLI fijado como RO.
- Red interna de DB y puente de salida propio. La salida a Internet es general, no una allowlist de Google; no se reutiliza el proxy descartado ni se modifica el puente exclusivo de la API.
- Reinicio `unless-stopped` habilitado después de la prueba funcional; logs rotados. El servicio ZIP conserva su sandbox y modo `--local-only --watch`.

## Prueba pública realizada

Se dejó un dataset nuevo identificado como **GCS Sync Smoke a7c3e291**, sin reutilizar datos anteriores:

1. Crear importación y recepción; enviar un ZIP de 22629 bytes en un fragmento y finalizarlo.
2. Admitir preview y confirm con 202, observar ambos trabajos `succeeded` y estado local `imported`.
3. Admitir sync con 202 y esperar `succeeded`, no solamente `claimed` o `running`.
4. Consultar la revisión 1 completa: un WAV, 32044 bytes verificados.
5. Leer original y manifiesto con sus generaciones inmutables; comprobar SHA-256 y tamaño de ambos desde el entorno real del consumidor.
6. Repetir la misma clave de sync: mismo trabajo terminado, sin crear otra sincronización. Comprobar 401 sin autenticación.

La prueba deja deliberadamente sus registros y objetos sintéticos. No borra objetos cloud ni sincroniza datasets previos. No acredita lotes grandes, tolerancia a fallos de red, calidad acústica, entrenamiento real, restauración de producción ni aceptación visual del frontend.

## Evidencia y límites

El runner protegido comprobó 68 casos de migración/CLI/sync/ejecución local, exclusivamente con SQLite en memoria y CPU, sin red ni DB real. El diferencial anterior conservó los modos general/local/cleanup y sus salidas, salvo el help y el error de watch ampliados intencionalmente. No se ejecutó la suite global del backend.

La evaluación nativa no pudo determinar el riesgo por archivos no rastreados no declarados; no equivale a aprobación. El cierre independiente, sus comandos y cualquier fallo o corrección del vector se registran en el recibo.

- [Plan y seguimiento](../arquitectura/gcs-sync-consumer-plan.md)
- [Recibo de sincronización](../receipts/gcs-sync-consumer.json)
- [Conexión GCS previa](gcs-mvp-local.md)
