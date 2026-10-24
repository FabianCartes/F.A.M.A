# Preparación del entorno oficial

**Estado vigente — 24 de octubre, arranque oficial:** el nodo de `http://localhost:3010` usa `fama_oficial`, `fama-audio-records-2026` y `runtime/oficial`. Perfil completado mediante adopción del administrador histórico, recuperación de contraseña solicitada por el operador e inicio de sesión verificado. Super-Ensamble de aves predeterminado y cinco modelos individuales seleccionables; inferencia real acotada correcta. Los cinco audios históricos diferentes están versionados en GCS, con 1205 filas conservadas en el índice; catálogo SQL de 1220 objetos de aves, 1386 de motores y un audio histórico industrial. Pesos respaldados por contenido y verificados. Los contadores globales ahora recorren todo el bucket: 2646 objetos observados. Siguen pesos del ensamble industrial, respaldo SQL externo/retención y despliegue universitario con HTTPS y servicio estable. [Estado operativo y límites](conciliacion_catalogo_y_pesos_oficiales.md), [recibo actual](../receipts/catalogo_oficial_publicado_20261024.json). Los bloques inferiores conservan sus cortes históricos.

**Corte: 23 de octubre de 2026. Rama: `fix/afinamiento-integral`.**

El operador confirmó que F.A.M.A. se utilizará primero en este PC y después se trasladará a un servidor de su universidad. El primer arranque oficial se prepara para acceso local. El dominio, HTTPS y acceso de otros equipos se concretarán con las condiciones del servidor; no se abrirán puertos de red por esa expectativa futura.

**Actualización del 24 de octubre:** El operador trasladó la historia a `fama_oficial` y Codex confirmó igualdad de todos los campos y siete secuencias: 41 filas, cuenta/hash intactos, cinco modelos y 31 predicciones. El respaldo PostgreSQL 16 posterior también se restauró y verificó en un laboratorio retirado. `runtime/oficial` ya está vinculado al perfil: cinco pesos y un audio copiados con SHA-256 coincidente, sin datos de prueba; los cinco modelos cargan tras corregir el lector AudioCNN histórico. Hay un índice candidato privado de 1205 filas: 1200 audios coinciden con GCS por MD5/tamaño y cinco requieren elegir tratamiento. El operador confirmó las dos preferencias; siguen publicación/catálogo, audios, adopción y arranque; el perfil no está activado. [Estado y decisiones](conciliacion_catalogo_y_pesos_oficiales.md), [recibo](../receipts/traslado_historia_confirmado_y_pesos_20261024.json). Los apartados inferiores conservan sus cortes históricos.

## Destinos y separación

| Elemento | Uso actual de pruebas | Propuesta oficial |
| --- | --- | --- |
| Bucket | `fama-pruebas` | `fama-audio-records-2026`, ya existente |
| Base PostgreSQL | Cloud SQL 16, `fama_pruebas` | `fama_oficial`, creada en la misma instancia; esquema 0003_autonomy, permisos e historia trasladada/verificada |
| Perfil nativo | `backend/installation/cloud-pruebas/native` | `backend/installation/cloud-oficial/native`, preparado y comprobado; sin activar |
| Almacenamiento del nodo | `runtime/pruebas` | `runtime/oficial`, preparado con pesos y un audio; resto en preparación |
| Credenciales técnicas | Identidades de pruebas | Usuario SQL diario y migrador propios; credenciales oficiales separadas |
| Acceso web inicial | `http://localhost:3010` | Mismo acceso al efectuar el cambio controlado; no se iniciarán ambos nodos sobre ese puerto |

El operador confirmó reutilizar `proyectotesis-fama:us-central1:fama-postgres-pruebas` con una base oficial separada. Codex creó `fama_oficial` mediante Cloud SQL Admin, y el listado posterior conserva `postgres`, `fama_pruebas` y `fama_oficial`, con UTF8 y `en_US.UTF8`. No se creó otra instancia ni bucket. Separar bases no ofrece aislamiento de infraestructura: comparten capacidad, mantenimiento y autoridad del operador de la instancia. La creación de la base aún no prepara los permisos diarios ni acredita un esquema migrado.

La configuración anterior de `backend/.env` apunta a **PostgreSQL 18 local**, base `fama_db`, y al bucket oficial. Esa base es un origen histórico distinto de las pruebas Cloud SQL. No se debe cambiar el bucket del perfil de pruebas ni iniciar el código nuevo directamente sobre el esquema histórico.

