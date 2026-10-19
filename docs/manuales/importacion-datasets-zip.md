# Importar datasets ZIP y sincronizarlos posteriormente

La nueva sección **Importar dataset** de Gestión de audios conserva primero una
copia persistente local y permite sincronizarla posteriormente con GCS. No prepara
particiones, extrae tensores ni inicia entrenamiento. Implementación local: todavía
no acredita despliegue ni operación real de GCS.

Para recepción reanudable, exportación nativa y mantenimiento, consultar la
[guía integral de operación y comprobación sintética T8](integracion-importacion-datasets.md).
Los pasos Docker de este manual requieren autorización separada; no forman parte
de esa comprobación aislada.

## Uso

1. En **Gestión de audios**, pulsa **Importar dataset**, junto a **Descargar Dataset
   al Entorno Local**. Lee las instrucciones y límites en la ventana modal y pulsa
   **Importar dataset** dentro de ella para mostrar el formulario. No hay formulario
   de login en el importador: la vista de acceso y la política de roles están
   pendientes de integración. Para probar sin sesión, el operador debe habilitar
   explícitamente el modo local descrito más abajo. Fuera de ese modo, el backend
   conserva la autenticación; el panel puede recibir una sesión de la futura vista
   de acceso, pero todavía no está conectado a ella.
2. Crea un dataset privado con nombre/descripción o selecciona uno propio. Las
   colecciones antiguas sin propietario no se ofrecen como destinos de escritura.
3. Descarga el ejemplo sintético si lo necesitas. Selecciona un ZIP con WAV:

   ```text
   aves/
     chucao/audio_01.wav
     colilarga/audio_01.wav
   ```

4. Indica `aves` como raíz para ese ejemplo, o deja la raíz vacía si las clases
   están directamente en el ZIP. En `aves/chucao/sesion_01/audio.wav`, la clase es
   `chucao`; la sesión queda como organización original, no como nueva etiqueta.
5. Pulsa **Validar ZIP** y revisa rutas, clases, errores y duplicados. Cambiar la raíz
   exige validar nuevamente. El destino queda fijado por solicitud; para cambiarlo,
   crea otra solicitud. No se aceptan confirmaciones de una vista previa obsoleta.
6. Confirma la importación local. Consulta y descarga sus archivos desde el panel.
   Una repetición exacta informa que no hay novedades sin incrementar los contadores.
7. Solo cuando corresponda, pulsa **Sincronizar con GCS**. Si queda en curso o falla,
   reanuda desde el mismo panel. La copia local no se elimina.

Puedes cerrar la ventana con **Cerrar importación**, Escape o pulsando el fondo
oscuro exterior. Pulsar dentro no la cierra. Cerrar solo oculta la ventana: conserva
el formulario, el ZIP seleccionado y el trabajo mientras permanezcas en la vista;
no cancela una operación ni libera su cupo. Volver a pulsar el botón permite continuar.
Si recargas o abandonas la vista, usa **Recuperar importaciones anteriores** y, si
la recepción no terminó, selecciona de nuevo el ZIP original.

Se admite al menos un WAV válido único y una clase poblada. Clases vacías y pequeñas
generan advertencias; esto no significa que el dataset sea apto para entrenamiento.
Mismo hash y clase se omite; mismo contenido con otra clase bloquea la confirmación.
Mismo nombre y bytes diferentes se conserva con identidades independientes. El hash
no demuestra equivalencia acústica de audios recodificados.

## Configuración del operador

### Preparación explícita de la base de pruebas

`backend/scripts/prepare_zip_manual_database.py` admite únicamente la base local
dedicada `fama_zip_manual`. `--initialize --writers-stopped` prepara un esquema
vacío mediante las etapas existentes; rechaza esquemas usados y no debe repetirse
como reparación. `--check` verifica tablas y marcadores sin backfill ni escrituras.
Ambas acciones requieren `--database-url` explícita; consultar `--help` para los
argumentos. No ejecutar sobre la base habitual ni usar datos reales.

### Excepción de desarrollo local

El modo sin login está **desactivado por defecto**. Requiere estas dos variables
en el proceso del backend:

```bash
FAMA_ENV=development
FAMA_IMPORT_DEV_MODE=1
```

#### Prueba manual aislada con worker externo

