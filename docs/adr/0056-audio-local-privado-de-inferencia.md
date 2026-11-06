# Audio local privado para inferencia de modelos importados

La inferencia privada importada no debe depender de GCS. Se conserva el WAV original en el almacenamiento persistente del backend y el resultado en PostgreSQL; la predicción no incorpora miembros al dataset. La incorporación exige revisión y aprobación explícitas del propietario. El flujo legacy mantiene su requisito de GCS y sus referencias existentes.

La columna existente `Prediccion.ruta_audio_prueba` admite una referencia local estricta `local_predictions/<owner>/<uuid>/<sha256>/<size>.wav`, relativa a la raíz privada de imports. El propietario procede de la sesión y de la procedencia validada del modelo, nunca de un argumento del cliente. El hash y el tamaño quedan vinculados a la referencia persistida sin introducir una migración de esquema ni reinterpretar claves GCS como rutas locales. Las lecturas recorren directorios mediante descriptores abiertos, rechazan enlaces simbólicos y verifican tipo, enlaces, tamaño y contenido. Los directorios son privados y la publicación del archivo es exclusiva, sincronizada a disco y sin sobrescritura.

## Alternativas y consecuencias

- Ignorar un error GCS sin guardar el audio impediría revisar e incorporar posteriormente la grabación; no satisface el flujo.
- Guardar una ruta absoluta acoplaría la base a la topología del host y expondría una referencia menos confinada. Se elige una referencia relativa validada; no es una URL pública ni un permiso de acceso.
- El archivo se publica después de inferir y antes de confirmar la fila. Si falla la persistencia relacional, solo se descarta el archivo nuevo cuando una consulta confirma que no existe una referencia persistida. Un error posterior a un commit confirmado no autoriza borrar el audio.
- No hay transacción atómica entre disco y PostgreSQL. Ante confirmación incierta o cancelación en el límite de publicación se prioriza conservar bytes privados: puede quedar un archivo sin fila, sin respuesta de éxito, sin incorporación ni sincronización automática. No se introduce un recolector automático; cualquier limpieza posterior necesita establecer la ausencia de referencias.
- `gcp_upload: false` no prueba almacenamiento local. Solo una respuesta confirmada con `local_audio_saved: true` y `cloud_status: deferred` permite mostrar el estado local. La cola de sincronización de un audio aprobado es una etapa distinta.

La decisión describe el contrato implementado. La calificación y el despliegue se registran por separado en T14/S16 de `docs/arquitectura/automatic-preparation-mvp-plan.md`; este ADR no acredita una predicción real ni una operación cloud.
