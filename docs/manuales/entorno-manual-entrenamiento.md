# Entorno principal del MVP: base conectada y acceso local

Por autorización expresa del usuario, `fama_training_dev_20261105153618`, ya conectada a la interfaz, es ahora el **entorno principal de iteración del MVP**. No se creó otra base ni se modificó la base anterior del contenedor `fama-db`.

Los cambios de feedback y preparación están desplegados en la API conectada; la UI recibe el aviso de preparación obsoleta. **Esto no acredita el recorrido ML completo. El worker ZIP ahora está activo en el host con el sandbox intacto y la misma BD; GCS todavía no está configurado en esta API.** Véase [operación del worker](worker-importacion-zip-local.md).

## Acceso rápido

| Recurso | Acceso |
| --- | --- |
| Interfaz local | `http://127.0.0.1:3000` — usar esta dirección exacta, no `localhost` |
| Base principal del MVP (nombre conservado) | `fama_training_dev_20261105153618` |
| Contenedor PostgreSQL | `fama-admin-persistent-9c4b15c847a23b49-db` |
| Contenedor API | `fama-manual-dev-44938bc83ad0184c-api` |
| Cuenta de aplicación | Investigador de prueba; credenciales en el archivo privado indicado abajo |
| Estado observado | [Recibo actual](../receipts/training-manual-development-current.json) |

Desde la raíz del proyecto, abrir localmente `.training-manual-44938bc83ad0184c/login.json` para consultar el correo y la contraseña generados. No copiar su contenido a incidencias, chats o commits. La contraseña del usuario no es la del rol PostgreSQL.

La interfaz usa sesión web del mismo origen. `API_URL` dirige el proxy de Next.js a la dirección privada del contenedor; `NEXT_PUBLIC_API_URL` permanece vacío. La API conserva autenticación, Origin y límites de acceso.

## Despliegue activo y recuperación

- API actual: `fama-manual-dev-44938bc83ad0184c-api`, imagen `fama-connected-mvp:b4173ae70a799fd1-ownership`; mantiene IP privada `172.23.0.3` para el proxy de Next.js.
- Imagen construida sobre la anterior, sin red ni cambios de dependencias; 119 archivos Python del checkout incorporados. [Recibo del despliegue](../receipts/connected-mvp-deployment.json) y [cambio de UI](../receipts/connected-mvp-frontend.json).
- Respaldo privado: `.mvp-deploy-b4173ae70a799fd1/database-before.dump`, catálogo validado con `pg_restore --list`; no se hizo restauración ni se creó otra base. SHA-256: `ee43d7e5b46e2a75e03d7f0a36338e65bafb29f516bc6b620a8ddf7e3d030cc9`.
- Contenedor anterior conservado **detenido y desconectado**, con sufijo `-before-b4173ae70a799fd1`. No iniciarlo simultáneamente ni eliminarlo para recuperar espacio por rutina.
- `/app/data` y `/app/checkpoints` se copiaron antes de detener la API anterior y ahora usan carpetas persistentes privadas del despliegue. Imports/snapshots/preparaciones conservan su montaje `/runtime` anterior. No usar limpieza ni borrar esas carpetas.
- La cuenta existente recibió DML acotado para predicción, feedback, snapshots y resultados de entrenamiento, más sus secuencias; se preservó el ACL anterior y no se concedieron superusuario, `CREATE`, `TEMP` ni administración de roles.
- Recuperar la versión anterior requiere una parada controlada de la API actual, liberar su IP y conectar la anterior, **reponiendo antes sus datos/checkpoints desde las copias persistentes**: su tmpfs original no sobrevive a la parada. No basta con `docker start` del contenedor antiguo. No restaurar el dump sobre datos posteriores sin autorización expresa.

El primer arranque de la nueva imagen falló por propiedad de archivos del contexto privado; se corrigió con `COPY --chown=1000:1000`. Se mantuvieron usuario no-root, raíz de solo lectura, capabilities eliminadas, `no-new-privileges` y red interna. El contenedor de ese intento fallido también se conservó; no está activo.

## Administrar la base

```bash
docker --host unix:///var/run/docker.sock exec -it \
  fama-admin-persistent-9c4b15c847a23b49-db \
  psql -U fama_training_bootstrap -d fama_training_dev_20261105153618
```

