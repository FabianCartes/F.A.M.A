# Entrega de F.A.M.A. a Kevin

Preparado el 25 de octubre de 2026. Esta guía describe otro PC conectado a la misma base y bucket oficiales. El código y la base están alineados en `0004_integration`. No se han concedido permisos a Kevin ni creado su cuenta mediante esta preparación; falta conocer su correo Google y sistema operativo.

## Lo que prepara Fabián

1. Confirmar el correo Google que usará Kevin y si su equipo tiene Windows o Linux. Ese correo identifica el acceso técnico; la cuenta web de F.A.M.A. se administra por separado.
2. Revisar si ese correo puede impersonar la cuenta `fama-oficial-app@proyectotesis-fama.iam.gserviceaccount.com`. Si falta el permiso, conceder `roles/iam.serviceAccountTokenCreator` únicamente sobre esa cuenta: Google Cloud → IAM y administración → Cuentas de servicio → cuenta oficial → Principales con acceso → Otorgar acceso. El texto de la consola puede variar. La cuenta técnica ya tiene Cloud SQL Client en el proyecto y Storage Object User en el bucket; no se necesita nombrar propietario del proyecto a Kevin. Estos permisos técnicos permiten operar los recursos directamente y son distintos del rol web.
3. En Administración de F.A.M.A., crear una cuenta propia para Kevin. Para tener las mismas opciones de gestión que el administrador actual, debe ser administradora. Si se elige investigador, tendrá su alcance de investigador y requerirá asignaciones. Entregar una contraseña inicial propia y acordar su cambio desde Mi cuenta.
4. Entregar por un canal privado el usuario SQL de aplicación `fama_oficial_app` y su contraseña. Es una credencial distinta a la de la cuenta web. Para el uso diario no se entrega el usuario `postgres` ni el migrador; tampoco se vuelve a ejecutar la migración ya aplicada.
5. Facilitar los pesos y el índice histórico de datos mediante copia controlada o recuperación desde GCS. Los nombres y rutas se indican abajo.

Si se comparten estos destinos, las altas, modificaciones y predicciones de ambos equipos actúan sobre los mismos datos. Para experimentar con cambios de código o de datos, preparar un entorno de desarrollo separado.

## Datos que se pueden enviar directamente

| Dato | Valor |
| --- | --- |
| Repositorio | https://github.com/FabianCartes/F.A.M.A |
| Rama | `fix/afinamiento-integral` |
| Proyecto Google Cloud | `proyectotesis-fama` |
| Nombre de conexión Cloud SQL | `proyectotesis-fama:us-central1:fama-postgres-pruebas` |
| Base | `fama_oficial` |
| Usuario SQL de aplicación | `fama_oficial_app` |
| Bucket | `fama-audio-records-2026` |
| Cuenta de servicio | `fama-oficial-app@proyectotesis-fama.iam.gserviceaccount.com` |
| Revisión requerida | `0004_integration` |
| Web local prevista | `http://localhost:3010` |
| Backend local previsto | `127.0.0.1:8010` |
| Proxy SQL local previsto | `127.0.0.1:5434` |

Los nombres de recursos y el nombre del usuario SQL no son contraseñas. La contraseña SQL y la contraseña inicial web se entregan aparte.

Para conservar el Super-Ensamble disponible y predeterminado, el perfil persistente de Kevin debe incluir el valor público `FAMA_ENSEMBLES_JSON` siguiente antes de cerrar su preparación:

```json
{"version":1,"enabled":["chilean-birds-ensemble"],"default":"chilean-birds-ensemble"}
```

El comando de preparación crea las claves locales y los archivos de conexión, pero no añade por sí solo esta declaración de ensamble. No copiar `installation.json` de Fabián como perfil listo: contiene referencias absolutas y cierres propios de su equipo.

## Archivos operativos

Los cinco pesos, aproximadamente 493 MB en total, están en `runtime/oficial/checkpoints/`:

- `efficientnet_gpu_pipeline_35e_best.pt`
- `convnext_nano_35e_best.pt`
- `resnet34d_35e_best.pt`
- `augmented_best.pt`
- `baseline_best.pt`

Tienen copias verificadas en `operator_backups/checkpoints/sha256/<huella>.pt` dentro del bucket. Los nombres, SHA-256 y generaciones están en el [recibo de actualización](../receipts/actualizacion_oficial_0004_20261025.json). Al recuperarlos se conserva su nombre original en la carpeta local de checkpoints y se comprueba el hash; descargar un objeto con su nombre SHA-256 sin renombrarlo no reproduce las rutas que espera el catálogo.