El lanzador `.venv/bin/python -B backend/scripts/zip_manual.py` utiliza el proyecto
Compose independiente `fama-zip-manual`, una base y raíces privadas persistentes,
sin datos, checkpoints ni servicios del entorno habitual. Solo admite pruebas
con ZIP sintéticos; no usar GCS, exportación ni entrenamiento.

Para preparar imágenes, usar `build`. Solo una base nueva y vacía admite
`init --writers-stopped`, con API y worker detenidos; no repetir inicialización
ni backfill para reparar una base usada. `check` verifica sin escribir.
`up` mantiene un relay en primer plano para `http://127.0.0.1:3001`, sin publicar
puertos Docker ni habilitar salida a Internet. Mantener esa terminal abierta.
En otra terminal, ejecutar `worker`: procesa únicamente preview/confirm en el host
con el sandbox existente y espera entre intentos; no incluirlo en Docker.
Para detener, primero Ctrl+C en las terminales de worker y up; luego `stop`.
La parada conserva el volumen y los archivos; para continuar usar `up` y `worker`,
nunca `init`. No se instalan dependencias en el host ni se borran datos automáticamente.

#### Docker local explícito

Desde la raíz del repositorio, con Docker accesible y Compose >= 2.24.4:

```bash
./iniciar_fama.sh --dev --build
```

Abre **http://127.0.0.1:3000**. El script anuncia **Importación sin sesión habilitada**
y selecciona explícitamente `docker-compose.yml` y `docker-compose.dev.yml`.
Este último no se carga automáticamente. `--help` no necesita Docker.

El overlay **reemplaza** las publicaciones mediante `!override`: solo el frontend
publica `127.0.0.1:3000`; backend y PostgreSQL no publican puertos al host.
Los tres servicios usan exclusivamente la red dedicada `fama-dev`, subred
`172.30.253.0/24`. El frontend tiene `172.30.253.10`; el backend admite esa IP exacta
mediante `FAMA_IMPORT_DEV_FRONTEND_IP`, además de loopback. No admite la subred completa.
Uvicorn arranca con `--no-proxy-headers` y el frontend usa el proxy interno
`http://backend:8000`, sin URL pública alternativa. Si hay colisión de subred,
no amplíes la guarda: elige otra subred y cambia coordinadamente las tres IP y
la variable del peer; vuelve a validar Compose antes de arrancar.

Se conserva la base de desarrollo en el volumen `fama_dev_pgdata` del proyecto
y los archivos en `backend/data-dev`, separados de los datos normales. No se monta
la clave GCS del Compose base en el backend de desarrollo. Las imágenes, nombres
de contenedor y checkpoints se comparten con el arranque normal: **no ejecutar ambos
modos simultáneamente**, ni usar entrenamiento como comprobación del importador.
Se conserva el requisito GPU del Compose base; este modo no instala sus prerrequisitos.

Al inicializar ese volumen por primera vez, PostgreSQL crea una base vacía aunque
conserve el nombre `fama_db`. Por eso el catálogo puede informar que no hay modelos
publicados ni seleccionables: compartir checkpoints no copia sus registros y
evaluaciones en la base de desarrollo. El volumen normal `fama_pgdata` no se borra.
No copies ni publiques modelos automáticamente para resolver ese mensaje; usar
registros reales en desarrollo requiere una operación independiente autorizada.

Para diagnosticar, valida la configuración final sin iniciar contenedores:

```bash
export HOST_UID=$(id -u) HOST_GID=$(id -g)
docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend
```

Con el frontend iniciado, `curl -f http://127.0.0.1:3000/api/ingestion/imports/access`
debe devolver `{"development_mode":true}`. Un 403 indica un peer no admitido;
un 503 indica que se solicitó la excepción fuera de `FAMA_ENV=development`.
Para una prueba manual, descarga el ZIP sintético del importador, valídalo y
confírmalo; **no pulses Sincronizar con GCS** ni uses datasets reales.

Para desactivar, recrea **todos** los servicios con el arranque normal:

```bash
./iniciar_fama.sh --force-recreate
```

Sin `--dev`, el script fija solo el Compose normal incluso si el entorno contiene
`COMPOSE_FILE`. La capacidad debe volver a `{"development_mode":false}` y las
peticiones de importación sin sesión deben devolver 401. Esto restaura también
las publicaciones normales de frontend, backend y PostgreSQL; **no las endurece**.
Los datos de prueba permanecen separados y no se borran ni transfieren a cuentas.