Dentro de `psql`:

```sql
SELECT current_database(), current_user;
\dt
\q
```

El acceso administrativo es para la persona que controla Docker en el equipo; no es autenticación administrativa remota. PostgreSQL no publica puerto al host. La aplicación usa `fama_training_app`, con credencial distinta y sin superusuario, CREATE de base/esquema, creación de roles ni TEMP.

**Antes de UPDATE/DELETE/DDL manuales, revisar las filas y respaldar lo necesario.** Cambiar registros directamente no prueba que funcione el recorrido de la interfaz y puede romper sus invariantes. Este manual no prescribe borrar o reinicializar datos.

## Arranque y parada

La base y la API quedan activas para las pruebas humanas. Para detener exclusivamente estos servicios:

```bash
docker --host unix:///var/run/docker.sock stop \
  fama-manual-dev-44938bc83ad0184c-api \
  fama-admin-persistent-9c4b15c847a23b49-db
```

Esto conserva el volumen PostgreSQL y las carpetas privadas; no usar `down -v`, `rm` ni comandos de limpieza. La interfaz iniciada por la sesión del agente permanece como proceso de desarrollo; puede pedirse su parada. Si se inicia desde una terminal propia como se muestra abajo, se detiene con Ctrl+C en esa terminal.

Para arrancar de nuevo los contenedores existentes, sin crear otra base:

```bash
docker --host unix:///var/run/docker.sock start fama-admin-persistent-9c4b15c847a23b49-db
docker --host unix:///var/run/docker.sock exec fama-admin-persistent-9c4b15c847a23b49-db \
  pg_isready -U fama_training_bootstrap -d fama_training_dev_20261105153618
# Continuar solo si pg_isready devuelve éxito.
docker --host unix:///var/run/docker.sock start fama-manual-dev-44938bc83ad0184c-api
```

La red es interna. Aunque se solicitó un binding de API a `127.0.0.1:8000`, Docker no lo materializó en este entorno. **No usar esa URL como prueba de disponibilidad.** Next.js accede a la IP privada de la API (`172.23.0.3`, fija en la red interna). Con el puerto 3000 libre, desde la raíz del proyecto:

```bash
API_IP="$(docker --host unix:///var/run/docker.sock inspect \
  --format '{{(index .NetworkSettings.Networks "fama-admin-persistent-9c4b15c847a23b49-net").IPAddress}}' \
  fama-manual-dev-44938bc83ad0184c-api)"
# Seleccionar la red interna de DB: la API también tiene una red de salida GCS.
# No concatenar las direcciones de todas las redes.
cd .training-manual-44938bc83ad0184c/frontend
env -i PATH="$PATH" HOME="$PWD/../runtime" \
  API_URL="http://$API_IP:8000" NEXT_PUBLIC_API_URL= NEXT_TELEMETRY_DISABLED=1 \
  npm run dev -- --hostname 127.0.0.1 --port 3000 --webpack
```

La UI utiliza una **copia de las fuentes**, sin dotenv, y reutiliza las dependencias locales existentes; no se instalaron paquetes Node. Modificar el checkout original no actualiza automáticamente esta copia. La imagen API también es una instantánea, no un montaje del código vivo.

## Qué probar y qué sigue bloqueado