## Inventario observado

Solo se consultaron metadatos en GCS y tablas SQL en una transacción de solo lectura. Los audios locales se leyeron para comparar huellas; no se decodificaron ni se cargaron modelos.

| Origen | Contenido observado | Implicación para el traslado |
| --- | --- | --- |
| GCS `datasets/AvesChilenas/` | 1215 objetos de audio, 5329102942 bytes; 18 carpetas de clase | Conservar identidades exactas. Hay variantes como `Chucao`/`chucao` y `Canastero`/`canastero`; una carpeta no determina por sí sola la etiqueta científica. |
| GCS `datasets/engine_diagnostics/` | 1386 audios, 185674284 bytes; 13 carpetas de clase | Existe en la nube; todavía no figura en la base histórica inventariada. No se ha descargado ni validado acústicamente. |
| GCS `raw_audios/` | 33 audios, 89003006 bytes | Inventario separado; no se asigna automáticamente a un dataset ni se supone correspondencia con todas las predicciones. |
| SQL local `fama_db` | Ocho tablas: una cuenta administradora, un dataset, un audio, cinco modelos, 31 predicciones, una retroalimentación y una sincronización; cero métricas | Conservar historia e identidades mediante traslado explícito. No tiene `alembic_version`; el migrador actual no admite actualizarla directamente. |
| Dataset SQL `MaquinariaMinas` | Un audio local de 220544 bytes; referencia cloud histórica | No se observó su prefijo en el listado del bucket. La referencia SQL no demuestra existencia remota. |
| Cinco modelos SQL | Pesos correspondientes encontrados localmente, con tamaños coincidentes y SHA-256 calculado | Los cinco están marcados activos en el origen y carecen de vínculo de dataset; eso no determina un único modelo predeterminado ni autoriza asignarlos a investigadores. No hay objetos bajo `models/` en el inventario cloud. |

La sincronización histórica está marcada `synced`. No se reintentó, reinterpretó ni publicó una intención antigua; su correspondencia completa de bytes no se verificó en este corte. La discrepancia entre la referencia SQL de `MaquinariaMinas` y el listado GCS se revisará antes de habilitar escritores sobre el destino oficial.

El listado completo contiene **2634 objetos / 5603780232 bytes**. Son observaciones de metadatos, no una instantánea transaccional de toda la nube ni una descarga que certifique integridad acústica.

### Índices y diferencias de AvesChilenas

- La carpeta local contiene **1211 audios**. El índice situado dentro de ella tiene una sola fila; no representa el conjunto completo.
- Se encontró el índice histórico alternativo `backend/data/metadata.csv`: **1205 filas, 15 etiquetas**, con identificador de origen, grabador y hash informado en cada fila.
- La previsualización del conversor resolvió **1205 referencias físicas únicas**, conservando todos los campos, el orden y el índice original. **No publicó candidato ni snapshot.**
- Se compararon los bytes de esos 1205 archivos con sus hashes históricos: **1205 coincidencias**, sin diferencias; 5387802024 bytes leídos. Esto acredita coincidencia con ese índice, no corrección de etiquetas, licencias ni independencia de grabadores.
- Por nombre cloud exacto y tamaño, 1050 archivos locales coinciden, cinco tienen tamaño diferente y 156 no tienen esa misma referencia remota. Hay 160 referencias remotas ausentes de la lista local exacta. La comparación distingue mayúsculas; no significa que todos sean audios distintos o adicionales.
- De las 156 referencias solo locales, 62 están en `Canastero`, 93 en `Chucao` y una en `churrín_de_la_mocha`. Las remotas sin referencia local incluyen 65 en `canastero`, 93 en `chucao`, una en `tijeral` y una en `zorzal_patagónico`.
- Los cinco tamaños distintos corresponden a `zorzal_patagónico/1083145.mp3`, `954562.mp3`, `954568.mp3`, `954572.mp3` y `954577.mp3`. Se conservan ambas versiones para decidir su tratamiento; no se sustituyó ninguna.
- Los seis archivos locales no incluidos en las 1205 filas mantienen su condición de no indexados. No se deduce su procedencia ni se incorporan a particiones por estar en la carpeta.

## Trabajo técnico completado en este bloque