#### Desarrollo directo sin Docker

Usa una base y un directorio persistente de pruebas. Arranca el backend enlazado
solo a `127.0.0.1` o `::1`, con ambas variables y `--no-proxy-headers`, sin proxy
ni túnel. No definas `FAMA_IMPORT_DEV_FRONTEND_IP` en ese modo.
La guarda usa el peer ASGI real: no publicar esta facilidad en servidores compartidos.
Quien controla Docker o la máquina, o puede acceder al frontend de desarrollo,
no queda aislado por esta excepción. No es autenticación entre contenedores.

- `FAMA_IMPORT_DEV_MODE=1` sin `FAMA_ENV=development` rechaza las rutas del importador
  con 503. Un cliente fuera de loopback y del peer exacto configurado recibe 403; las rutas no confían
  en `Host`, `Forwarded` ni `X-Forwarded-For` para admitirlo.
- Solo se sustituye la identidad de las solicitudes de importación sin credenciales.
  Se reserva el propietario `-1`, sin crear cuentas ni reutilizar usuarios reales.
  Todas las sesiones locales sin login comparten esa identidad: **no hay aislamiento
  entre navegadores o personas que accedan a ese mismo backend local**.
- Los filtros por propietario se conservan en consulta, ampliación, confirmación,
  cancelación, descarga y sincronización. No se da acceso a colecciones de cuentas
  reales ni al catálogo legacy como destino. Un Bearer presente se valida normalmente;
  si es inválido, no se convierte en una solicitud anónima local.
- `GET /api/ingestion/imports/access` solo informa `development_mode`; no lista
  usuarios, datasets ni límites. El frontend consulta esa capacidad antes de habilitar
  el formulario. No existe un interruptor de bypass controlado por el navegador.
- Quita `FAMA_IMPORT_DEV_MODE` o usa `0` y reinicia el backend para volver al acceso
  autenticado. Los objetos locales de desarrollo permanecen con propietario `-1`;
  no se transfieren automáticamente a ninguna cuenta.

Esta excepción no desactiva `/api/auth/me` ni la autenticación de otras rutas,
no prepara entrenamiento y no concede autorización para operaciones reales en GCS.

### Almacenamiento y límites

`FAMA_IMPORT_ROOT` debe ser una ruta absoluta física persistente, sin enlaces.
El valor por defecto es `backend/data/dataset-imports`, cubierto por el bind de
`backend/data` en el Compose versionado. Esto no acredita otros despliegues ni su
capacidad disponible. No usar `/tmp`, el navegador o la capa efímera del contenedor.
Mantener el directorio fuera de `data/raw` y de cualquier servidor de archivos
público. No configurar el prefijo remoto privado como fuente del catálogo legacy.

Los límites requieren sesión o la excepción local en `GET /api/ingestion/imports/limits` y se
configuran como enteros positivos mediante `FAMA_IMPORT_<CAMPO_EN_MAYÚSCULAS>`:

| Campo | Valor por defecto |
|---|---:|
| `RECEIVED_BYTES` | 67.108.864 |
| `EXPANDED_BYTES` | 268.435.456 |
| `ENTRIES` | 2.000 |
| `DEPTH` | 12 |
| `PATH_BYTES` | 240 bytes UTF-8 |
| `AUDIO_BYTES` | 33.554.432 |
| `AUDIO_SECONDS` | 600 |
| `VALIDATION_SECONDS` | 60 |
| `FREE_BYTES` | 536.870.912 |
| `TTL_SECONDS` | 86.400 |
| `CONCURRENT_IMPORTS` | 4 solicitudes activas globales |

Una sola mutación de almacenamiento se admite simultáneamente por volumen. Si el
lock está ocupado, el servidor devuelve 409 y no comienza otra operación. Las
solicitudes activas reservan cupo hasta finalizar, cancelar o vencer. La limpieza
se ejecuta al iniciar otra mutación: borra solamente staging propio vencido,
incluidos ZIP temporales de importaciones finalizadas; nunca los objetos publicados
ni el staging de una confirmación pendiente de recuperación. No es un cron separado.

