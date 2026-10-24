# Asistente de primera instalación

Implementado en la etapa 7, el 22 de octubre de 2026, en `fix/afinamiento-integral`. El recorrido es **requisitos → PostgreSQL → Google Cloud Storage → comprobaciones → primer administrador → finalización**. Utiliza el estilo de las vistas de administración.

El asistente conecta recursos existentes. La instancia, el proxy, ADC y las migraciones se preparan con los [manuales de conexiones](conexiones_cloud_sql_y_gcs.md) y [permisos PostgreSQL](permisos_aplicacion_postgresql.md). No aprovisiona GCP ni ejecuta migraciones privilegiadas. La cuenta SQL diaria conserva sus permisos DML; el migrador no queda en el backend.

## Abrir el asistente

1. Mantener disponible el proxy y seleccionar el directorio persistente de esta instalación al iniciar el backend. Para el perfil nativo de pruebas preparado en este equipo:

   ```powershell
   Set-Location 'C:\Users\fabia\Desktop\F.A.M.A\backend'
   & .\.venv\Scripts\python.exe -m app.node --config-dir "$PWD\installation\cloud-pruebas\native" serve --port 8000
   ```

2. Iniciar el frontend con su proxy hacia ese backend. El navegador y `/api` deben usar el mismo origen. Con el frontend en `http://localhost:3000`, abrir `http://localhost:3000/installation`. La entrada habitual también redirige allí cuando el backend informa instalación pendiente. Una caída de un equipo ya configurado no provoca esta redirección.
3. En otro terminal del equipo, generar la autorización:

   ```powershell
   Set-Location 'C:\Users\fabia\Desktop\F.A.M.A\backend'
   & .\.venv\Scripts\python.exe -m app.node --config-dir "$PWD\installation\cloud-pruebas\native" setup-code --web-origin http://localhost:3000
   ```

4. Introducir localmente el campo `authorization_token` de la respuesta en **Código de autorización**. No compartirlo por chat ni añadirlo a la URL. Caduca a los 15 minutos; generar otro invalida el anterior. El origen debe coincidir exactamente: `localhost` y `127.0.0.1`, o puertos diferentes, son orígenes distintos. HTTP se admite únicamente en loopback; otros destinos necesitan HTTPS.

La CLI protege el directorio para el usuario del equipo y SYSTEM en Windows, o mediante permisos privados en POSIX. El proceso del backend debe ejecutarse con una identidad que pueda leerlo. Una instalación cerrada rechaza generar un nuevo código. El código se muestra solo en el terminal del operador; el servidor conserva su digest y el navegador lo mantiene en memoria. Recargar exige autorizar de nuevo.

Las vistas `native` y `docker` son configuraciones diferentes. Completar una no completa la otra; no alternarlas para reabrir o adoptar la base ya inicializada. Para Docker se debe operar sobre el directorio realmente montado por ese servicio y con su origen web exacto.

## Qué hace cada paso

| Paso | Datos y comportamiento |
| --- | --- |
| Requisitos | Muestra la conexión preparada y si hay un archivo de autenticación disponible. No revela su ruta ni contenido. |
| PostgreSQL | Proyecto, base, usuario de aplicación y contraseña SQL. Instancia y dirección del proxy permanecen bajo control del operador. El proyecto debe corresponder a la instancia preparada. Si hay contraseña guardada, dejar el campo vacío la conserva. |
| Google Cloud Storage | Nombre del bucket sin `gs://`; reutiliza la identidad técnica preparada en el servidor. No solicita claves JSON al navegador. |
| Comprobaciones | Presenta por separado conexión SQL, lectura del bucket, estructura/revisión del esquema, permisos SQL, configuración de acceso y disponibilidad de la primera cuenta. Solo habilita continuar si todo pasa. |
| Administrador | Nombre, correo y contraseña confirmada de al menos 12 caracteres. La cuenta se guarda activa, con rol administrador, y su creación queda auditada en la misma transacción. |
| Finalización | Confirma el registro persistente y cierra el asistente. **Es necesario reiniciar el servicio del backend** para habilitar la aplicación funcional; después se ingresa con la cuenta creada. |

