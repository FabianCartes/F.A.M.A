# Actualización oficial a 0004 — 25 de octubre de 2026

Estado: aplicada y comprobada. F.A.M.A. funciona en `http://localhost:3010/`, con backend 8010, proxy Cloud SQL 5434, base `fama_oficial`, bucket `fama-audio-records-2026` y runtime existente. El código de aplicación es `54bdaaf`, rama `fix/afinamiento-integral`, en la carpeta habitual `C:/Users/fabia/Desktop/F.A.M.A`. La copia de integración deja de ser el checkout de trabajo. [Recibo de esta operación](../receipts/actualizacion_oficial_0004_20261025.json).

## Trabajo del operador y de Codex

El operador pidió aplicar el paso pendiente y facilitó la entrada para autenticar al usuario SQL migrador. Se comprobó la identidad exacta `fama_oficial_migrador` en `fama_oficial`; la contraseña se introdujo por terminal sin eco y quedó solo en memoria. No se guardó ni se cambiaron contraseñas.

Codex preparó un primer respaldo y copia privada del perfil, secretos e índices; calculó huellas de los cinco checkpoints. Verificó los procesos que atendían 3010/8010 y los detuvo, conservando el proxy y los servicios ajenos. Tomó entonces el respaldo final sin escritores y comparó todos los registros y secuencias antes de aplicar la actualización.

Se aplicó una sola vez `0003_autonomy → 0004_integration`, con la función pública de migración y sus comprobaciones de estructura. Añadió 21 tablas; la base queda con 37 tablas de negocio, `alembic_version` y 14 secuencias. Las tablas nuevas de control contienen sus tres filas iniciales. Todas las filas y secuencias previas coincidieron con el respaldo al terminar la migración.

La primera ejecución del archivo de permisos se detuvo por pasar su cuerpo SQL mediante un método DBAPI con parámetros implícitos. Se reanudó desde la revisión ya aplicada con `cursor.execute` sin parámetros, dentro de una transacción. Se conservaron las guardas de base, usuario propietario y revisión; no se repitió la creación de tablas. La cuenta diaria conserva DML en las tablas de negocio, lectura de `alembic_version` y USAGE/SELECT de las secuencias, sin DDL ni UPDATE de secuencias.

El checkout original volvió a `fix/afinamiento-integral`. Se conservaron las notas y recibos locales de reinicio y diagnóstico de identidad. La configuración privada y sus referencias absolutas se reutilizaron sin cambiar sus bytes, claves, cuenta web o bucket.

## Compatibilidad de los cinco modelos históricos

El primer catálogo nuevo mostró solo el Super-Ensamble: los cinco modelos históricos tenían `hash_binario=NULL`. La guarda nueva exige una identidad SHA-256 persistida para publicar modelos SQL.

Se verificaron bytes, tamaños, SHA-256 local y coincidencia MD5/tamaño con las copias ya existentes en `operator_backups/checkpoints/sha256/<huella>.pt` de GCS. Una transacción completó únicamente `hash_binario` de los modelos 2–6, condicionada a que siguiera vacío y coincidieran ruta/tamaño. No se cambiaron activaciones, métricas ni relaciones de dataset; tampoco se escribieron objetos GCS. No se inventó procedencia de entrenamiento ni evaluaciones estándar de los históricos.

El catálogo final devuelve seis opciones disponibles, sin errores de publicación: Super-Ensamble predeterminado y cinco modelos individuales. Las huellas y generaciones observadas figuran en el recibo.

## Comprobaciones observadas

