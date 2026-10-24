# Respaldo y recuperación de checkpoints

Implementación del 23 de octubre de 2026 en `fix/afinamiento-integral`. Disponible para administradores e investigadores con asignación vigente al dataset del modelo. El respaldo es una acción explícita: terminar un entrenamiento no significa que sus pesos ya estén en GCS.

## Uso

1. Abre **Entrenamiento → Historial de Modelos Guardados → Ficha Técnica**.
2. En **Copias del checkpoint**, pulsa **Comprobar copias**. La consulta lee el archivo local y los metadatos del objeto cloud; no sube ni recupera pesos.
3. Si aparece **Copia local íntegra**, pulsa **Respaldar en GCS**. La aplicación prepara una copia temporal estable, la sube sin reemplazar objetos y descarga su generación concreta para comprobar tamaño y SHA-256. Solo entonces muestra **Respaldo verificado**.
4. En otro nodo que conserve acceso a la misma base, bucket e identidad del modelo, comprueba las copias. Si muestra **Sin copia local** y **Respaldo disponible en GCS**, pulsa **Recuperar en este equipo**. La descarga se valida antes de publicar el archivo local.
5. Abre de nuevo la ficha si necesitas refrescar los metadatos internos del checkpoint recuperado. Para inferencia, vuelve a consultar el catálogo de Predicción. Recuperar pesos no designa un nuevo modelo predeterminado.

Un **respaldo disponible** indica que se encontró un objeto de tamaño y generación compatibles. La consulta no descarga todos sus bytes: no acredita por sí sola integridad. La confirmación de una transferencia sí comprueba los bytes recibidos contra el hash registrado.

## Conflictos y fallos

- Un archivo local distinto, un directorio o un enlace en el destino se conserva. La interfaz bloquea la recuperación: el operador debe preservar ese archivo y revisar el conflicto antes de reintentar. No hay botón de borrado ni reemplazo forzado.
- Un objeto remoto de tamaño incompatible se marca en conflicto. Una descarga con tamaño o hash incorrectos se rechaza y el archivo local no se publica.
- Si GCS, las credenciales, la red o el disco fallan, la operación devuelve un error sin secretos y permite reintentar. Un upload cuya confirmación se pierde puede haber creado ya un objeto; el siguiente respaldo comprobará ese objeto sin reemplazarlo.
- Repetir un respaldo verifica los bytes existentes. Recuperar una copia ya íntegra no reemplaza ni cambia el archivo local.
- Las operaciones validan sesión, origen de las escrituras y asignación en cada solicitud. Revocar acceso vuelve a bloquearlas. No se conceden roles ni asignaciones como parte del respaldo.

## Qué se conserva

Se respaldan exclusivamente los bytes del checkpoint registrado, incluido su manifiesto de particiones cuando lo contiene. No se deserializa el checkpoint durante la transferencia. El nombre local, tamaño esperado y SHA-256 proceden del registro SQL; no se aceptan rutas, buckets ni archivos indicados por el navegador.

El objeto se identifica como `gs://<bucket-configurado>/models/checkpoints/sha256/<sha256>.pt`. La referencia histórica `models/<nombre>.pt` de SQL se conserva para el nombre local y no constituye por sí misma una prueba de que exista un respaldo. No se añade una migración ni una tabla SQL.

La creación usa `if_generation_match=0`. La descarga fija la generación observada y solicita bytes sin transcodificación; además de la verificación del SDK, se verifica SHA-256 localmente. La publicación local usa un temporal en el mismo directorio, fsync del archivo y enlace sin reemplazo; el directorio se sincroniza donde el sistema lo permite. Véase la [referencia oficial del SDK de GCS](https://docs.cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.blob.Blob) y el [ADR 0045](../adr/0045-respaldo-explicito-de-checkpoints-por-contenido.md).

## Alcance y límites

- Se requiere modelo asociado a dataset del bucket configurado, hash SHA-256 válido, tamaño registrado positivo y referencia administrada `models/<nombre>.pt`. Los registros históricos incompletos requieren revisión del operador; no se rellenan automáticamente.
- Límite inicial: 1 GiB por checkpoint. Las transferencias son explícitas y síncronas; consumen espacio temporal para una instantánea local y su verificación. No se implementa una cola automática, progreso en bytes ni política de retención/borrado de backups.
- El registro SQL y los permisos GCS siguen siendo fuentes de confianza. El hash acredita coincidencia de bytes con ese registro; no es una firma, no certifica calidad científica ni reconstruye una identidad perdida.
- No se cambian `activo`, las métricas, el dataset, la versión del esquema ni los pesos ya cargados en memoria. Las copias no incluyen la base SQL, las grabaciones ni los manifiestos que no estén dentro de un checkpoint.
- Recuperar el nodo completo todavía requiere copias/restauración de PostgreSQL, audios y configuración, directorios persistentes exclusivos, secretos operativos y recuperación administrativa. Esta función no constituye recuperación integral de desastres.
- No se modifica el bucket oficial con este bloque. El recorrido original se ejecutó bajo `.pytest_cache/stage8-live`; el bloque posterior trasladó los archivos a `runtime/pruebas` y sirve las fuentes originales. Véase [almacenamiento persistente](directorios_persistentes_por_entorno.md). El recibo del respaldo conserva su corte anterior.

## Verificación

Se utilizaron HTTP autenticado y UI renderizada con SQL/archivos temporales y GCS simulado. Cubren reintentos, recuperación exacta, archivos existentes, corrupción de igual tamaño, ausencia de respaldo, fallos cloud sanitizados, permisos revocados, origen ajeno, referencias que escapan y bucket incompatible. La regresión conjunta backend terminó con **163 PASS / 8 SKIP** (symlinks Windows); frontend, **42 PASS**. TypeScript y lint de los dos archivos nuevos no presentan diagnósticos. No se declara lint global ni suite global aprobados.

La comprobación cloud real y sus hashes se registran en [el recibo de este bloque](../receipts/respaldo_checkpoints_20261023.json); el registro guiado se mantiene en la [bitácora](bitacora_acceso_e_instalacion.md).


### Recorrido real de pruebas

En la sesión administradora de `localhost:3010` se respaldó el modelo #1 de `FAMA_Prueba_Aves`: **16318381 bytes**. GCS confirmó el objeto y la interfaz confirmó tamaño/SHA-256. La recuperación real se realizó en `.pytest_cache/checkpoint-recovery-20261023/checkpoints`, sin retirar la copia operativa. El hash recuperado coincide con SQL; diecisiete archivos previos y los conteos/activación SQL permanecieron iguales. El respaldo está en `fama-pruebas`; el bucket oficial no se modificó. La transferencia no ejecutó ni certificó inferencia. [Captura de respaldo](../images/respaldo_checkpoint_real_20261023.png).