- Administrar y consultar exclusivamente esta base conectada, elegida como principal del MVP.
- Abrir la interfaz y usar la cuenta de investigador propia del entorno.
- Revisar las vistas y anotar errores concretos, sin interpretar una pantalla disponible como aprobación de todas las funcionalidades.
- La política `isolated` omite bootstrap legacy, precarga de modelos, seed y feedback worker. Los modelos legacy no se cargan automáticamente.
- El worker de importación está **activo como servicio persistente de usuario `fama-zip-worker-connected-large`** en el host (arranca al iniciar sesión), usando la misma BD y carpeta de imports. Su preflight comprobó el validador real bajo `NoNewPrivileges`, con Bubblewrap, seccomp y límites intactos; no se cambió la política Docker. Su modo local procesa preview/confirm, no GCS. El intento antiguo dentro de Docker continúa siendo evidencia histórica de un runtime incompatible, no del estado del worker nuevo.
- El trabajo `47a3ab3adec64dbea026dbd456959dbc` apareció cancelado antes del arranque del worker, con cero intentos; no se reactivó. Se necesita una nueva acción del usuario en la aplicación para comprobar preview/publicación real, sin presentar readiness sintética como importación exitosa.
- Las rutas actuales de entrenamiento, inferencia, feedback y preparación están desplegadas y se habilitaron los permisos de almacenamiento en DB que antes faltaban. No se ha ejecutado entrenamiento ni inferencia real para validar este despliegue.
- No se configuraron credenciales GCS ni salida externa de red; antes de S16, `/api/predict` dependía de subida GCS. El despliegue S16 elimina ese requisito solo para modelos privados importados; el flujo legacy sigue necesitando GCS. Véase el apartado de inferencia privada local. No pulsar sincronización cloud como prueba de salud; el worker de feedback no se inició automáticamente.
- No se reintentó el verificador independiente anterior ni las pruebas no disponibles con SQLite en archivo. La aceptación funcional del usuario sigue pendiente y no equivale a aprobación independiente.

## Evidencia y límites

El padre verificó identidad del clúster/OID antes de habilitar la base. Se conservan los recibos históricos de preparación; el recibo actual registra la activación posterior, sin reescribir aquella evidencia.

La primera comprobación del proxy falló con 500 y la espera de API por loopback terminó en fallo. El diagnóstico comprobó salud interna y acceso desde el host a la IP privada; la configuración de Next.js se corrigió sin abrir red externa a la API. Estos resultados no se presentan como arranque sin incidencias.

La revisión independiente observó el estado anterior a esa corrección y quedó **inconclusa**. No se repitió ni escaló. Consultar el recibo para los resultados posteriores ejecutados por el padre: interfaz 200, proxy sin sesión 401, registro 201, login web 200, identidad investigador 200 y logout 204 vacío. La sesión del smoke quedó cerrada; no se imprimieron cookies ni tokens. No equivalen a aprobación independiente final, prueba de navegador o validación completa del flujo ML.

## Pesos preentrenados de EfficientNet-B0 en caché local

El entorno conectado mantiene la red Docker interna y `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`. Para el modelo `efficientnet_b0`, los pesos oficiales `timm/efficientnet_b0.ra_in1k` se aprovisionan una vez desde el host, no desde el proceso de entrenamiento. No se cambia a entrenamiento desde cero.

La caché persistente privada se monta en `/opt/fama-pretrained-cache` en modo de solo lectura; `HF_HOME` y `HF_HUB_CACHE` apuntan a esa ubicación. Sus directorios tienen modo0700 y los archivos0600, con acceso del UID de la aplicación. No borrar ni mover el directorio del host mientras este entorno lo utilice; al recrear el contenedor deben conservarse el montaje y ambas variables.

Artefacto: `model.safetensors`, revisión `1b5383e5f79cc0f7fc067e372f8f26a5fa73f26a`, 21355344bytes (21,36MB /20,37MiB), SHA256 `d569899762ea9b1384ee07f4af64805cf8caa1c55f9253ebb1080dc40e87a2cd`, contrastado con el identificador LFS publicado por el Hub. Esto verifica coincidencia con la fuente HTTPS, no constituye una auditoría del modelo.

La validación construye el modelo preentrenado para un canal y15clases sin conexión, sin iniciar épocas, crear preparaciones o publicar checkpoints. Otras arquitecturas o variantes pueden requerir otros artefactos y no quedan habilitadas por esta caché. Evidencia y ubicación exacta: `docs/receipts/pretrained-b0-cache.json`; consultar su campo `deployed` antes de asumir integración terminada.

## Pesos preentrenados de ResNet-34d

La caché persistente también incorpora `timm/resnet34d.ra2_in1k`, que es la variante resuelta por `resnet34d` en timm1.0.30 de la API actual. Se descargó únicamente `model.safetensors` de la revisión `a5413743ca8b64733faaab21d68820b410c66acb`:87356926bytes, SHA256 `9caa44ee097e5648e75166ff0286278f55715aa68c6b4f83b788bd7a13362ce7`, cotejados con los metadatos LFS del repositorio oficial. No se descargaron archivos pickle ni código remoto.