El conversor offline ahora admite raíces y destinos absolutos nativos de Windows, además de los POSIX anteriores. Mantiene referencias persistidas POSIX relativas. Rechaza rutas Windows no canónicas, streams alternativos, dispositivos, nombres reservados, UNC y junctions en índices, raíces, destinos y referencias verificadas. No habilita acceso a recursos UNC ni elimina las carreras posteriores a la comprobación física.

La corrección se realizó con TDD sobre la CLI y archivos temporales: primero falló la previsualización nativa, y después fallaron los rechazos de junctions antes de corregirlos. Regresión: **61 PASS / siete casos antiguos deseleccionados**, dos archivos; los siete requieren symlinks o carpetas que solo difieren en mayúsculas, incompatibles con las condiciones Windows de esta ejecución. Los doce casos nuevos sí se ejecutaron, incluidas junctions reales. Sin regresión frontend, entrenamiento ni inferencia en este bloque. [Recibo](../receipts/preparacion_oficial_inventario_20261023.json).

## Pasos restantes hasta el cambio de uso

### Si solo aparece fama_pruebas

El 24 de octubre el operador reportó esta situación. El listado Cloud SQL consultado nuevamente muestra `postgres`, `fama_pruebas` y `fama_oficial` en el proyecto `proyectotesis-fama`, instancia `fama-postgres-pruebas`. La base existe; no se creó otra copia.