Para reproducir el conjunto local de este PC, facilitar los 1205 audios de `runtime/oficial/data/raw/AvesChilenas/` junto con su `metadata.csv`, y el audio local de `MaquinariaMinas`. Como alternativa, Kevin puede descargar los audios del bucket. Debe conservarse el índice histórico de AvesChilenas: su selección de 1205 archivos no equivale a todos los objetos que hay en GCS. El índice también tiene una copia inmutable en `dataset_indices/AvesChilenas/sha256/64f258de5c3b35853c09eb6b3b18c029ed22567f735d1edcd36db6275c8fc768.csv`.

La verificación de este corte encontró cero archivos en `runtime/oficial/data/processed/`; no hay tensores locales que sea necesario entregar. Los tensores futuros se pueden generar por preprocesamiento. Otros datasets, como motores, están disponibles en GCS según sus registros y permisos.

Se transfieren los archivos de audio, CSV y checkpoints necesarios. Las carpetas de logs, bloqueos, marcadores de runtime e intenciones de trabajos no forman parte del paquete de datos para otro PC. La raíz de almacenamiento de Kevin se prepara primero vacía y con su ruta propia.

## Lo que hace Kevin en su equipo

1. Descargar la rama y preparar Python 3.12, Node.js y las dependencias del repositorio. Instalar Google Cloud CLI y Cloud SQL Auth Proxy. Si necesita workers ZIP, usar el entorno Linux/Docker; Windows nativo mantiene esa capacidad deshabilitada.
2. Iniciar sesión con su propia cuenta Google y generar un ADC local impersonando la cuenta autorizada. El comando de referencia, una vez concedido el permiso, es:

   ```text
   gcloud auth application-default login --impersonate-service-account=fama-oficial-app@proyectotesis-fama.iam.gserviceaccount.com --disable-quota-project --project=proyectotesis-fama
   ```

   Proteger el archivo `application_default_credentials.json` que genere su equipo. No recibir el ADC de Fabián ni iniciar sesión con la cuenta personal de Fabián.
3. Preparar su perfil mediante `app.node prepare`, usando esos destinos, su propio ADC y la contraseña del usuario SQL de aplicación introducida localmente. El comando pide la contraseña sin eco y genera las claves de su nodo. Preparar las rutas según su sistema operativo y añadir la declaración del ensamble.
4. Iniciar el proxy con su ADC en loopback 5434 y preparar una raíz propia con `app.node runtime --directory`. Transferir a esa raíz los datos y pesos verificados.
5. Completar la vinculación local a la base ya existente mediante el procedimiento de [adopción de administrador existente](traslado_historia_y_adopcion.md#adopción-local-posterior-al-traslado-y-a-preparar-archivos). No crear otra primera cuenta ni trasladar/copiar la base que ya contiene la historia. La preparación local se verifica con un administrador activo existente; no es otra migración SQL.
6. Arrancar backend y frontend con origen `http://localhost:3010` y proxy web a 8010. Iniciar sesión con su cuenta propia y comprobar disponibilidad, datasets y modelos. Con rol administrador y los cinco pesos correctos, se esperan seis opciones: Super-Ensamble y cinco individuales.

Los comandos finales de rutas y arranque deben prepararse después de confirmar el sistema operativo y la ubicación elegida por Kevin. No ejecutar literalmente rutas `C:/Users/fabia/...` en otro equipo.

## Material que permanece en el PC del operador

El ADC del operador, sus secretos/JWT/claves de límites, contraseña administradora personal, carpetas completas `backend/credentials/` y `backend/installation/`, `.env`, dumps SQL, `.venv`, `node_modules` y compilaciones `.next-*` no se entregan como configuración portable. Kevin genera autenticación, secretos, dependencias y compilación propios. Para compartir la misma base no necesita recibir un dump.

## Fuentes y límites

- [ADC local e impersonación, documentación de Google](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment?hl=en).
- [Permisos de impersonación](https://docs.cloud.google.com/docs/authentication/use-service-account-impersonation).
- [Requisitos del Cloud SQL Auth Proxy](https://docs.cloud.google.com/sql/docs/postgres/sql-proxy).
- [Estado oficial aplicado y recuperación](actualizacion_oficial_0004_20261025.md).

Esta guía y el inventario local están preparados. No acreditan que Kevin ya tenga permisos, programas instalados o un nodo funcionando; esas comprobaciones se realizan en su equipo. No se ha enviado ninguna contraseña ni archivo privado mediante esta preparación.
