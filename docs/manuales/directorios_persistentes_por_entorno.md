# Directorios persistentes por entorno

Implementado y activado el 23 de octubre de 2026 en `fix/afinamiento-integral`. El nodo de pruebas ya ejecuta el código del repositorio original y conserva sus archivos en `C:\Users\fabia\Desktop\F.A.M.A\runtime\pruebas`. La copia ejecutable de `.pytest_cache/stage8-live` quedó detenida y sus archivos originales se conservaron. Se mantiene `fama-pruebas`; el bucket oficial no cambió.

## Qué conserva la carpeta

```text
runtime/pruebas/
  .fama-runtime.json       identidad del entorno, sin contraseñas
  .fama-runtime.lock       bloqueo mientras vive el nodo
  data/raw/               audios, CSV, particiones e intenciones de incorporación
  data/processed/         tensores derivados
  checkpoints/            pesos de modelos
  logs/                   salida de los procesos iniciados por el lanzador
  run-last.json           PID, puertos y rutas de logs del último lanzamiento
```

`FAMA_RUNTIME_DIR` se guarda en el perfil privado de instalación. La huella vincula la carpeta al nombre de base, bucket e instancia configurados; cuando no hay nombre Cloud SQL, utiliza motor, host y puerto. No incluye contraseñas ni certifica la identidad de una base reconstruida con el mismo nombre. Con esta opción activa, la aplicación no busca audios ni pesos en carpetas históricas del código si faltan en la carpeta elegida.

La raíz debe ser absoluta y física, sin alias ni `..`. Una carpeta de otro entorno, una estructura incompleta o una raíz sin preparar bloquean la disponibilidad del nodo. Un segundo proceso local no puede compartir la misma raíz: el bloqueo se mantiene hasta cerrar el primero. Esto no es coordinación distribuida ni autorización para compartir volúmenes entre Windows, Docker y varios equipos.

## Consultar y arrancar las pruebas en Windows

Primero debe estar disponible el proxy Cloud SQL de pruebas en `127.0.0.1:5433`. El perfil ya cerrado es `backend/installation/cloud-pruebas/native`; sus referencias privadas a credenciales se conservan. No es necesario repetir el asistente ni ejecutar migraciones para iniciar este bloque.

Desde la raíz del repositorio, consultar el almacenamiento no inicia servidores ni conecta con SQL/GCS:

```powershell
Push-Location backend
try {
    & .\.venv\Scripts\python.exe -m app.node --config-dir installation/cloud-pruebas/native runtime
} finally { Pop-Location }
```

Para iniciar los dos procesos desde las fuentes originales, cuando 8010 y 3010 estén libres:

```powershell
& .\backend\scripts\iniciar_nodo.ps1 `
    -ConfigDirectory .\backend\installation\cloud-pruebas\native `
    -BackendPort 8010 -FrontendPort 3010
```

El lanzador requiere Python y dependencias del backend, Node y `frontend/node_modules` ya instalados. Usa `node` del PATH; si no está disponible, se indica su ejecutable con `-NodeExecutable`. En este equipo se utilizó `C:\Users\fabia\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe`. `-ValidateOnly` comprueba dependencias, puertos y perfil sin iniciar procesos. El origen web del perfil debe coincidir con `http://localhost:3010`; cambiar el puerto del lanzador no reconfigura ese origen.