Se añadió un repositorio nuevo al mismo montaje de solo lectura, sin sobrescribir EfficientNet-B0, reiniciar la API ni habilitarle red. Se mantienen `HF_HOME`, `HF_HUB_CACHE` y las dos opciones offline descritas arriba. El constructor real cargó los pesos con un canal de entrada y13clases en CPU, sin ejecutar entrenamiento. La comprobación independiente también pasó en la misma imagen, con red deshabilitada y caché de solo lectura: un canal,13clases y21309998parámetros. La evidencia y sus límites están en [el recibo ResNet-34d](../receipts/pretrained-resnet34d-cache.json); no confundir disponibilidad de pesos con entrenamiento terminado o mejor rendimiento.

Para usarla, selecciona **ResNet-34d** en el entrenamiento individual. La preparación debe ser compatible con esa arquitectura: el perfil incluye la arquitectura, por lo que una preparación de EfficientNet-B0 no se reutiliza sin verificar compatibilidad. Conserva los modelos, preparaciones y checkpoints anteriores. Esta comprobación no habilita ensambles, no certifica GPU ni acredita las otras arquitecturas.

## Recuperar el entrenamiento después de recargar

El proceso de entrenamiento vive en el backend: cerrar o recargar la pantalla no lo cancela. La interfaz debe consultar el progreso al abrirse, recuperar el estado y los registros existentes y mantener deshabilitado el inicio mientras no conozca el estado real. Si esa lectura falla, debe mostrar el error y permitir reintentar únicamente la consulta, no iniciar automáticamente otro entrenamiento.

**Detener** solicita una cancelación cooperativa. Una respuesta de aceptación no acredita que el proceso haya terminado: la pantalla debe continuar consultando el progreso hasta recibir un estado final. Los errores HTTP o de la respuesta de detención deben mostrarse; no deben convertirse silenciosamente en una confirmación. Esta corrección de la interfaz no modifica los puntos de cancelación del backend ni garantiza una latencia máxima para detenerlo.

La aceptación manual se realiza sin Playwright: recargar durante una ejecución debe recuperar su progreso sin enviar otro inicio; al solicitar detención deben verse los errores o el estado pendiente hasta la confirmación final. No iniciar un trabajo adicional solo para comprobar una pantalla vacía. El estado efectivo del despliegue debe consultarse en el recibo de entrega correspondiente; este apartado describe el contrato, no demuestra por sí solo que esté desplegado.

## Espera al solicitar el inicio

Tras pulsar Iniciar, el botón queda deshabilitado y atenuado con **«Preparando inicio…»** mientras la solicitud espera respuesta. Para fuentes importadas se muestra **«Verificando la integridad y compatibilidad del dataset. Puede tardar unos segundos.»**: la admisión verifica los audios completos antes de aceptar el entrenamiento. No es un porcentaje ni una indicación de la subfase exacta en cada instante.

Esa espera es distinta de un trabajo activo: una lectura temporal de progreso inactivo no libera la solicitud pendiente y los clics repetidos no generan solicitudes adicionales. Detener solo se muestra para trabajo activo confirmado, no para la espera de admisión. Un error se comunica sin reintentar automáticamente el inicio; si el resultado de red es incierto, comprobar el estado antes de volver a iniciar.

## Temporales de evaluación importada

Después de guardar checkpoint, modelo y métricas, la evaluación materializa copias verificadas de validación y prueba. Estas copias deben ubicarse en el almacenamiento privado del snapshot, no en el `/tmp` global de128MiB. La raíz se mantiene abierta mediante descriptor hasta finalizar el contexto y su limpieza; se conservan las lecturas confinadas y los controles de tamaño y SHA-256. Se requiere espacio libre para ambas particiones más margen operativo. Un error de copia sigue impidiendo evaluar: no se omiten verificaciones ni se publica el modelo.

Para el dataset actual, validación y prueba requieren2681796976bytes. La sonda de materialización y limpieza no ejecuta inferencia ni registra evaluaciones. Consultar `docs/receipts/imported-evaluation-temporary-storage.json` para el estado efectivo del despliegue.