La expansión se cuenta con bytes realmente leídos, no solamente con cabeceras ZIP.
Se rechazan rutas ambiguas, archivos especiales, cifrado, archivos no WAV y ZIP
anidados. El worker usa ahora un proceso contenido para interpretar ZIP, extraer
y decodificar WAV; si no puede establecer la contención, rechaza la validación sin
fallback. El presupuesto cooperativo del motor interno no es por sí solo un sandbox.
La sincronización conserva sus límites cooperativos y no queda contenida por T4.
Consulte [prerrequisitos, límites y comprobación T4](trabajos-importacion-datasets.md#t4-validacion-zip64-contenida)
antes de operar; esta entrega local no acredita el entorno desplegado.
El proxy actual admite 110 MiB; aumentar el límite recibido sobre ese valor requiere
revisar el proxy por separado. No se modifica su configuración en esta entrega.

## Persistencia y recuperación

Las tablas nuevas no cambian el formato de registros legacy. La migración explícita
es `python -m scripts.migrate_dataset_imports` desde `backend/` (dry-run sin conexión);
`--apply` crea únicamente las tablas ausentes en la base configurada y **requiere
autorización operacional**. El arranque actual de la aplicación también usa
`Base.metadata.create_all`; no actualiza tablas existentes. Ninguna migración real
se ejecutó durante la implementación.

Después de una interrupción, usa la misma sesión o identidad local de desarrollo y
**Recuperar importaciones anteriores**. Reenviar el ZIP original idéntico restablece
el archivo retenido si se perdió o corrompió; no permite sustituirlo por otros bytes.
La recepción confirma la durabilidad del archivo, su directorio y el directorio padre.
Reintenta la misma confirmación si está `committing`: el diario permite verificar
los archivos ya movidos y publicar una vez. No cancela ni limpia esas confirmaciones.
Mientras exista ese diario, una confirmación equivalente en otro destino espera
su recuperación; no puede dejarlo bloqueado permanentemente por equivalencia.
Si un destino cambió después de la vista previa, valida nuevamente; se rechaza antes
de publicar. Si cambió la integridad local, conserva el estado y solicita recuperación
al operador; no sobrescribas archivos manualmente.

La sincronización se liga al contenido de la importación confirmada, con progreso
persistente por archivo y hasta tres intentos para errores transitorios. No existe
un demonio residente: cada acción explícita procesa un lote hasta completar o llegar
al presupuesto; después se reanuda. Un estado `synced` acredita la verificación del
contenido de ese snapshot durante la ejecución, no vigilancia permanente del bucket
ni que ampliaciones posteriores del dataset estén sincronizadas. Volver a solicitar
una sincronización completada vuelve a verificar sus objetos.

## Verificación y exclusiones

Los tests nuevos usan WAV/ZIP sintéticos, SQLite en memoria, temporales privados,
red bloqueada y GCS simulado. Comando desde `backend/` con el intérprete validado:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// \
CUDA_VISIBLE_DEVICES='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
../.venv/bin/python tests/run_isolated_training_checks.py \
  tests/test_dataset_zip_validation.py tests/test_dataset_import_api.py \
  tests/test_dataset_import_sync.py tests/test_dataset_import_migration.py \
  tests/test_dataset_import_dev_mode.py tests/test_dataset_import_verifier_regressions.py \
  tests/test_import_legacy_isolation.py tests/test_ingestion_service.py tests/test_local_dataset_catalogue.py
```

El runner es una guarda de aplicación, no sandbox del sistema operativo. No valida
PostgreSQL real, Docker/Python 3.12, calidad ML, navegador real o disponibilidad GCS.
No ejecutar como regresión el caso de inventario real
`test_cli_paths.py::test_ingestion_service_both_datasets_synced`.
Frontend: `npm test`, `npm run lint`, `npm run build`; reportar resultados vigentes
en el [seguimiento](../arquitectura/dataset-zip-import.md), no reutilizar evidencia histórica.
Una prueba real GCS necesita autorización de destino, operación y credencial.

Pruebas del arranque y fusión real de Compose (sin daemon ni contenedores), desde la raíz:

```bash
bash tests/test_iniciar_fama.sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/test_compose_import_dev.py
```

La prueba HTTP de desarrollo realiza una importación ZIP sintética desde el peer
Docker, verifica aislamiento/Bearer y retorno al modo normal. No acredita navegador,
red Docker real ni el arranque de las imágenes; esos pasos requieren prueba operacional.
Política de acceso: [ADR 0028](../adr/0028-importacion-local-docker.md).