- PostgreSQL y lectura del bucket: correctos. Revisión `0004_integration`, permisos diarios válidos y configuración preparada. La comprobación de alta inicial informa `database_already_initialized`, que es lo esperado en un perfil ya completado; no se ejecutó otra alta.
- Cuenta administradora real: login 200, cookie HttpOnly, perfil y gestión de cuentas 200; cierre 204 y consulta posterior 401. Solo se revocaron las sesiones creadas por la comprobación.
- Modelos, tres datasets, dashboard y capacidad ZIP: rutas 200. ZIP informa `available=false` en Windows nativo, conservando su requisito de Linux/Docker y workers.
- Interfaz: compilación nueva Turbopack y TypeScript aprobada; HTML de login y archivos CSS/JS responden 200. Se sirve la salida standalone compilada, con proxy hacia 8010. `pip check` pasó sin requisitos rotos.
- Salud backend y `/ready`: 200. La comprobación completa de esquema tardó 30,59 segundos en esta observación; no es una medición de latencia de predicción.
- Perfil, secretos, índices y cinco checkpoints: bytes/huellas conservados. Cuenta, tres datasets, 2607 registros de audio, cinco modelos y 31 predicciones presentes. Las tablas de datos/datasets/predicciones/feedback conservaron sus huellas completas tras los logins y el registro de hashes.

Las pruebas sintéticas de integración del día 24 siguen siendo evidencia histórica; no se presentan como una ejecución nueva. En este mantenimiento no se entrenó, no se emitió una nueva predicción ni se certificó calidad científica o GPU. El Super-Ensamble cargó sus tres checkpoints en el backend; no se ejecutó otra inferencia con persistencia.

## Respaldos y recuperación

| Copia privada | Revisión | Tablas / secuencias |
| --- | --- | --- |
| `backend/installation/cloud-oficial/backups/pre-0004-quiescente-20261025` | 0003_autonomy | 17 / 9 |
| `backend/installation/cloud-oficial/backups/post-0004-20261025` | 0004_integration | 38 / 14 |

Ambas copias se restauraron en bases nuevas de un PostgreSQL 16 local temporal, sin red ni puertos publicados. Cada tabla coincidió por recuento y SHA-256 de todas sus filas; cada secuencia coincidió por valor y estado. Se montaron solamente los archivos SQL privados de solo lectura, que contienen las filas y hashes de autenticación de la base; no se montaron ADC ni secretos de conexión. El contenedor temporal fue retirado y los contenedores ajenos se conservaron.

La referencia local `codex/official-runtime-20261024` conserva el código anterior `aa53e09`. Para volver a él también se necesita restaurar una base compatible con 0003 desde el respaldo previo; cambiar de rama por sí solo no revierte la base. Preparar un destino separado y permisos con el operador, siguiendo [respaldo y restauración](respaldo_y_restauracion_postgresql.md). No se ensayó una restauración destructiva sobre la base activa ni PITR administrado de Cloud SQL. Retención y copia SQL fuera de este equipo siguen pendientes.

Los dumps, perfiles y material de mantenimiento están protegidos y excluidos de Git y del contexto Docker. Los recibos públicos contienen huellas y resultados, nunca las filas, contraseñas, cookies o tokens.

## Arranque y próximos pasos

El registro privado `runtime/oficial/run-last.json` identifica los procesos, logs, versión y compilación de esta ejecución. El backend se inició con `app.node --config-dir <perfil-oficial-absoluto> serve --port 8010`; el frontend con Node sobre `frontend/.next-oficial-0004/standalone/server.js`, `HOSTNAME=127.0.0.1`, `PORT=3010` y `NODE_ENV=production`. La compilación usa `API_URL=http://127.0.0.1:8010` y se copiaron `public` y `static` al árbol standalone. El proxy requiere el ADC oficial propio de este equipo.

El lanzador público `backend/scripts/iniciar_nodo.ps1` sigue siendo una alternativa de arranque nativo con frontend en desarrollo; no utiliza por defecto esta salida de producción. Antes de reconstruir o iniciar otra versión, comprobar que corresponde al esquema y que no existe otro propietario de los mismos puertos/runtime.

Para Kevin, código integrado y base oficial ya están alineados en 0004. Su equipo sigue necesitando permisos Google, credenciales SQL de aplicación, cuenta web propia, perfil/runtime y archivos; esas piezas no se transfieren mediante GitHub. Windows nativo no habilita los workers ZIP. El despliegue universitario, HTTPS/red y servicio permanente se preparan aparte.
