# GCS conectado al MVP local

La API del entorno manual tiene acceso directo a GCS. El frontend sigue en desarrollo y PostgreSQL permanece local. La conexión está comprobada para catálogo remoto y operaciones del adaptador de almacenamiento; **la sincronización de importaciones en cola no está habilitada**.

## Comprobación rápida

1. Abrir http://127.0.0.1:3000 y consultar la pantalla de datasets.
2. El catálogo compartido remoto contiene AvesChilenas1220archivos, engine_diagnostics1386 y MaquinariaMinas1, según el listado verificado. No unirlos con los datasets privados importados por coincidencia de nombre.
3. Consultar, sin modificar datos:

   ```sh
   curl --fail http://127.0.0.1:3000/api/ingestion/status
   curl --fail http://127.0.0.1:3000/api/ingestion/datasets
   ```

La salud de la API se comprueba en `http://172.23.0.3:8000/health`. La ruta `/api/health` no existe; no usar su404 para concluir que la API está caída. La aceptación visual corresponde al usuario; la comprobación funcional observada fue HTTP/JSON a través del frontend, no una prueba de navegador.

## Configuración conservada

| Área | Configuración |
| --- | --- |
| API | Misma imagen, usuario1000:1000, raíz de solo lectura y restricciones previas |
| Red interna | API/PostgreSQL, IP de API172.23.0.3 conservada |
| Salida | Segunda red bridge dedicada a la API; prioridad de gateway10; sin puertos nuevos publicados |
| Credencial GCS | Copia privada0600, montaje de solo lectura `/run/secrets/gcs-service-account.json`; valores fuera de Git |
| Variables añadidas | `GCS_BUCKET_NAME`, `GOOGLE_APPLICATION_CREDENTIALS`, `GCP_KEY_PATH` |
| Entrenamiento | GPU y caché de pesos RO conservadas; opciones offline permanecen activas |
| Arranque | `FAMA_APP_STARTUP_POLICY=isolated`; no inicia worker de feedback ni seeding |
| Datos | Mismos volúmenes; sin migración, descarga masiva ni activación de modelos |

La salida general permite iniciar conexiones a destinos distintos de Google. Fue autorizada explícitamente; no equivale a un proxy restringido. El montaje RO protege el archivo, **no limita los permisos IAM de la cuenta de servicio**. No se certificaron permisos mínimos para producción.

## Evidencia y límites

- Lectura inicial de2607objetos bajo `datasets/`; las cantidades son objetos/archivos del catálogo, no aceptación acústica ni calidad de datos.
- Prueba real desde la imagen aplicada: un WAV sintético de556bytes, bajo un prefijo nuevo `mvp-integration-tests/`. Creación condicional, lectura SHA256, repetición con misma generación y rechazo de conflicto; el objeto se conserva, no se borró.
- Historial y catálogo privado comparados por el padre;10383entradas de archivos conservadas, con SHA de pequeños y metadatos de grandes. No se hizo hash completo de todos los WAV ni auditoría integral de DB.
- Verificación independiente del runtime: identidad/configuración, redes, IP, HTTP200, privado anónimo401, CUDA disponible y worker activo. No repitió login ni prueba cloud de escritura.
- Sin entrenamiento, inferencia, prueba de rendimiento, restore real ni calificación de producción. La recuperación está preparada conservando el contenedor anterior, pero no se ejecutó un rollback.
- El indicador global de almacenamiento actualmente lista como máximo2000objetos; no tratar `total_objects` de `/status` como inventario completo. Los conteos por dataset se comprobaron por separado.

Recibo: [gcs-mvp-integration.json](../receipts/gcs-mvp-integration.json). Plan y antecedentes, incluidos fallos y recuperación de comparadores: [gcs-mvp-integration-plan.md](../arquitectura/gcs-mvp-integration-plan.md).

## No activar una cola por accidente

El botón de sincronización de una importación admite un trabajo durable; no ejecuta necesariamente la subida en la API. El worker ZIP actual se inicia con `--local-only --watch`, limpia su entorno y no dispone de la configuración GCS añadida al contenedor. Que esté activo **no significa que reclame trabajos sync**.

No quitar `--local-only`, cambiar a startup normal ni ejecutar un worker general para intentar arreglarlo: podría reclamar otros trabajos. Una entrega posterior debe definir un consumidor sync acotado, su identidad, permisos, perfil de almacenamiento y prueba completa de cola, preservando el sandbox ZIP y los trabajos existentes. El worker de feedback también permanece desactivado y su uploader legacy necesita revisión de sobrescrituras antes de habilitarlo.

## Recuperación y reinicios

Las recetas y la captura exacta anterior están en registros operativos privados del proyecto; no publicarlas porque contienen configuración sensible. No usar la receta histórica que falló por diferencias de entorno ni ejecutar el Compose general como sustituto del despliegue manual.

Ante un problema, identificar los contenedores por sus IDs registrados, conservar datos y restaurar la conexión interna/IP del original detenido. No hacer `docker compose down -v`, restauraciones globales, limpiezas Git ni borrados. Para reinicios controlados, comprobar trabajos y drenar solicitudes por SIGTERM sin SIGKILL; no interrumpir una preparación síncrona.
