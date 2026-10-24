# Plan de implementación: Cloud SQL, GCS y primera instalación

**Estado vigente — 24 de octubre, arranque oficial:** el nodo de `http://localhost:3010` usa `fama_oficial`, `fama-audio-records-2026` y `runtime/oficial`. Perfil completado mediante adopción del administrador histórico, recuperación de contraseña solicitada por el operador e inicio de sesión verificado. Super-Ensamble de aves predeterminado y cinco modelos individuales seleccionables; inferencia real acotada correcta. Los cinco audios históricos diferentes están versionados en GCS, con 1205 filas conservadas en el índice; catálogo SQL de 1220 objetos de aves, 1386 de motores y un audio histórico industrial. Pesos respaldados por contenido y verificados. Los contadores globales ahora recorren todo el bucket: 2646 objetos observados. Siguen pesos del ensamble industrial, respaldo SQL externo/retención y despliegue universitario con HTTPS y servicio estable. [Estado operativo y límites](conciliacion_catalogo_y_pesos_oficiales.md), [recibo actual](../receipts/catalogo_oficial_publicado_20261024.json). Los bloques inferiores conservan sus cortes históricos.

**Fecha:** 20 de octubre de 2026. **Rama:** `fix/afinamiento-integral`.

**Estado (22 de octubre):** etapas 1–6 verificadas con los alcances de sus recibos. La etapa 7 incorpora el asistente protegido, configuración persistente, comprobaciones SQL/GCS y primer administrador con finalización reanudable. Las regresiones y el recorrido visual usan PostgreSQL desechable y GCS simulado; la instalación remota real sigue pendiente, sin primer administrador ni carga ML. Siguiente etapa: 8, realizar juntos la instalación con los recursos de pruebas preparados y comprobar el reinicio y acceso. Se conserva el proxy nativo; la concurrencia funcional completa, el stack ML y la operación institucional mantienen sus etapas posteriores.

## Alcance y reparto de responsabilidades

**Relevo vigente del 24 de octubre:** El operador trasladó la historia a `fama_oficial` y Codex confirmó igualdad de todos los campos y siete secuencias: 41 filas, cuenta/hash intactos, cinco modelos y 31 predicciones. El respaldo PostgreSQL 16 posterior también se restauró y verificó en un laboratorio retirado. `runtime/oficial` ya está vinculado al perfil: cinco pesos y un audio copiados con SHA-256 coincidente, sin datos de prueba; los cinco modelos cargan tras corregir el lector AudioCNN histórico. Hay un índice candidato privado de 1205 filas: 1200 audios coinciden con GCS por MD5/tamaño y cinco requieren elegir tratamiento. El operador confirmó las dos preferencias; siguen publicación/catálogo, audios, adopción y arranque; el perfil no está activado. [Estado y decisiones](conciliacion_catalogo_y_pesos_oficiales.md), [recibo](../receipts/traslado_historia_confirmado_y_pesos_20261024.json). Los apartados inferiores conservan sus cortes históricos.

