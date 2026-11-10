# Traslado de historia y adopción del administrador

**Estado vigente — 24 de octubre, arranque oficial:** el nodo de `http://localhost:3010` usa `fama_oficial`, `fama-audio-records-2026` y `runtime/oficial`. Perfil completado mediante adopción del administrador histórico, recuperación de contraseña solicitada por el operador e inicio de sesión verificado. Super-Ensamble de aves predeterminado y cinco modelos individuales seleccionables; inferencia real acotada correcta. Los cinco audios históricos diferentes están versionados en GCS, con 1205 filas conservadas en el índice; catálogo SQL de 1220 objetos de aves, 1386 de motores y un audio histórico industrial. Pesos respaldados por contenido y verificados. Los contadores globales ahora recorren todo el bucket: 2646 objetos observados. Siguen pesos del ensamble industrial, respaldo SQL externo/retención y despliegue universitario con HTTPS y servicio estable. [Estado operativo y límites](conciliacion_catalogo_y_pesos_oficiales.md), [recibo actual](../receipts/catalogo_oficial_publicado_20261024.json). Los bloques inferiores conservan sus cortes históricos.

**Corte: 24 de octubre de 2026. Rama: `fix/afinamiento-integral`.** Traslado real informado por el operador y verificado independientemente: cuenta/hash, todos los campos históricos y siete siguientes secuencias iguales. Runtime en preparación; perfil oficial sin activar. Sigue [conciliación de catálogo y pesos](conciliacion_catalogo_y_pesos_oficiales.md).

<a id="paso-inmediato-copiar-la-historia-al-esquema-oficial"></a>

## Copia de la historia: paso ya realizado

**Resultado posterior:** el operador ejecutó la copia y compartió `history_transferred`; Codex comprobó igualdad completa de los campos históricos y secuencias. El comando inferior conserva el procedimiento realizado; el destino ocupado rechaza repetirlo. [Recibo posterior](../receipts/traslado_historia_confirmado_y_pesos_20261024.json).

El operador compartió `official_schema_prepared`. La comprobación independiente de SQL/GCS y del perfil confirmó las seis comprobaciones correctas. La vista previa del traslado reconoce una cuenta administradora, un dataset, un audio, cinco modelos, 31 predicciones, una corrección y una sincronización; no hay métricas históricas.

La huella de filas y siguientes valores de secuencias es `922c811f8d90b01f58212613b2ebd913e43ea28555304af366c7e8b97a0afa64`: coincide con el traslado ensayado sobre el respaldo recuperado. Se volvió a comprobar el archivo conservado, 29983 bytes, SHA-256 `78855829efeee7bc16a8e893168f9a0d8649e3907c415f4a1b0929f1f2105a6b`. No se generó otro dump ni se sobrescribió ese respaldo.

En PowerShell del operador:

```powershell
Set-Location 'C:\Users\fabia\Desktop\F.A.M.A\backend'
& .\.venv\Scripts\python.exe -m scripts.trasladar_historia_oficial --config-dir 'C:\Users\fabia\Desktop\F.A.M.A\backend\installation\cloud-oficial\native' --source-env-file 'C:\Users\fabia\Desktop\F.A.M.A\backend\.env' apply --apply --confirm-source fama_db --confirm-target fama_oficial --expect-digest 922c811f8d90b01f58212613b2ebd913e43ea28555304af366c7e8b97a0afa64
```

Solicita la misma contraseña SQL de `fama_oficial_migrador` utilizada al preparar el esquema, con entrada oculta y solo en memoria. El origen se obtiene del archivo elegido expresamente; no se carga dotenv implícitamente ni se interpolan sus valores. Se ignoran variables `PG*` heredadas. La previsualización puede repetirse con los mismos dos argumentos iniciales y `plan`, sin contraseña del migrador y con transacciones de lectura.

Al aplicar, el comando exige que no haya otros clientes conectados al origen y mantiene bloqueos SHARE de las ocho tablas mientras copia. No termina procesos o conexiones ajenas; `official_history_source_busy` significa que debe revisarse el cliente abierto antes de reintentar. El bloqueo evita escrituras de tablas durante esta ventana, pero no impide que otro cliente conecte o avance una secuencia; la huella se vuelve a comparar con la prevista dentro del traslado. No establece una congelación permanente del origen.

Salida correcta: `history_transferred`, con los recuentos anteriores, la misma huella y `migrator_password_saved: false`. Compartir solo el JSON final. Ante `history_source_changed`, conservar el resultado y revisar diferencias y respaldo antes de aceptar otra huella. Ante `history_target_not_empty`, revisar el destino; no borrar sus filas para repetir la copia. La CLI conserva el rechazo transaccional del módulo de traslado.