`native_processes_started` acredita la creación de procesos, no que sus servicios estén listos. Revisar los logs y esperar HTTP 200 en `http://127.0.0.1:8010/ready`, luego abrir [F.A.M.A.](http://localhost:3010/). `run-last.json` ayuda a localizar los procesos; antes de detenerlos, comprobar su identidad y el propietario de los puertos. No detener servicios de 3000/8000 ni el proxy como efecto del cierre de las pruebas.

La compilación frontend usa `.next-3010`, separada de `.next`. Next añadió sus tipos generados a `tsconfig.json`; TypeScript se volvió a comprobar después. Las carpetas `runtime/` y `.next-*/` están excluidas de Git; esta última también del contexto Docker frontend.

## Preparar otro entorno o trasladar uno existente

Con el nodo detenido y el perfil correcto, se selecciona una carpeta vacía mediante la CLI del backend:

```powershell
& .\.venv\Scripts\python.exe -m app.node --config-dir <perfil-privado> runtime --directory <ruta-absoluta-exclusiva>
```

El comando prepara la estructura y cambia solo `FAMA_RUNTIME_DIR`; conserva el cierre de instalación y las demás referencias. No copia archivos, no mueve ni borra datos y no ejecuta migraciones. Si había otra raíz configurada, exige que tampoco esté ocupada. Consultar `runtime` sin `--directory` sí es posible mientras el nodo está funcionando.

Antes del arranque, el operador debe inventariar y copiar únicamente los archivos del entorno elegido, comprobar hashes y conservar los originales. Una carpeta no vacía sin marcador se rechaza para impedir adoptar contenido histórico accidentalmente. Si la preparación se interrumpe antes de publicar el marcador, revisar la carpeta y el perfil; el comando no limpia datos automáticamente. La preparación del árbol y la publicación del perfil no forman una sola transacción.

En el traslado comprobado se copiaron **29 archivos** desde la copia aislada anterior: 28 de datos y un checkpoint. Se verificaron SHA-256 en origen y destino antes y después de arrancar. La intención antigua `backend/data/raw/.feedback_1.json`, perteneciente a `AvesChilenas`, se conservó fuera del nuevo árbol. La intención propia de `FAMA_Prueba_Aves` sí se preservó. No restaurar un perfil sin raíz y arrancar el backend original: volvería a habilitar rutas históricas. La copia privada `installation.before-runtime-20261023.json` es evidencia del cambio, no un procedimiento automático de recuperación.

## Diagnósticos

| Código | Qué revisar |
| --- | --- |
| `runtime_ready` | Estructura e identidad local compatibles; la disponibilidad SQL se comprueba por separado. |
| `runtime_in_use` | Otro proceso local posee la carpeta. Verificar qué proceso está activo. |
| `runtime_identity_mismatch` | El marcador corresponde a otra combinación de instancia/base/bucket o fue alterado. |
| `runtime_directory_not_empty` | Hay contenido sin marcador; inventariarlo antes de preparar una raíz nueva. |
| `runtime_path_invalid` / `runtime_layout_invalid` | Ruta relativa, alias, estructura ausente o directorios inesperados. |
| `runtime_unprepared` / `runtime_not_configured` | Falta seleccionar/preparar la raíz o su marcador no puede leerse. |
| `runtime_identity_invalid` / `runtime_identity_incomplete` | Configuración de base/bucket inválida o incompleta. |
| `runtime_database_not_persistent` | SQLite en memoria o con ruta relativa; se requiere una identidad persistente. |
| `native_port_in_use` | Hay un servicio en alguno de los puertos elegidos; no se reemplaza. |
| `native_runtime_not_ready` / `native_dependency_missing` | Revisar primero el diagnóstico CLI o las dependencias locales. |

Los arranques antiguos sin `FAMA_RUNTIME_DIR` siguen siendo compatibles, pero no acreditan este aislamiento. La configuración se selecciona antes de importar los consumidores de datos; cambiar de perfil requiere un proceso nuevo.

## Docker y límites operativos

`docker-compose.cloud.yml` requiere una carpeta host `FAMA_RUNTIME_DIR` montada en `/var/lib/fama`, y configura esa raíz dentro del backend. El perfil del contenedor y el volumen deben prepararse con la CLI del contenedor antes del arranque funcional. Un perfil nativo con una ruta Windows no se adopta como perfil Linux. La prueba de este bloque valida el resultado de `docker compose config`: **no inició contenedores ni acreditó el despliegue institucional**. El `compose.env` anterior no se reescribió para asumir una carpeta host.

La persistencia local no es un respaldo. Los bloques posteriores ya comprobaron una [copia/restauración lógica de PostgreSQL en destino local separado](respaldo_y_restauracion_postgresql.md) y la [recuperación de emergencia del operador](recuperacion_emergencia_administrador.md). Siguen preparación del entorno oficial, política de copias/retención y destino independiente, secretos institucionales y HTTPS/proxy según el acceso final; el traslado al bucket oficial corresponde a un corte posterior acordado. Tampoco se resuelven aquí procedencias desconocidas, una prueba final independiente ni la revisión de `Chucao`/`chucao`.

## Evidencia

La regresión principal dio **226 PASS / 8 SKIP**; otras **16 pruebas físicas/sin archivo** y **dos de Compose** aprobaron en selecciones disjuntas: **244 PASS únicos**. Permanecen 40 casos anteriores que requieren privilegios Windows para crear symlinks; un primer intento los observó fallar con `WinError 1314`, antes del comportamiento probado. Frontend: **43 PASS**, TypeScript y lint de configuración/prueba sin diagnósticos. No se declara la suite global aprobada.

Tras el reinicio real, `/ready` devolvió 200, la API sin sesión devolvió 401 y seleccionar la raíz ya ocupada devolvió `runtime_in_use`. El navegador conservó la sesión administradora, el dataset y la versión `2262aaf0364a` de ocho train/dos val; la ficha confirmó copia local íntegra y respaldo disponible. La consulta cloud leyó metadatos, no volvió a descargar ni certificar los bytes remotos. SQL conservó 12 audios, un modelo inactivo y `0003_autonomy`; no hubo nuevas cargas GCS ni entrenamiento.

[ADR 0064](../adr/0064-almacenamiento-persistente-vinculado-al-entorno.md), [recibo verificable](../receipts/directorios_persistentes_20261023.json), [captura](../images/runtime_persistente_pruebas_20261023.png) y [bitácora](bitacora_acceso_e_instalacion.md).