Comprobar primero **Cloud SQL → fama-postgres-pruebas → Bases de datos**, recargando la página con Ctrl+F5. Después volver a Studio y elegir `fama_oficial` al conectar con `postgres`. Si lo observado es el árbol del Explorador de Studio, este muestra los objetos de la base elegida al autenticar; no es el inventario de todas las bases de la instancia. [Documentación oficial](https://docs.cloud.google.com/sql/docs/postgres/manage-data-using-studio?hl=es). No se ha verificado aún si el reporte proviene de ese árbol, del selector o de otra vista. [Recibo del diagnóstico](../receipts/seleccion_base_oficial_20261024.json).

### Paso inmediato del operador: preparar identidades SQL

**Confirmación posterior, 24 de octubre:** el operador ya conectó Studio a `fama_oficial`, ejecutó el script e informó `crea_tablas=false` para la aplicación y `true` para el migrador. Codex observó ambos nombres en la API de usuarios. La autenticación y los atributos SQL completos desde el nodo se comprobarán después de asignar contraseñas. [Recibo](../receipts/roles_oficiales_operador_20261024.json). Las instrucciones siguientes conservan el procedimiento realizado.

El archivo [preparar_roles_oficial.sql](../../backend/scripts/preparar_roles_oficial.sql) ya está preparado y comprobado en PostgreSQL 16 local. Crea `fama_oficial_app` y `fama_oficial_migrador`, sin contraseñas asignadas; el primero utiliza el esquema y el segundo también puede crear tablas para las migraciones. Retira CONNECT/TEMP de PUBLIC en **esta base**, concede CONNECT a las dos identidades oficiales y conserva permisos/datos de `fama_pruebas`. No concede DML de tablas inexistentes; se otorgará y verificará después de migrar.

1. En Google Cloud, abrir **Cloud SQL → fama-postgres-pruebas → Cloud SQL Studio**.
2. Seleccionar base **`fama_oficial`**, usuario **`postgres`** e introducir allí la contraseña de la instancia.
3. Abrir una consulta, copiar el contenido completo de `preparar_roles_oficial.sql` y pulsar **Ejecutar**.
4. Confirmar las dos filas: ambos admiten login, conectan y usan el esquema; ambos indican `false` en superusuario/crear bases/crear roles. `crea_tablas` debe ser **false** para `fama_oficial_app` y **true** para `fama_oficial_migrador`.

Las contraseñas SQL se asignarán en el siguiente paso. El script se detiene si se ejecuta sobre otra base, existen identidades oficiales o hay tablas, funciones, tipos o esquemas previos; un rechazo exige revisar el resultado, sin intentar completar parcialmente la operación. Sus cambios se ejecutan dentro de una sola transacción `DO`.

**Pruebas del script:** ocho casos PostgreSQL reales aprobados: permisos limitados y separación, destino equivocado, cuatro variantes de objetos previos, identidad existente y propietario con CREATEROLE sin superusuario. El ensayo conservó los otros cuatro contenedores y retiró solo su contenedor/volumen exclusivos. La ejecución remota posterior fue confirmada por el operador el 24 de octubre, con el alcance indicado arriba.

### Siguiente paso: asignar contraseñas SQL

1. Volver a la instancia **fama-postgres-pruebas** y abrir **Usuarios**.
2. En `fama_oficial_migrador`, abrir **⋮ → Cambiar contraseña**, asignar una contraseña y guardar.
3. Repetir con `fama_oficial_app`, usando una contraseña diferente.
4. Conservar ambas en el gestor del operador, identificadas por usuario/instancia. Comunicar únicamente que la operación terminó; después se introducirán localmente en la preparación privada y la comprobación de conexión.

Se actualizan las cuentas existentes; no hace falta crearlas de nuevo. Este paso corresponde a los usuarios SQL oficiales, distintos de las cuentas web de F.A.M.A. El procedimiento de consola figura en la [documentación de Google](https://docs.cloud.google.com/sql/docs/postgres/create-manage-users). **Confirmación posterior del 24 de octubre:** el operador indicó que terminó de asignarlas. Codex no recibió sus valores; la autenticación desde el nodo sigue por comprobar.

### Siguiente paso: comprobar acceso desde este PC

En PowerShell del operador:

```powershell
Set-Location 'C:\Users\fabia\Desktop\F.A.M.A\backend'
& .\.venv\Scripts\python.exe -m scripts.comprobar_acceso_sql_oficial
```

El comando solicita primero la contraseña de `fama_oficial_migrador` y después la de `fama_oficial_app`, con entrada oculta. No aparecen caracteres al teclear. Las contraseñas no se guardan en archivos, no se pasan como argumentos ni se incluyen en el JSON final. El operador compartirá únicamente ese resultado.

Utiliza `127.0.0.1:5433`, base fija `fama_oficial`, ignorando `.env`, cualquier URL heredada y las variables `PG*` de libpq (solo en este proceso). Antes del relevo se comprobó que el PID 22380 seguía siendo el binario del proxy esperado, con la instancia correcta en sus argumentos y propietario del puerto loopback. Ese PID identifica esta observación, no un servicio permanente. Para este diagnóstico se reutiliza el transporte hacia la misma instancia; la identidad GCS y el perfil oficiales siguen pendientes y no se selecciona el bucket de pruebas como oficial.

Cada conexión establece `default_transaction_read_only=on` antes de consultar y limita la sentencia a cinco segundos y la conexión a ocho. Comprueba identidad, lectura, CONNECT/USAGE, CREATE solo para el migrador, ausencia de privilegios globales, TEMP, herencia y membresías. Informa el número de tablas públicas sin leer sus filas. No ejecuta migraciones ni comprueba todavía permisos DML o compatibilidad de esquema; los valida el procedimiento posterior.

La salida correcta contiene `code: official_sql_access_verified`, las dos identidades y los atributos observados. `public_tables: 0` es lo esperado en esta base recién preparada; se reporta el conteo, no se fuerza una migración ni se declara el backend listo por este código.

| Código | Acción del operador |
| --- | --- |
| `official_sql_authentication_failed` | Revisar la contraseña del usuario indicado; no se reintenta automáticamente. |
| `official_sql_permissions_invalid` | Conservar el resultado para revisar los atributos antes de continuar. |
| `official_sql_terminal_required` | Ejecutar en un PowerShell interactivo; no se permite entrada con eco. |
| `official_sql_password_required` | La entrada quedó vacía; volver a ejecutar e introducirla localmente. |
| `official_sql_unavailable` | Revisar proxy/conectividad antes de otro intento. |
| `official_sql_check_cancelled` | Se canceló la entrada; no se cambió la base. |

**Pruebas del comprobador:** 14 casos nuevos y ocho del script de roles, **22 PASS / dos archivos**, PostgreSQL 16 temporal real. Solo se sustituyó el hardware de entrada del terminal. Incluye contraseñas incorrectas/vacías, cancelación, negativa a entrada con eco, caracteres especiales, privilegios excesivos, variables de conexión/servicio heredadas y conservación de filas existentes. El laboratorio propio se retiró al finalizar; el acceso con las contraseñas oficiales reales espera la ejecución del operador. [Recibo](../receipts/comprobacion_sql_oficial_preparada_20261024.json).

**Resultado posterior del operador:** `official_sql_access_verified` para ambos usuarios, con los atributos previstos y `public_tables: 0`. El paso de autenticación local queda cubierto por ese resultado compartido; no se ejecutó otra autenticación SQL desde las herramientas de Codex. IAM y ADC oficiales ya están verificados; sigue [preparar el perfil](identidad_tecnica_oficial.md#perfil-local-preparado-y-comprobado) antes de migrar historia o activar el nodo.

### Orden posterior

1. **Completado:** instancia confirmada por el operador y base `fama_oficial` creada por Codex; base de pruebas conservada.
2. **Completado por Codex y operador:** roles SQL, contraseñas locales, identidad IAM/ADC y perfil oficial preparados; conexiones verificadas. Esquema y permisos DML también confirmados. Los scripts de `fama_pruebas` conservan sus guardas. No se reutilizará sin revisión la clave JSON anterior como configuración de despliegue universitario.
3. **Completado por Codex:** respaldo histórico con herramientas PostgreSQL 18 y recuperación compatible comprobados; [alcance y archivo](respaldo_historico_postgresql18.md). La CLI de respaldo reciente exige un esquema versionado y herramientas de la misma versión; no es aplicable directamente a esta base histórica. Un dump de PostgreSQL 18 no se tratará como una migración automática hacia PostgreSQL 16.
4. **Historia completada por operador y Codex:** traslado explícito al esquema vigente aplicado y comparado, con IDs, relaciones, campos y siguientes secuencias preservados. Sin permisos/autoría inventados. Adopción implementada y ensayada; su aplicación real espera catálogo y archivos. [Estado actual](conciliacion_catalogo_y_pesos_oficiales.md).
5. **Codex y operador:** revisar el plan de catálogo e índices antes de publicar. Resolver referencias de carpeta, cinco versiones de tamaño distinto y audios no indexados; mantener procedencia desconocida visible. Conservar los registros históricos aunque no puedan conceder permisos por falta de autor o dataset verificable. No inventar vínculos de los modelos ni aprobar retroalimentación automáticamente.
6. **Codex, en curso:** runtime oficial preparado; cinco pesos y un audio copiados/verificados. Los cinco modelos cargan tras la corrección de formato histórico. Quedan los audios/índice elegidos y respaldo externo de los checkpoints; no se copió FAMA_Prueba_Aves. Las cinco activaciones heredadas siguen intactas hasta resolver la preferencia solicitada.
7. **Ambos:** revisar el resultado preparado y acordar el corte. Detener los escritores que correspondan a los orígenes confirmados, tomar el corte final, arrancar el perfil oficial y comprobar acceso, catálogo, pesos y un recorrido funcional acotado. Cambiar el perfil en este paso establece el uso oficial. El perfil de pruebas y sus datos permanecen recuperables.
8. **Al disponer del servidor universitario:** confirmar sistema operativo, recursos, acceso a GCP y política de respaldo; regenerar referencias privadas del perfil para ese equipo, trasladar los archivos comprobados y configurar dominio/HTTPS y acceso de red. No se copian rutas absolutas de Windows como si fueran válidas en otro sistema.

Los pasos 3–6 son preparación de la migración real; no implican repetir todas las funciones sobre otro dataset de demostración. El respaldo externo, retención y prueba de recuperación del destino final siguen siendo decisiones operativas de la instalación.

## Conservación y evidencia

El corte inicial del inventario solo creó la base remota `fama_oficial`; sus recibos anteriores conservan ese alcance. Después el operador preparó usuarios SQL/contraseñas, Codex aplicó IAM autorizado y el operador generó ADC oficial. En el último paso se verificaron accesos de lectura y se inició un proxy oficial de loopback. No se han modificado tablas de aplicación, audios, índices activos o pesos ni activado un perfil oficial; servicios anteriores conservados. El laboratorio temporal de permisos ya se retiró. El nodo de pruebas sigue separado. La consulta no acredita qué perfil utiliza cada proceso antiguo que conserva su puerto abierto; se identificará al fijar la ventana de traslado.

Los metadatos por objeto y los informes con autores del índice se guardaron únicamente en `.pytest_cache/`, excluida de Git. El recibo público conserva agregados y huellas; no contiene correos de cuentas web, hashes de contraseña, claves privadas ni contenido de credenciales. El material temporal no sustituye un respaldo durable del origen.