El modelo#2 conservado tras el fallo está inactivo y pendiente de evaluación; no repetir épocas ni activarlo para ocultar el error. El servicio de reevaluación estándar no acredita compatibilidad con la identidad privada importada. La recuperación requiere una ruta validada que mantenga propietario, checkpoint, snapshot y preparación; no ejecutar la CLI estándar sobre este modelo sin demostrar esa compatibilidad y autorizar la operación.

## Modelos privados en Predicción

La pantalla Predicción muestra únicamente los modelos privados de la cuenta autenticada, en el grupo **Mis modelos**. No transforma un modelo en público ni cambia su activación global. Al cerrar o cambiar de sesión se descartan catálogo, selección, informes y resultados locales privados; las respuestas pendientes de la cuenta anterior no deben restaurarlos. Sin sesión no se consulta el catálogo privado.

`GET /api/models?private_only=true` exige autenticación cookie/Bearer y devuelve solo modelos con asociación privada validada del propietario. No incluye el default global ni diagnósticos de publicación que puedan revelar otros modelos; una indisponibilidad de base de datos conserva una respuesta503 genérica. Las consultas existentes sin esa opción conservan su comportamiento; `include_imported=true` sigue combinando los públicos con los privados propios. No usar nombres, IDs ni clases para deducir propiedad.

La selección utiliza la identidad canónica `dataset_name` publicada por el catálogo, sin inventar un dominio por las clases del modelo. La API de predicción conserva su comprobación de propietario. Que el modelo aparezca no acredita una predicción real. El apartado S16 describe la persistencia local de modelos importados; el flujo legacy conserva su dependencia GCS.

El nombre visible del modelo importado debe usar el nombre de su dataset de origen: se obtiene de la procedencia persistida y del dataset del mismo propietario, no de la relación de datasets legacy ni de las clases. No cambia el ID técnico, la arquitectura, los pesos ni el ordinal de presentación `vN`. Si no hay un nombre de origen admisible, no se inventa uno.

Al recuperar el foco o la visibilidad, la aplicación comprueba la sesión y actualiza el catálogo. Confirmar la misma cuenta no debe reiniciar la revisión de sesión ni desmontar la vista privada: se conserva la selección durante la actualización. Un cambio de cuenta, un fallo de comprobación o un cierre de sesión siguen borrando el estado privado. Esto no introduce una caché persistente. Consultar el recibo de la corrección de nombre y foco para distinguir este contrato del despliegue efectivo.


## Historial de entrenamientos importados

La vista de entrenamiento solicita `GET /api/training/history?include_imported=true`
con la sesión vigente. La API conserva el filtro por propietario: un historial
vacío sin esa opción no demuestra ausencia de entrenamientos importados.
El nombre visible del dataset se obtiene de la asociación importada del mismo
propietario; no del identificador o relación legacy. Los modelos pendientes de
evaluación pueden figurar en el historial aunque todavía no estén disponibles
para predicción. Consultar el recibo `docs/receipts/imported-training-history-minimal.json`
para el estado del despliegue; abrir el historial no reentrena ni activa modelos.

## Inferencia privada local sin GCS (S16)

S16 está desplegado en la API/UI conectadas, con evidencia en `docs/receipts/local-inference-no-gcs.json`. Conserva el audio de una predicción importada en el almacenamiento
persistente **del backend**, no en el navegador. No intenta una subida a GCS. El
resultado se confirma en PostgreSQL antes de responder con
`local_audio_saved: true`, `gcp_upload: false` y `cloud_status: deferred`.
La UI muestra **Guardado local · GCS diferido** solo con confirmación local explícita.
Los párrafos anteriores que describen la dependencia GCS son históricos para
modelos importados. El recibo separa despliegue verificado de aceptación humana
pendiente sobre un audio real.

La raíz es el bind persistente privado configurado mediante `FAMA_IMPORT_ROOT`.
Los WAV mantienen propietario, UUID, tamaño y SHA-256 verificables; no se aceptan
rutas proporcionadas por el cliente. Se conserva el límite de100MiB y se necesita
un margen libre adicional de512MiB. No borrar el volumen ni sus audios para
recuperar espacio por rutina.