Esta operación copia una historia concreta; el cambio de nodo oficial sigue pendiente. Antes de activar el perfil se conciliará catálogo, archivos, pesos y runtime, se identificarán/detendrán los escritores históricos y se volverá a comprobar que el origen conserve esta huella. Una diferencia posterior exige revisión. Los procesos de aplicación y proxies siguen funcionando como antes; `runtime/oficial` y la adopción real todavía no se han preparado/aplicado.

## Qué conserva el traslado

`app.history_transfer` lee las ocho tablas históricas y copia sus campos conocidos al esquema vigente de un destino vacío: cuenta y hash, datasets, audios, modelos, predicciones, retroalimentación, sincronizaciones y métricas. Conserva IDs, relaciones y siguiente valor de las siete secuencias históricas. Los dos campos nuevos de incorporación quedan NULL. No interpreta nombres como permisos: las tablas de asignaciones, solicitudes, procedencia de predicción, sesiones y recuperación permanecen vacías.

La validación reconoce el esquema de negocio congelado y su variante histórica observada: `retroalimentacion.id_prediccion` con CASCADE. En el destino se conserva RESTRICT. El ensayo real detectó esta diferencia y se añadió una prueba antes de admitir esa variante; no se ignoran diferencias generales de claves o columnas. Se rechazan tablas, funciones, triggers o esquemas ajenos, secuencias incoherentes, ausencia de administrador activo y sincronizaciones históricas pendientes de publicar.

La vista previa usa transacciones de lectura. Al aplicar, la instantánea del origen se compara con la huella prevista, y el destino toma el bloqueo compartido por las migraciones y bloqueos de tablas. Copia y verificación se confirman juntas. `ALTER SEQUENCE ... RESTART` permite revertir también los reinicios si falla una operación posterior. Un reintento sobre un destino ocupado se rechaza y conserva sus filas. El límite de esta operación es de 100000 filas por tabla.

La CLI general recibe referencias privadas elegidas expresamente, sin cargar `.env` ni mostrar filas:

```powershell
python -m app.history_transfer --source-url-file '<referencia-privada-origen>' --target-url-file '<referencia-privada-destino>' plan
python -m app.history_transfer --source-url-file '<referencia-privada-origen>' --target-url-file '<referencia-privada-destino>' apply --apply --confirm-source '<base-origen>' --confirm-target '<base-destino>' --expect-digest '<huella-del-plan>'
```

Los nombres entre ángulos son marcadores, no un comando preparado para los recursos reales. Se requiere una identidad propietaria de tablas/secuencias para aplicar. Las variables `PG*` heredadas se retiran solo del proceso de CLI; errores y resultados no contienen DSN, contraseñas, correos o hashes de cuenta. No se debe apuntar a otra base o borrar un destino ocupado para conseguir un resultado exitoso.

## Adopción local, posterior al traslado y a preparar archivos

`app.history_adoption` verifica configuración, SQL/GCS, esquema, permisos diarios, raíz de almacenamiento y que la cuenta seleccionada ya sea administradora activa. La vista previa no cierra la instalación. La aplicación explícita confirma el nombre de base, conserva la cuenta y escribe un único evento `account.operator_adopted`, visible en auditoría como «Cuenta existente adoptada por el operador».

Una intención privada en el directorio elegido guarda huellas de configuración/cuenta y el ID reservado del evento, sin contraseña ni su hash original. Si falla la publicación de `installation.json` después del commit SQL, el resultado `history_adoption_pending` permite reanudar con la misma intención. Un cambio de identidad/configuración, una intención de alta inicial, un runtime ocupado o una instalación completada bloquean la operación. La reserva puede dejar un hueco en la secuencia de auditoría si se cancela una transacción; no duplica eventos ni cambia las secuencias históricas.

```powershell
python -m app.history_adoption --config-dir '<perfil-nativo-preparado>' --user-id '<ID-existente>'
python -m app.history_adoption --config-dir '<perfil-nativo-preparado>' --user-id '<ID-existente>' --apply --confirm-database '<base-elegida>'
```

Estos comandos son el procedimiento de adopción, pendiente para el entorno oficial; no sustituyen conciliar los archivos ni la revisión del corte. El asistente web de alta inicial conserva su rechazo de bases con cuentas existentes. La CLI no inicia ni reinicia servicios.

<a id="paso-inmediato-del-operador-preparar-el-esquema-oficial"></a>

## Preparación del esquema oficial: paso ya realizado