La comprobación GCS del asistente **solo lista objetos**. No sube ni descarga archivos; los permisos efectivos de escritura se validan por separado en la instalación completa. La etapa 6 ya documentó esas operaciones sobre el bucket de pruebas real. La revisión SQL espera `0002_access`: 15 tablas de aplicación con DML sin propiedad/DDL ni delegación, `alembic_version` en solo lectura y 9 secuencias con USAGE/SELECT sin UPDATE.

Las respuestas privadas usan `Cache-Control: no-store`; las contraseñas desaparecen del formulario al enviarlas. Los secretos se guardan mediante referencias a archivos protegidos del equipo. Ni los códigos de error ni el estado HTTP devuelven contraseñas, claves o cadenas de conexión completas. El servicio no elimina archivos de secretos anteriores que pudieran estar compartidos con otro perfil; su mantenimiento corresponde al operador.

## Fallos y reanudación

| Resultado | Acción |
| --- | --- |
| Código inválido o caducado | Generar otro desde el equipo y volver a autorizar. |
| Origen no autorizado | Abrir el origen indicado por el operador o volver a generar el código para el origen correcto. |
| SQL rechazado o no disponible | Revisar proxy, base, usuario y contraseña. No sustituir el usuario diario por el migrador para saltar la comprobación. |
| Esquema o permisos incompatibles | El operador debe aplicar/revisar las migraciones y el script de permisos; luego repetir las comprobaciones. |
| GCS sin permisos o bucket ausente | Revisar el nombre, ADC y acceso de la identidad técnica sobre ese bucket. |
| Base con datos existentes | Se rechaza la instalación. Este asistente no migra datos ni adopta cuentas existentes. No borrar datos para forzarlo. |
| Otra operación en curso | Esperar su resultado y reintentar. El bloqueo también evita rotar la autorización durante la finalización. |
| Finalización pendiente | Conservar el directorio del nodo, volver a autorizar y pulsar **Reanudar finalización**. No se pide otra contraseña ni se crea otra cuenta. |
| Instalación finalizada | Reiniciar el backend. Una indisponibilidad posterior se trata como incidente; no reabre el asistente. |

Antes de insertar la cuenta se guarda `finalization.json` privado con la identidad, hash de contraseña y huella de los destinos. Un bloqueo de archivo serializa las escrituras del nodo; un bloqueo asesor PostgreSQL protege la comprobación de base vacía y creación frente a otro nodo. Si falla la auditoría SQL, la cuenta se revierte; si falla el guardado local después del commit, el reintento reconoce exclusivamente esa cuenta y su evento original. La configuración queda inmovilizada mientras haya finalización pendiente.

No editar ni retirar el registro pendiente para crear otro administrador. Si se pierde el directorio local, cambia el destino o el contenido de la base ya no corresponde a la intención original, el procedimiento falla de forma conservadora. La recuperación del operador ante pérdida de estado o bloqueo de todos los administradores forma parte de la etapa 9, no de esta reanudación.

## Alcance verificado

Las pruebas cruzan HTTP/CLI y formularios visibles. Utilizan PostgreSQL 16 desechable con permisos reales, y simulan GCS únicamente en la biblioteca externa de Google. Cubren autorización/expiración/origen, configuración privada, permisos insuficientes, creación y login, bloqueo concurrente, reversión SQL, fallo de escritura local y reanudación tras reconstruir la aplicación. Las pruebas de sesión existentes se mantienen con las mismas interfaces públicas.

La revisión en navegador recorrió todos los pasos y finalizó una instalación **sintética y desechable**, con PostgreSQL local real y GCS simulado. [Comprobaciones](../images/instalacion_etapa7_comprobaciones_20261022.png) y [resultado final](../images/instalacion_etapa7_finalizada_20261022.png). No acredita GCS real desde el asistente, vista móvil, reinicio con carga ML ni despliegue institucional. La configuración remota de pruebas permanece sin finalizar y sin primer administrador real: el siguiente recorrido conjunto corresponde a la etapa 8 del [plan](plan_instalacion_gcp_y_asistente.md).

Decisión y consecuencias: [ADR 0060](../adr/0060-autorizacion-y-finalizacion-reanudable-de-instalacion.md). Comandos, resultados, hashes y limpieza: [recibo de etapa 7](../receipts/instalacion_etapa7_asistente_20261022.json).