La predicción no modifica el dataset ni inicia entrenamiento. El usuario revisa
el resultado y su propietario debe aprobarlo explícitamente para incorporarlo al
dataset de origen; se mantienen validación WAV, integridad, cuota y revisión.
Tras una incorporación aprobada, la tabla de datasets disponibles vuelve a consultar
también el catálogo privado: el número de archivos locales refleja el total
confirmado por el servidor, sin sumar uno artificialmente ni modificar el conteo GCS.
Un estado de sincronización pendiente tras aprobar no acredita subida GCS.

Un error tras el commit puede dejar una fila válida y su audio aunque la petición
responda con error. Ante confirmación o cancelación inciertas se conservan los
bytes privados antes que borrar una fuente posiblemente referenciada; también
puede quedar un WAV sin fila. No hay reintento, limpieza, incorporación ni
sincronización automática por ese hecho. La comparación de referencias debe
preceder cualquier limpieza manual. Véase [ADR0056](../adr/0056-audio-local-privado-de-inferencia.md).

La aceptación sobre un audio real y la UI corresponde al usuario. La prueba de
salud, el catálogo y las pruebas sintéticas no equivalen a inferencia real.


## Historial persistente de predicciones privadas

La implementación del checkout consulta los registros existentes del modelo importado
privado seleccionado. Su disponibilidad en el entorno servido requiere desplegar tanto
la nueva ruta de API como los archivos frontend; editar este checkout no lo despliega.

- Se carga al entrar en Predicción y al cambiar de modelo; se actualiza tras una
  inferencia local confirmada. Muestra fecha, archivo, clase y confianza originales.
- Cada página contiene hasta 20 registros, en orden descendente de creación
  (ID de predicción). **Cargar más predicciones** recupera páginas anteriores.
  Los filtros de archivo/clase se aplican solo a los registros cargados.
- No incluye estados de revisión, audios ni nuevas copias. No modifica etiquetas
  originales cuando se revisa una predicción ni incorpora registros al dataset.
- Solo se muestran referencias locales canónicas vinculadas al usuario autenticado,
  con modelo y dataset importado coherentes. Un historial vacío no demuestra ausencia
  de predicciones públicas, legacy o sin atribución verificable: estas quedan excluidas.
- La consulta valida la identidad de la referencia escrita por el servidor, no vuelve
  a leer ni a calcular el hash de cada audio para mostrar metadatos históricos.

### API de consulta

`GET /api/inference/history?model_id=fama_trained_model_N&limit=20&cursor=ID`
requiere sesión. También acepta el ID numérico del modelo importado. `limit` está
entre 1 y 20; `cursor` es opcional y positivo. La respuesta contiene `items` con
`id`, `filename`, `timestamp`, `clase`, `confianza`, `modelo_id`, y `next_cursor`
(nulo al terminar). Un modelo ajeno, inexistente o no importado devuelve 404;
sin autenticación devuelve 401; parámetros fuera de rango devuelven 422.

Cada consulta examina como máximo 200 candidatos. Si una ventana contiene
referencias antiguas inválidas, puede devolver pocos registros o ninguno con un
cursor de continuación. El consumidor debe seguir ese cursor, no interpretar
una página vacía como fin del historial. La ruta no devuelve ubicaciones internas
ni permite consultar otra cuenta mediante parámetros.

Evidencia y estado de despliegue: `docs/receipts/private-prediction-history.json`.


### Despliegue verificado del historial privado

El recibo `docs/receipts/private-prediction-history.json` confirma el despliegue
HTTP en el entorno conectado de desarrollo, incluida autenticación mediante la
cookie de sesión existente. La ruta reutiliza el resolutor de identidad de los
recursos importados: no añade excepciones para credenciales inválidas o conflictivas.
En el smoke, v3 tenía una predicción atribuible y v4 ninguna. Seleccionar v4 no
muestra los registros de v3; no es necesario repetir una predicción para recuperar
un registro existente de v3. La aceptación visual queda a cargo del usuario.

El respaldo se validó mediante su catálogo y hash; no se realizó un ensayo de
restauración. Los datos de negocio, checkpoints y audios privados no cambiaron;
solo avanzó `usuario.ultimo_acceso` por el login de comprobación. Los fallos
intermedios del primer smoke401 y de la identidad de usuario del probe aislado
quedan documentados en el recibo. Esto no acredita preparación para producción,
GCS, lint ni una compilación frontend de producción.