El comando siguiente ya fue probado con los roles restringidos correspondientes. Lee el perfil oficial y pide la contraseña de `fama_oficial_migrador` con entrada oculta, únicamente en el terminal. Valida sus atributos antes de DDL, ejecuta las revisiones conocidas y aplica el SQL de permisos exclusivo de `fama_oficial`. La cuenta diaria recibe DML de negocio, SELECT de `alembic_version` y USAGE/SELECT de secuencias, sin UPDATE de la versión o secuencias. No conserva la contraseña del migrador en el perfil.

**Aplicación real confirmada el 24 de octubre:** el operador obtuvo `official_schema_prepared`; la lectura independiente confirmó 17 tablas, nueve secuencias, todas las tablas de negocio vacías y `completed=false`.

```powershell
Set-Location 'C:\Users\fabia\Desktop\F.A.M.A\backend'
& .\.venv\Scripts\python.exe -m scripts.preparar_esquema_oficial --config-dir 'C:\Users\fabia\Desktop\F.A.M.A\backend\installation\cloud-oficial\native' --apply
```

Salida correcta: `code: official_schema_prepared`, `revision: 0003_autonomy`, `runtime_permissions_ready: true`. Compartir solo el JSON final. El comando crea estructura y concede permisos; no traslada historia, crea cuentas web ni activa el perfil. Errores de contraseña, cancelación o entrada no oculta no crean tablas. Un esquema no versionado ocupado se conserva y devuelve `official_schema_not_prepared`; no se fuerza `stamp` ni se elimina contenido. Repetir una preparación sobre el esquema vigente conserva las filas existentes. Si falla una comprobación posterior, conservar la salida para revisar el estado antes de continuar.

## Evidencia y límites

**Bloque posterior de esquema real/comando oficial:** 23 PASS en dos archivos, diez casos de la CLI específica y trece del traslado general; cero fallos/errores/omisiones. Cubre entrada oculta/cancelación/contraseña incorrecta, perfil completado, origen cambiado, reintento con destino ocupado, otro cliente del origen conservado y rechazo anticipado de parámetros de red alternativos. Se retiró solo el laboratorio propio con tmpfs; cuatro contenedores anteriores preservados. [Recibo actualizado](../receipts/esquema_oficial_y_traslado_preparado_20261024.json). Las cifras siguientes describen el bloque anterior y no se suman como casos nuevos.

Selecciones backend disjuntas: **27 PASS** (traslado/esquema, dos archivos), **9 PASS** (adopción), **10 PASS** (preparación oficial), **46 PASS** (auditoría/CLI/configuración, tres archivos). Son 92 casos en siete archivos, no la suite global. Entrada de terminal y llamadas GCS se sustituyeron solo en sus interfaces externas; SQL y archivos fueron reales. El fallo de publicación se simuló en `os.replace`.

Frontend: 20 pruebas de administración aprobadas; TypeScript y lint de `SecurityPanel.tsx` sin diagnósticos. El chequeo global de whitespace conserva defectos anteriores en `backend/dataset_references.py`, que no se editó en este bloque.

Ensayo con el respaldo real: PostgreSQL 18 local restaurado a partir del dump conservado, copia de sus ocho tablas hacia un PostgreSQL 16 migrado a `0003_autonomy`, huellas iguales y adopción del administrador ID 1 en ese destino local. Se conservaron cuenta/hash y relaciones, sin asignaciones nuevas. Las comprobaciones de adopción hicieron lectura real de GCS. No se cargaron modelos, transfirieron audios o escribieron datos en Cloud SQL/GCS ni en el origen histórico. Los dos laboratorios de esta unidad se retiraron verificando ID, imagen y etiquetas, con tmpfs y cuatro contenedores ajenos conservados.

Los cinco modelos conservan `activo=true` histórico y carecen de dataset verificable. Esto sigue requiriendo una decisión de modelo predeterminado y conciliación de pesos; no se inventaron relaciones. La prueba no acredita calidad científica ni disponibilidad funcional del catálogo. La copia de historia se protege con el bloqueo acotado y la huella del respaldo; antes del cambio operativo se identificarán y detendrán escritores y se revisarán diferencias posteriores a la copia. Siguen referencias/casos de nombres, cinco versiones de audio de distinto tamaño, archivos no indexados, runtime oficial y copia externa/operación universitaria.

[Decisión ADR 0067](../adr/0067-traslado-explicito-de-historia-y-adopcion-de-cuenta.md), [respaldo de origen](respaldo_historico_postgresql18.md), [recibo de esta unidad](../receipts/traslado_historia_preparado_20261024.json), [orden general](preparacion_entorno_oficial.md#orden-posterior).