**Relevo posterior del 24 de octubre:** contraseñas SQL oficiales asignadas según el operador; comprobador local de logins/privilegios listo con 22 PASS en PostgreSQL temporal, proxy correcto cotejado. Sigue ejecutarlo con entrada oculta en el PC y después preparar identidad técnica/perfil y traslado de historia. [Comando y límites](preparacion_entorno_oficial.md#siguiente-paso-comprobar-acceso-desde-este-pc). Los relevos inferiores conservan sus cortes.

**Relevo del 24 de octubre:** el operador confirmó ejecución de roles en `fama_oficial`, aplicación sin CREATE y migrador con CREATE; ambos usuarios observados por API. Sigue asignar contraseñas SQL y comprobar conexiones/permisos antes de preparar el perfil oficial y trasladar historia. [Paso actual](preparacion_entorno_oficial.md#siguiente-paso-asignar-contraseñas-sql). Los relevos del 23 mantienen su fecha y alcance.

**Destino confirmado el 23 de octubre:** primero este PC con acceso local; después servidor de la universidad. El operador eligió la instancia Cloud SQL actual con base oficial separada; Codex creó `fama_oficial` y verificó que `fama_pruebas` sigue presente. Inventario histórico y conversor Windows comprobados; script de roles oficiales listo con ocho pruebas PostgreSQL. Sigue ejecutarlo en Cloud SQL Studio con `postgres`, asignar contraseñas y preparar perfil/migración de historia. Hay una base histórica PostgreSQL 18 local sin Alembic y diferencias entre catálogos; no se trasladó historia ni se cambió el perfil. [Preparación oficial y paso inmediato](preparacion_entorno_oficial.md). Este relevo actualiza equipo/acceso e inventario; los estados fechados inferiores conservan sus cortes.

La instalación institucional tendrá frontend, backend y cómputo en el nodo local; PostgreSQL en Cloud SQL y archivos publicados en GCS. El disco local seguirá alojando caché y archivos de procesamiento. PostgreSQL local se conserva para desarrollo y pruebas.

El responsable de la instalación configura los recursos de GCP una vez por instalación. Los investigadores utilizan después sus cuentas de F.A.M.A. y sus asignaciones. Son identidades distintas: usuario web, identidad técnica de Google Cloud y usuario de PostgreSQL.

En la primera versión, el asistente conectará una instancia, una base y un bucket existentes. El aprovisionamiento de infraestructura se hará previamente en GCP. La transferencia de datos actuales será una etapa posterior y separada de instalar sobre una base vacía.

En este plan, **tú** significa el responsable humano de GCP y del equipo institucional; **yo** significa el trabajo de desarrollo de Codex. Las operaciones reales se ejecutarán sobre los destinos que se identifiquen expresamente al llegar a su etapa.

## Etapas, en orden

| Etapa | Responsable principal | Entrega y condición para avanzar |
| --- | --- | --- |
| 1. Preparar configuración y migraciones | Yo | Código probado con PostgreSQL local, capaz de iniciar en modo instalación y de comprobar el esquema sin crear tablas al importar módulos. |
| 2. Preparar proyecto y acceso a GCP | Tú | Proyecto identificado, APIs habilitadas, región y presupuesto revisados, equipo desde el que se operará definido. |
| 3. Crear o reservar recursos de prueba | Tú | Instancia/base PostgreSQL y bucket de pruebas disponibles, con sus identificadores anotados. |
| 4. Configurar identidades, permisos y red | Tú, con mis instrucciones | Identidad técnica y usuario SQL preparados; el nodo puede alcanzar la instancia mediante el método acordado. |
| 5. Integrar conexiones reales | Yo | Backend configurable, proxy y arranque nativo/Docker preparados; comprobaciones SQL y GCS separadas y con errores comprensibles. |
| 6. Preparar y comprobar la base remota | Tú ejecutas los scripts que preparo; yo verifico resultados | Migraciones aplicadas a la base de pruebas, permisos comprobados y pruebas de integración reales registradas. |
| 7. Implementar el asistente | Yo | Recorrido web protegido y persistente para configurar, verificar y crear el primer administrador. |
| 8. Validar una instalación completa | Ambos | Instalación desde cero, reinicio, fallos y reintentos comprobados con cuentas y archivos de prueba. |
| 9. Preparar la operación institucional | Yo preparo; tú configuras el entorno final | HTTPS, secretos, copias/restauración, recuperación de emergencia y acceso al nodo preparados. |
| 10. Migrar datos existentes y poner en servicio | Ambos, sobre destinos acordados | Corte controlado, comprobación del recorrido funcional y posibilidad de recuperar el entorno anterior. |

### 1. Yo: preparar el código antes de contratar o activar nuevos recursos

- Centralizar la configuración de base de datos, bucket, autenticación y estado de instalación; retirar dependencias de nombres personales y rutas fijas del entorno actual.
- Separar el arranque de instalación del arranque normal. La instalación debe poder abrirse antes de configurar Cloud SQL; los modelos y workers funcionales comenzarán cuando corresponda.
- Guardar el estado inicial en un volumen o ubicación persistente del servidor. Los secretos tendrán almacenamiento protegido y no formarán parte de respuestas públicas, logs, código fuente ni almacenamiento del navegador.
- Preparar migraciones versionadas para las tablas actuales y las de acceso. Probar una base vacía y una actualización compatible; detectar un esquema desconocido sin asumir que está actualizado.
- Evitar DDL por importación y definir la ejecución explícita de migraciones. Separar los permisos para migrar de los del usuario que ejecuta la aplicación diariamente.
- Preparar pruebas de conexión con tiempos de espera acotados y pruebas mediante interfaces públicas. Registrar la decisión arquitectónica definitiva antes de implementar los cambios estructurales.

Para probar PostgreSQL local será necesario tener Docker o un servidor PostgreSQL de pruebas disponible en el equipo. Tú pondrás ese entorno a disposición cuando corresponda; yo prepararé los comandos y las comprobaciones.

**Cierre:** pruebas aisladas y PostgreSQL local aprobados; todavía no se modifica GCP ni la base actual.

**Realizado el 21 de octubre:** configuración central y referencias a secretos, registro persistente, entrada `main:app` previa a SQL/ML, revisiones `0001_core`/`0002_access`, CLI explícita y rechazo de esquemas desconocidos. PostgreSQL 16.15 temporal: migración vacía, conservación de cuenta al actualizar, permisos DML sin DDL y arranque/login/logout desde copia de código sin artefactos reales. Comprobación final: **34 PASS**, más **149 PASS** de regresión aislada. Contenedor temporal retirado. [Guía de operación](preparacion_instalacion_y_migraciones.md) y [recibo reproducible](../receipts/instalacion_etapa1_postgresql_20261021.json). El asistente visual y su finalización protegida siguen en la etapa 7.

### 2. Tú: preparar el proyecto en GCP

1. Elegir el proyecto y comprobar si ya dispone de bucket o instancia aprovechables. Un recurso existente requiere un destino de pruebas claramente separado.
2. Comprobar facturación y definir un presupuesto con alertas. Las alertas informan del gasto; no son un tope automático.
3. Habilitar Cloud SQL Admin API y Cloud Storage API. Si utilizamos suplantación de cuenta de servicio, habilitar también IAM Service Account Credentials API.
4. Elegir la región y la ruta de red desde el nodo local antes de crear la instancia. Para la opción de IP privada, preparar primero el acceso a la VPC correspondiente; para IP pública con proxy, confirmar que la política institucional lo permite. Cuando sea apropiado, ubicar bucket e instancia en la misma región disponible.
5. Confirmar si la prueba se hará en Windows nativo o Docker; la integración deberá funcionar desde el entorno donde se ejecute realmente el backend.

**Cierre:** proyecto, región, modalidad de ejecución y presupuesto identificados.

Referencia: [presupuestos y alertas de Google Cloud](https://docs.cloud.google.com/billing/docs/how-to/budgets).

### 3. Tú: preparar Cloud SQL y GCS de prueba

**Cloud SQL:** crear una instancia de PostgreSQL o reservar una base aislada en una instancia existente. PostgreSQL 16 es el punto de compatibilidad inicial porque Compose utiliza esa versión. Revisar explícitamente edición, CPU, RAM, almacenamiento, copias y estimación de coste en la consola. Crear una base de prueba vacía, por ejemplo `fama_pruebas`, y anotar el nombre de conexión `proyecto:region:instancia`.

**GCS:** crear preferentemente un bucket de pruebas distinto del que contiene los audios actuales. Utilizar acceso uniforme a nivel de bucket y prevención de acceso público. Anotar su nombre exacto, ubicación y política de retención/recuperación.

Los nombres de ejemplo no identifican recursos existentes. El contenido actual del proyecto no se copia ni se elimina durante esta etapa.

**Cierre:** instancia/base y bucket accesibles en la consola, con sus identificadores disponibles.

Referencias: [crear una instancia PostgreSQL](https://docs.cloud.google.com/sql/docs/postgres/create-instance), [crear un bucket](https://docs.cloud.google.com/storage/docs/creating-buckets).

### 4. Tú: identidades, permisos y conectividad

- Crear una identidad técnica para F.A.M.A. o reservar una existente para estas pruebas. Conceder Cloud SQL Client para la conexión mediante proxy, acotando su alcance cuando corresponda.
- Conceder permisos sobre los objetos del bucket de pruebas según las operaciones requeridas. Evaluar Storage Object User para lectura/escritura/borrado; los permisos para consultar metadatos del bucket se revisan por separado. La aplicación no necesita administrar todo el proyecto.
- Preparar un usuario PostgreSQL de aplicación con permisos sobre su base/esquema y una identidad de operador para migraciones. Los permisos IAM del proxy no sustituyen los permisos SQL.
- Configurar autenticación del nodo. Para desarrollo local se propone ADC con suplantación de cuenta de servicio, sujeto a compatibilidad de las bibliotecas y políticas institucionales; requiere permisos de suplantación sobre esa cuenta. En Docker se comprobará que las credenciales estén disponibles dentro del contenedor.
- Comprobar la ruta de red elegida en la etapa 2. Para pruebas desde un PC, IP pública con Cloud SQL Auth Proxy es una opción si la institución la permite. Con IP privada, verificar la ruta VPN/VPC preparada: el proxy no crea conectividad hacia esa red.

Las credenciales se configuran en el equipo autorizado. Para coordinar el trabajo se comparten identificadores y resultados sanitizados, sin pegar contraseñas o claves en el chat.

**Cierre:** identidad técnica, usuario SQL y conectividad preparados para comprobarlos desde el backend.

Referencias: [Cloud SQL Auth Proxy](https://docs.cloud.google.com/sql/docs/postgres/connect-auth-proxy), [roles de Cloud Storage](https://docs.cloud.google.com/storage/docs/access-control/iam-roles), [ADC local y suplantación](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment), [usuarios PostgreSQL](https://docs.cloud.google.com/sql/docs/postgres/create-manage-users).

**Avance del 22 de octubre:** proyecto `proyectotesis-fama` (número `551538268021`), instancia `proyectotesis-fama:us-central1:fama-postgres-pruebas`, PostgreSQL 16, IP pública y CA `GOOGLE_MANAGED_CAS_CA`; base `fama_pruebas`, bucket de pruebas `fama-pruebas` e identidad `fama-pruebas-app@proyectotesis-fama.iam.gserviceaccount.com`. El operador confirmó `fama_pruebas`/`postgres` mediante una consulta de lectura en Studio. La autenticación local se conserva en `backend/credentials/gcloud-pruebas`, excluida de Git y de la imagen, mediante ADC de suplantación. Se observaron listado GCS correcto y HTTP 200 de `connectSettings` tras habilitar Cloud SQL Admin API. No se modificó `fama-audio-records-2026` ni se aplicaron migraciones remotas. El operador ejecutó el [script de usuarios SQL](usuarios_postgresql_pruebas.md): su captura confirma `fama_app` y `fama_migrador`, sin superusuario/creación de bases o roles y con creación en `public` solo para el migrador. Confirmó después la asignación de sus contraseñas. Se descargó el proxy oficial 2.26.2, se comprobó su SHA-256 y se inició en loopback; `--run-connection-test` informó `Connection test passed`. Finalmente el operador mostró `fama_pruebas`/`fama_migrador` y `fama_pruebas`/`fama_app` desde el terminal local: autenticación SQL nativa confirmada, con consultas de lectura. Los permisos sobre tablas quedan para después de las migraciones.

### 5. Yo: integrar el backend y los lanzadores

- Implementar configuración de Cloud SQL mediante proxy, conservando el acceso SQLAlchemy/PostgreSQL compatible con el proyecto.
- Para ejecución nativa, enlazar el proxy a loopback y elegir un puerto libre. Para Docker, comunicar backend y proxy por su red interna sin publicar el puerto SQL hacia el exterior.
- Adaptar Compose para seleccionar PostgreSQL local o Cloud SQL y retirar la dependencia obligatoria del contenedor `db` cuando se utilice la nube.
- Comprobar SQL y GCS por separado. Empezar por una consulta SQL mínima y operaciones de almacenamiento de prueba; mostrar qué conexión falla.
- Mantener la configuración institucional independiente de la salud actual de los servicios. Una caída de Cloud SQL o GCS no reabrirá el asistente ni cambiará la aplicación a otra base de datos.

**Cierre:** conexión desde el entorno real del backend comprobada; fallos de autenticación, red y permisos distinguibles sin revelar secretos.

**Implementación y validación del 22 de octubre:** CLI `app.node prepare/check/serve`, diagnóstico `app.connections` y variante `docker-compose.cloud.yml` preparados. Se protege el directorio privado en Windows/POSIX, se conservan secretos mediante referencias y se evita heredar la base local al seleccionar nube. Regresión acotada previa: **50 PASS/ocho archivos** (82,09 s), con PostgreSQL local efímero. Las comprobaciones iniciales Windows/Linux combinaron SQL local con listado GCS real, antes de verificar la configuración remota indicada a continuación. [Manual de conexiones](conexiones_cloud_sql_y_gcs.md), [ADR 0041](../adr/0041-conexiones-cloud-explicitas-mediante-proxy.md) y [recibo](../receipts/instalacion_etapa5_conexiones_20261022.json). Los registros preparados siguen sin finalizar: el asistente de etapa 7 conserva esa responsabilidad.

**Cierre posterior de conexiones, 22 de octubre:** el operador obtuvo `configuration_prepared` con la contraseña real de `fama_app`. El diagnóstico devolvió `database_connected` y `storage_read_connected` tanto desde Windows como desde la imagen Linux mínima, utilizando Cloud SQL y `fama-pruebas` reales. La variante Compose selecciona proxy/backend/frontend sin `db`. La comprobación SQL de lectura confirmó base `fama_pruebas`, usuario `fama_app` y `schema_empty`. La nueva red y el proxy Docker temporales se retiraron tras cotejar identidad y etiquetas. Se pasa a la preparación de las migraciones; las escrituras remotas, permisos DML y stack ML completo aún no se han comprobado.

### 6. Ambos: migraciones e integración en los recursos de prueba

Yo entregaré los scripts y su comprobación previa. Tú los ejecutarás en la base de pruebas identificada; revisaremos conjuntamente las salidas sanitizadas.

1. Confirmar destino, versión y estado del esquema; preparar la recuperación o recreación del entorno de prueba según corresponda.
2. Aplicar las migraciones con la identidad del operador. El usuario normal de aplicación debe poder operar después sin permisos de migración.
3. Verificar persistencia, transacciones y los casos de concurrencia relevantes en PostgreSQL; SQLite no sustituye esa evidencia.
4. Probar subida, lectura/listado y descarga de un objeto pequeño en un espacio de pruebas. La retirada posterior se limita a los objetos creados expresamente para esta comprobación.
5. Verificar que reiniciar el backend conserva datos y configuración, y que un fallo de red no produce un éxito ficticio.

**Cierre:** evidencia de conexiones reales, migraciones y operaciones limitadas a los recursos de prueba. No implica que el pipeline ML completo esté validado.

**Cierre del 22 de octubre:** el operador ejecutó migración y `permisos_tablas_pruebas.sql`. Desde la configuración privada de `fama_app` se comprobó revisión y estructura `0002_access`, DML en las 15 tablas, versión en solo lectura, USAGE/SELECT sin UPDATE en 9 secuencias y ausencia de privilegios del migrador. CRUD sintético con rollback y una inserción con commit/lectura desde otra transacción se limpiaron verificando cero filas de prueba; no se avanzaron secuencias. En `fama-pruebas` se subió, listó, descargó y borró la generación propia de un texto de 39 bytes, con ausencia de objeto vivo confirmada. Dos arranques ASGI aislados conservaron la instalación pendiente, sin ML. La regresión local previa de permisos/roles/migraciones obtuvo **25 PASS/tres archivos** (73,58 s); esto no acredita todavía concurrencia web ni el stack ML remoto completo. [Manual de permisos](permisos_aplicacion_postgresql.md) y [recibo](../receipts/instalacion_etapa6_permisos_20261022.json).

La concurrencia SQL se comprobó además con dos conexiones reales sobre una fila sintética: la segunda escritura agotó su espera de bloqueo de 250 ms, y el reintento posterior conservó ambos incrementos. Se retiró la fila y se confirmó su ausencia. Esta comprobación se limita al bloqueo de fila PostgreSQL; la concurrencia funcional de autenticación y operaciones web permanece en la validación posterior al asistente.

### 7. Yo: construir el asistente de primera instalación

Recorrido implementado: **requisitos → PostgreSQL → GCS → comprobación del esquema y permisos → primer administrador → finalizar**.

- Proteger la entrada mediante prueba de control del nodo durante la instalación; no depender de una cuenta web que todavía no existe.
- Solicitar identificadores de recursos existentes y el método de conexión. Las credenciales se manejarán por el mecanismo del servidor definido en la etapa 1.
- Verificar que las migraciones ya se aplicaron. En esta primera versión, las migraciones privilegiadas se ejecutan con los scripts del operador de la etapa 6; la aplicación no conserva esas credenciales.
- Crear el primer administrador y finalizar de forma reanudable e idempotente. Si se interrumpe entre una escritura SQL y el guardado del estado del nodo, el reintento no debe duplicar cuentas ni permitir tomar una instalación existente.
- Bloquear la primera instalación tras completarla. Una indisponibilidad posterior de GCP se presenta como fallo de operación y no como una instalación nueva.
- Mantener el estilo de las vistas existentes. Probar formularios, estados, permisos y respuestas HTTP mediante las interfaces públicas acordadas.

**Cierre:** asistente probado localmente y listo para una instalación completa sobre recursos de prueba nuevos o reinicializados expresamente.

**Realizado el 22 de octubre:** autorización del operador de 15 minutos vinculada al origen; configuración privada y pasos visuales con los estilos existentes. Comprobaciones separadas de conexión, lectura GCS, esquema, permisos diarios, opciones de acceso y base disponible. Creación de cuenta y auditoría en una transacción, intención privada y bloqueo entre procesos/nodos para reanudar sin duplicar ni adoptar cuentas. Cierre permanente y reinicio explícito del backend. Recorrido visual completo sobre una base temporal independiente; ninguna cuenta real creada. [Manual de uso](asistente_primera_instalacion.md), [ADR 0042](../adr/0042-autorizacion-y-finalizacion-reanudable-de-instalacion.md) y [evidencia de pruebas y límites](../receipts/instalacion_etapa7_asistente_20261022.json).

### 8. Ambos: probar la experiencia completa de instalación

**En curso desde el 22 de octubre:** [bitácora del operador y Codex](bitacora_acceso_e_instalacion.md) consolidada y diagnóstico nativo SQL/GCS de lectura correcto; esquema actual y 15 tablas de aplicación vacías en el preflight previo al alta. Pantalla de autorización comprobada en `http://localhost:3010/installation`, con backend en loopback 8010 y servicios existentes conservados. El operador confirmó la autorización, con respuestas protegidas de estado HTTP 200; PostgreSQL ya fue guardado (HTTP 200 y avance visual a GCS). El bucket ya fue guardado y las seis comprobaciones muestran **Correcto** (captura del operador y HTTP 200); primera cuenta y cierre ya verificados, backend reiniciado con health/ready 200 y asistente cerrado. Login administrador verificado (interfaz, HTTP y sesión/auditoría persistidas). Mi cuenta, cuentas y auditoría revisadas en lectura; investigador de prueba ya creado por el operador y persistencia/auditoría verificadas. Cambio a investigador verificado: logout, rol visible y GET administrativos 403; sin datasets asignados. Cambio de contraseña/revocación y nuevo login investigador verificados. E8-01 de predicciones ficticias corregida con TDD y 308 pruebas frontend, TypeScript/ESLint y navegador. Sesión administradora restaurada; enlace de recuperación emitido por el operador y verificado con HTTP 200, un registro vigente y auditoría. Consumo verificado tras cerrar sesión administradora: HTTP 204, cero filas de recuperación y auditoría. Reutilización rechazada con HTTP 400 y sin un segundo evento de recuperación correcto. Login investigador con contraseña recuperada verificado con HTTP 200, rol visible y una sesión vigente. Catálogo SQL: cero datasets y asignaciones. El operador ya volvió al administrador y tiene abierta **Gestión de audios** (ingesta), según rol y encabezado observados. Quedan revisión del catálogo y elección de activos acotados. Siguen asignaciones y recorrido funcional. Los datos de la cuenta y contraseña los introducirá localmente; el avance y sus resultados se registran por paso en el [recibo de etapa 8](../receipts/instalacion_etapa8_validacion_20261022.json). Actualización del 23 de octubre: E8-02/E8-03 corregidas en código y pruebas aisladas; subida visual, incorporación SQL con autoría y catálogo/solicitudes implementados. Pendiente migración remota 0003_autonomy por el operador, actualización de procesos y recorrido real acotado. No se transfirieron audios reales. Ver el manual de autonomía y el recibo de implementación.

**Política definida por el operador:** autonomía de uso, carga, corrección e incorporación para datasets asignados; solicitudes de acceso decididas por administración. Sin permiso adicional de curador ni moderación administrativa obligatoria. [ADR 0043](../adr/0043-autonomia-investigadora-en-datasets-asignados.md) y [plan de ajustes](plan_autonomia_investigador_y_catalogo.md). Los puntos 1–4 están implementados en código y comprobados con servicios aislados. La [activación controlada de autonomía](autonomia_y_solicitudes_datasets.md) requiere la migración remota del operador y la actualización de procesos; después sigue la verificación real. Etapa 8 abierta.

Tú recorrerás el asistente con los datos de prueba; yo corregiré y verificaré los comportamientos observados.

Comprobaremos conexión errónea, credenciales insuficientes, esquema incompatible, interrupción/reanudación, doble finalización, reinicio y rechazo de reapertura del asistente. Después: ingreso del administrador, creación de investigador, asignación de recursos, expiración/cierre de sesión y recuperación administrada.

Finalmente se probará el recorrido ingesta → entrenamiento acotado → checkpoint/modelo → predicción → feedback con los audios, pesos y recursos elegidos para esa prueba. Requiere disponer de artefactos compatibles y resolver los defectos funcionales que ese recorrido revele.

**Cierre:** evidencia del recorrido observado y lista explícita de incidencias restantes.

**Actualización vigente del 23 de octubre:** migración `0003_autonomy`, login de 120 segundos, solicitud/aprobación y Recorrido investigador acotado verificado: acceso concedido por el operador, descarga y preprocesamiento de diez audios, entrenamiento de una época/lote dos, predicción, corrección propia e incorporación SQL/GCS. La carga investigadora de un audio idéntico se omitió sin duplicarlo. El dataset tiene ahora once audios: diez MP3 originales y una copia WAV derivada para la prueba, no una observación independiente. El modelo quedó inactivo globalmente y su checkpoint solo está respaldado localmente. Siguen E8-04 (discrepancia MP3 disco/memoria), un rótulo del gráfico individual que aún puede indicar «Punto 1/10» pese a ejecutar 1/1, y la operación institucional de etapas 9–10. La prueba no acredita calidad científica, independencia por grabador, recuperación de desastres, GPU ni la suite global. [Bitácora](bitacora_acceso_e_instalacion.md). El párrafo inicial de etapa 8 conserva su corte anterior y no describe el estado actual de migración ni transferencias.

### 9. Ambos: preparar la operación institucional

Yo prepararé configuración de HTTPS/proxy/CORS, secretos y volúmenes persistentes, guía de operación, diagnósticos y recuperación de emergencia del operador. Tú configurarás el dominio o acceso institucional, las credenciales finales, las copias de seguridad y las políticas del proyecto.

Se comprobará una restauración en un destino separado y el procedimiento de recuperación si ningún administrador web puede acceder. Revisar duración de sesiones y retención de auditoría según la institución. Las alertas de gasto y los costes se revisan sobre los recursos concretos elegidos.

**Cierre:** requisitos de operación y recuperación comprobados antes del uso institucional.

Referencia: [copias de Cloud SQL](https://docs.cloud.google.com/sql/docs/postgres/backup-recovery/backups).

### 10. Ambos: trasladar datos existentes y poner en servicio

Si se necesitan datos actuales, preparar un inventario de la base, audios, checkpoints, referencias GCS e identidades. Definir qué se conserva, comprobar procedencias y preparar copia/restauración. El asistente de instalación vacía no es una herramienta de migración de datos históricos.

Yo prepararé los cambios/scripts necesarios y verificaciones de consistencia. Tú confirmarás destinos y ventana operativa; ejecutaremos el corte acordado con comprobaciones y recuperación del entorno anterior. Las credenciales y datos del entorno de prueba se mantendrán separados del institucional.

**Cierre:** cuentas, permisos y recursos correctos en el entorno final y recorrido funcional comprobado. Una caída posterior se gestiona como incidente operativo.

## Información necesaria al llegar a la etapa de conexión

| Dato | Cómo se utilizará |
| --- | --- |
| ID del proyecto y región | Identificar recursos y conectividad. |
| Nombre de conexión de Cloud SQL | Configurar el proxy hacia la instancia correcta. |
| Nombre de base y usuario de aplicación | Configurar PostgreSQL; la contraseña se introduce en el equipo autorizado. |
| Nombre exacto del bucket de pruebas | Restringir las operaciones de almacenamiento al destino acordado. |
| Correo de la cuenta de servicio | Identificar los permisos y la autenticación técnica. |
| Backend nativo o Docker, nodo final y ruta de red | Preparar los lanzadores y la conectividad apropiados. |

**Siguiente paso al 22 de octubre:** etapa 8, abrir el asistente contra el perfil nativo de pruebas, generar localmente la autorización y crear la primera cuenta con el operador. Después, reiniciar el backend y verificar ingreso, administración y recorridos funcionales con los recursos acordados. No se necesita crear más recursos GCP para comenzar.

**Relevo posterior del 23 de octubre:** asistente, cuentas y recorrido investigador acotado ya comprobados en el entorno de pruebas. E8-04/E8-11 quedaron corregidas y activadas localmente, con [evidencia de MP3 y gráfico](validacion_mp3_y_curvas_entrenamiento.md). Antes de ejecutar el corte oficial siguen particiones versionadas desde la aplicación, respaldo/recuperación de checkpoints, directorios persistentes, recuperación administrativa y operación de etapa 9. Las variantes históricas de clase requieren revisión. No se cambió al bucket `fama-audio-records-2026`; su inventario y la planificación del traslado corresponden a etapa 10. Los bloques anteriores conservan su fecha de corte.

**Relevo posterior — particiones completadas el 23 de octubre:** previsualización/publicación/selección verificadas en `FAMA_Prueba_Aves`, con ocho train/dos val, CSV y modelo anteriores intactos. [Manual](particiones_versionadas.md), [recibo](../receipts/particiones_versionadas_20261023.json). El siguiente bloque es respaldar y recuperar checkpoints desde GCS. Siguen directorios persistentes exclusivos, recuperación administrativa, revisión de clases y corte oficial; no se cambió de bucket. Esta actualización sustituye únicamente el pendiente de particiones del corte anterior.

**Relevo posterior — checkpoints, 23 de octubre:** respaldo explícito desde la ficha técnica y recuperación verificada en carpeta separada, con el checkpoint operativo y dieciséis archivos del dataset intactos. [Manual](respaldo_y_recuperacion_checkpoints.md), [recibo](../receipts/respaldo_checkpoints_20261023.json). El siguiente bloque es preparar directorios persistentes exclusivos por entorno; siguen copias/restauración SQL, recuperación del operador y HTTPS/proxy institucional. No se cambió al bucket oficial. El pendiente de respaldo de checkpoints del corte anterior queda cubierto solo en este alcance, sin afirmar recuperación completa del nodo.

**Relevo posterior — persistencia, 23 de octubre:** el nodo nativo de pruebas ya ejecuta las fuentes originales y conserva sus 29 archivos trasladados en `runtime/pruebas`, con hashes iguales, perfil cerrado preservado y bloqueo local exclusivo. Muestra, partición 8/2 y copias del modelo verificadas después del reinicio; SQL conserva doce audios, un modelo inactivo y `0003_autonomy`. [Guía](directorios_persistentes_por_entorno.md), [recibo](../receipts/directorios_persistentes_20261023.json). Sigue copia/restauración de PostgreSQL en un destino separado, recuperación del operador y HTTPS/proxy. La variante Docker solo pasó validación de configuración; el corte institucional y el bucket oficial siguen pendientes. Los relevos anteriores conservan sus fechas de corte.

**Relevo posterior — SQL, 23 de octubre:** respaldo lógico real de `fama_pruebas` y restauración verificada en PostgreSQL 16 local: 17 tablas/nueve secuencias, recuentos y revisión iguales; origen, perfil y 29 archivos preservados. Usuario diario del destino con privilegios limitados comprobado. [Guía](respaldo_y_restauracion_postgresql.md), [recibo](../receipts/respaldo_postgresql_20261023.json). Este ensayo no es restauración administrada/PITR ni una copia fuera del equipo. El siguiente bloque es recuperación de emergencia del operador; después se preparan los recursos/perfil/catálogo oficiales y se cambia a ese perfil con verificación acotada. La política de respaldos, credenciales y HTTPS/red se cierra para el destino final. No se movieron los datos de pruebas al bucket oficial ni se cambió a él. Los cortes anteriores conservan sus fechas.

**Relevo posterior — recuperación del operador, 23 de octubre:** CLI de inspección/recuperación de administradores existentes comprobada con PostgreSQL local, login HTTP y auditoría. Reactivación explícita, revocación selectiva, cuotas preservadas y nueva comprobación del rol después de obtener el gate. La inspección sobre el perfil vigente fue de solo lectura; contraseña y sesiones reales se conservaron. [Guía](recuperacion_emergencia_administrador.md), [recibo](../receipts/recuperacion_emergencia_20261023.json). El siguiente bloque es definir equipo/acceso finales y preparar base, perfil, credenciales y catálogo oficiales; después se cambia a ese perfil y se verifica el recorrido acotado. HTTPS/proxy y política de copias se concretan según el destino. El mecanismo asume control confiable del servidor y sus credenciales SQL; no se distribuyen como permisos web. No se cambió al bucket oficial.
