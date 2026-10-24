# Permisos sobre recursos asignados

**18 de octubre de 2026 — implementación backend, sin despliegue real.** [Decisión ADR 0053](../adr/0053-asignaciones-explicitas-y-propiedad-de-entrenamiento.md).

## Asignaciones administradas

Con sesión web de administrador:

| Método | Ruta | Contrato |
| --- | --- | --- |
| GET | `/api/access/users/{user_id}/datasets/{dataset_id}` | `{user_id, dataset_id, assigned}` |
| PUT | Misma ruta | Concede de forma idempotente; 200. |
| DELETE | Misma ruta | Revoca de forma idempotente; 204. |

Usuario y dataset deben existir. Anónimo: 401; investigador: 403; identidad ausente: 404. PUT/DELETE requieren el origen web configurado, como las demás escrituras. No hay asignaciones implícitas al iniciar sesión, subir archivos, descubrir un modelo o por tener el mismo nombre que una carpeta. La interfaz gráfica para administrar asignaciones todavía no existe.

## Política por operación

- **Todas las 22 operaciones funcionales `/api/*`** requieren sesión web. Login conserva su política pública; registro sigue limitado a administradores. `/` y `/health` permanecen públicos como liveness, no como garantía de autorización o preparación operacional.
- **Dashboard:** datasets, audios, predicciones, modelo de referencia y sus curvas se consultan dentro del alcance permitido. Las referencias experimentales históricas siguen identificadas como referencias, no como disponibilidad actual.
- **Catálogo/predicción:** solo modelos con destino autorizado; si el default global es ajeno, no se publica como default del investigador ni se permite usarlo implícitamente. Se comprueba el predictor resuelto, no el `dataset_name` del formulario. Para modelos publicados desde BD también se verifica la FK actual, sin confiar en metadata antigua en memoria.
- **Ingesta:** investigador recibe inventario de los registros asignados, con `source=database` y salud/sincronización cloud desconocidas (`null`). No ejecuta el inventario global de GCS. Archivos, subida y cada elemento de sync requieren asignación; todo el lote se comprueba antes de la primera transferencia. El administrador mantiene las operaciones globales y creación de nuevos datasets mediante las operaciones existentes. Estado global de almacenamiento: solo administrador.
- **Entrenamiento:** datasets e historial filtrados antes de recorrer fuentes locales o abrir checkpoints. Inicio requiere dataset asignado. Progreso y parada requieren propietario más asignación vigente; administrador puede gestionar todos los trabajos del proceso. Hardware es información disponible para usuarios autenticados. Resultados HTTP nuevos guardan `user_id` y quedan inactivos hasta activación administrativa explícita.
- **Feedback:** autor obtenido de la sesión. El campo legacy `id_usuario` se ignora y no tiene default 1 en el contrato HTTP. No se puede sobrescribir feedback de otro autor como investigador. Pendientes, métricas y estados de sincronización se filtran en SQL antes de aplicar límites. Aprobar/rechazar comprueba la relación de la predicción con un dataset asignado; el destino persistido no se sustituye por un nombre enviado en la petición.

Los permisos se vuelven a consultar en cada petición. Revocar una asignación afecta la siguiente petición, no cancela ni revierte transferencias/trabajos ya admitidos. El administrador puede detener un trabajo cuyo investigador perdió acceso.

## Datos existentes y cambios de esquema

`asignacion_dataset` vincula PK de usuario y dataset. `acceso_prediccion` conserva PK de predicción, dataset y actor para predicciones nuevas con origen asociado verificable; se inserta en la misma transacción que la predicción. Si un adaptador utilizado por el administrador carece de destino asociado, no se inventa esa relación y el resultado queda restringido a administración. No se modifica ni rellena por suposición la historia existente.

Un modelo persistido en BD sin FK o una predicción histórica sin la nueva relación quedan restringidos al administrador, incluso si su nombre/clase/texto coincide con un dataset asignado. Los adaptadores registrados explícitamente declaran su destino canónico y no se incorporan automáticamente a BD por esta autorización. Las relaciones nuevas no corrigen ni certifican archivos cloud históricos.

No se ha ejecutado DDL contra PostgreSQL local ni GCP. El arranque existente registra las tablas ORM con `create_all`; no sustituye las migraciones explícitas, respaldo y pruebas PostgreSQL/Cloud SQL exigidas antes del despliegue. Tampoco se ha migrado la BD, creado cuentas reales o concedido asignaciones reales.

Se comprobó únicamente la compilación SQLAlchemy del DDL de las dos tablas nuevas para el dialecto PostgreSQL (PK y FK declaradas). Es validación estática, no ejecución, migración ni prueba de conectividad.

## Verificación y siguientes pasos

`backend/tests/test_resource_access.py` prueba las rutas con sesiones reales de prueba, SQLite temporal y fuentes/adaptadores sintéticos. Comprueba concesión/revocación, rechazo anónimo de las 22 operaciones, aislamiento de listados/agregaciones, rechazo previo a IO, lote mixto, default ajeno, metadata antigua, identidad del feedback, historia sin asociación y propiedad de trabajos. Las pruebas antiguas de negocio usan una identidad administrativa explícita; no sustituyen las pruebas dedicadas de sesiones/permisos.

Focal final: **82 PASS** en `test_resource_access.py`, `test_web_sessions.py`, `test_api_training.py`, `test_api_feedback_sync.py` y `test_audio_review_flow.py`, tres avisos de deprecación. Las pruebas de sesiones/permisos habilitan claves foráneas SQLite. También se verifica que un inicio fallido no exponga campos del snapshot del entrenamiento anterior. No se han ejecutado nuevamente los benchmarks reales.

Un intento más amplio dio **382 PASS / 55 FAIL / una deselección**: se reconciliaron las expectativas del autor de entrenamiento y dos fixtures de negocio, pero no se declara la matriz completa verde. Persisten pendientes de portabilidad POSIX/symlinks/encoding y una discrepancia de política del catálogo protegida como cambio local previo. Detalle y regresión posterior acotada en KANBAN; no se ha ejecutado un baseline separado para atribuir todos esos fallos al entorno o a una revisión anterior.

Cierre posterior acotado: **272 PASS / una deselección** de calidad real en 17 archivos, tres deprecaciones (190,99 s). No incluye `test_api_model_catalogue.py`, `test_training_flow.py` ni `test_feedback_local_approval.py`; los resultados anteriores de esos archivos no se sustituyen por esta selección verde. El comando y la lista de archivos corresponden a los contratos de permisos/sesiones, autenticación, APIs de predicción/entrenamiento/ingesta/dashboard/feedback, entrenamiento, cola y revisión de audio; detalle en KANBAN.

El estado de regresión y su alcance se registra en [KANBAN](../KANBAN.md). No es evidencia de concurrencia PostgreSQL, aislamiento entre procesos, navegador, servicios cloud ni seguridad integral. El scheduler sigue siendo de un proceso; antes de usar varios workers o réplicas se requiere diseño y validación específicos.

Actualización posterior: la [gestión backend de cuentas](gestion_cuentas_y_recuperacion.md) ya incorpora suspensión/cambio de contraseña con revocación, preservación del último administrador y recuperación administrada. Siguen pendientes límites de intentos, auditoría, limpieza, las pantallas de cuentas/login centrado/SlicedWaves, setup y preparación de producción.
