# Entrega de F.A.M.A. a Kevin

Actualizado el 4 de noviembre de 2026. Esta guía describe otro PC conectado a la misma base y bucket oficiales. El código y la base están alineados en `0004_integration`. El operador confirmó que Kevin usa Linux y el correo `kevcardenas675@gmail.com`, y que ya tiene índice, audios y modelos.

La cuenta web de Kevin está creada y activa como administradora, ID **2**. Login, consulta de sesión y acceso a Administración comprobados por HTTP; las sesiones de prueba se cerraron. Su permiso `roles/iam.serviceAccountTokenCreator` se añadió y comprobó únicamente sobre `fama-oficial-app@proyectotesis-fama.iam.gserviceaccount.com`. La contraseña inicial se comunica al operador por separado y no figura en este documento. [Recibo de alta y permisos](../receipts/alta_kevin_administrador_20261104.json).

**Pendiente en su equipo:** generar su propio ADC, recibir por privado la contraseña SQL de `fama_oficial_app`, instalar dependencias, preparar perfil/runtime y verificar sus archivos. No se ha observado todavía una instalación ni autenticación Google de Kevin desde Linux.

## Lo que prepara Fabián

1. **Completado:** correo `kevcardenas675@gmail.com` y Linux confirmados por Fabián. Ese correo identifica el acceso técnico; la cuenta web de F.A.M.A. se administra por separado.
2. **Completado:** permiso de impersonación concedido y comprobado sobre la cuenta técnica oficial. La cuenta técnica ya tiene Cloud SQL Client en el proyecto y Storage Object User en el bucket según el corte previo; esta intervención no modificó las políticas de proyecto o bucket. Estos permisos técnicos permiten operar los recursos directamente y son distintos del rol web.
3. **Completado:** cuenta administradora propia creada y comprobada. Fabián entrega la contraseña inicial por privado; Kevin la cambia desde Mi cuenta cuando tenga acceso a su instalación.
4. Entregar por un canal privado el usuario SQL de aplicación `fama_oficial_app` y su contraseña. Es una credencial distinta a la de la cuenta web. Para el uso diario no se entrega el usuario `postgres` ni el migrador; tampoco se vuelve a ejecutar la migración ya aplicada.
5. **Disponibles según Fabián:** pesos, índice y audios ya en poder de Kevin. Sus rutas y huellas aún se verifican en Linux; no hace falta repetir la transferencia por esta alta.

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

La sección siguiente concreta el perfil nativo Linux. Elegir la carpeta de su clon; no ejecutar literalmente rutas `C:/Users/fabia/...` en otro equipo. La distribución Linux y la arquitectura del equipo no se han indicado: la instalación de Python, Node.js, gcloud y el proxy debe corresponder a ese sistema.

## Preparación nativa en Linux

Requiere el clon actualizado de `fix/afinamiento-integral`, Python 3.12 con venv, Node.js/npm, Google Cloud CLI y `cloud-sql-proxy` en PATH. Desde la raíz de su clon, en Bash:

```bash
export FAMA_ROOT="$PWD"
export FAMA_CONFIG="$FAMA_ROOT/backend/installation/kevin-oficial"
export FAMA_PROFILE="$FAMA_CONFIG/native"
export CLOUDSDK_CONFIG="$HOME/.config/fama-gcloud"
export FAMA_ADC="$CLOUDSDK_CONFIG/application_default_credentials.json"
umask 077
mkdir -p "$CLOUDSDK_CONFIG"
python3.12 -m venv "$FAMA_ROOT/backend/.venv"
"$FAMA_ROOT/backend/.venv/bin/python" -m pip install -r "$FAMA_ROOT/backend/requirements.txt"
```

Usar la cuenta Google de Kevin al completar este login; genera su propio ADC:

```bash
gcloud auth application-default login \
  --impersonate-service-account=fama-oficial-app@proyectotesis-fama.iam.gserviceaccount.com \
  --disable-quota-project --project=proyectotesis-fama
chmod 600 "$FAMA_ADC"
```

Preparar un perfil nuevo; introducir la contraseña SQL de **`fama_oficial_app`**, distinta de la web. Si el directorio ya existe, revisar su estado antes de repetir; conservarlo:

```bash
cd "$FAMA_ROOT/backend"
.venv/bin/python -m app.node --config-dir "$FAMA_CONFIG" prepare \
  --project proyectotesis-fama --bucket fama-audio-records-2026 \
  --credentials-file "$FAMA_ADC" \
  --connection-name proyectotesis-fama:us-central1:fama-postgres-pruebas \
  --database fama_oficial --user fama_oficial_app \
  --proxy-port 5434 --web-origin http://localhost:3010

.venv/bin/python - "$FAMA_PROFILE" <<'PY'
import json
from pathlib import Path
import sys
from app.configuration import InstallationStore
store = InstallationStore(Path(sys.argv[1]))
state = store.read()
values = dict(state['values'])
values['FAMA_ENSEMBLES_JSON'] = json.dumps({
    'version': 1, 'enabled': ['chilean-birds-ensemble'],
    'default': 'chilean-birds-ensemble',
})
store.save(values)
PY

.venv/bin/python -m app.node --config-dir "$FAMA_PROFILE" runtime \
  --directory "$FAMA_ROOT/runtime/kevin-oficial"
```

Preparar la raíz antes de copiar archivos. Después colocar los cinco pesos en `runtime/kevin-oficial/checkpoints/` y los audios con su CSV en `runtime/kevin-oficial/data/raw/AvesChilenas/`, conservando nombres, subcarpetas, mayúsculas y acentos. Los pesos y el CSV se comparan con las huellas del recibo de actualización; no copiar los marcadores/bloqueos del runtime de Fabián.

En **otra terminal**, dejar el proxy ejecutándose:

```bash
cloud-sql-proxy --address 127.0.0.1 --port 5434 \
  --credentials-file "$HOME/.config/fama-gcloud/application_default_credentials.json" \
  proyectotesis-fama:us-central1:fama-postgres-pruebas
```

De vuelta en la primera terminal, comprobar conexiones y adoptar su cuenta existente **ID 2**:

```bash
cd "$FAMA_ROOT/backend"
.venv/bin/python -m app.node --config-dir "$FAMA_PROFILE" check
.venv/bin/python -m app.history_adoption --config-dir "$FAMA_PROFILE" --user-id 2
.venv/bin/python -m app.history_adoption --config-dir "$FAMA_PROFILE" --user-id 2 \
  --apply --confirm-database fama_oficial
.venv/bin/python -m app.node --config-dir "$FAMA_PROFILE" serve --port 8010
```

La vista previa debe informar `history_adoption_ready` y la aplicación `history_adopted`. Una instalación completada ya no repite esta preparación. Estos comandos no aplican una migración SQL ni crean otra cuenta.

En una tercera terminal, desde `frontend/` de su clon, iniciar la interfaz para revisión local:

```bash
npm ci
export API_URL=http://127.0.0.1:8010
export NEXT_PUBLIC_API_URL=http://localhost:3010
export FAMA_NEXT_DIST_DIR=.next-kevin-oficial
npm run dev -- --webpack --hostname 127.0.0.1 --port 3010
```

Este último comando utiliza el modo de desarrollo. El servicio permanente y una compilación de producción se preparan aparte. Mantener las tres terminales abiertas; comprobar `http://127.0.0.1:8010/ready` (`schema_current`) y entrar en `http://localhost:3010` con su cuenta propia. Los workers ZIP requieren su procedimiento y ejecución correspondientes.

Los comandos se contrastaron con las interfaces del checkout actual; no se ejecutaron en el equipo Linux de Kevin. Su arranque, sus dependencias y la disponibilidad de sus archivos siguen pendientes de comprobación allí.

## Material que permanece en el PC del operador

El ADC del operador, sus secretos/JWT/claves de límites, contraseña administradora personal, carpetas completas `backend/credentials/` y `backend/installation/`, `.env`, dumps SQL, `.venv`, `node_modules` y compilaciones `.next-*` no se entregan como configuración portable. Kevin genera autenticación, secretos, dependencias y compilación propios. Para compartir la misma base no necesita recibir un dump.

## Fuentes y límites

- [ADC local e impersonación, documentación de Google](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment?hl=en).
- [Permisos de impersonación](https://docs.cloud.google.com/docs/authentication/use-service-account-impersonation).
- [Requisitos del Cloud SQL Auth Proxy](https://docs.cloud.google.com/sql/docs/postgres/sql-proxy).
- [Estado oficial aplicado y recuperación](actualizacion_oficial_0004_20261025.md).

La política IAM y la cuenta web se verificaron el 4 de noviembre, con los límites del recibo. No acreditan que Kevin tenga programas instalados o un nodo Linux funcionando. No se enviaron mensajes o archivos a Kevin; Fabián entrega las credenciales por un canal privado. Las contraseñas no forman parte de esta guía ni de los recibos.
