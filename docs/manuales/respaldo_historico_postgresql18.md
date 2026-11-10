# Respaldo de la base histórica PostgreSQL 18

**Estado vigente — 24 de octubre, arranque oficial:** el nodo de `http://localhost:3010` usa `fama_oficial`, `fama-audio-records-2026` y `runtime/oficial`. Perfil completado mediante adopción del administrador histórico, recuperación de contraseña solicitada por el operador e inicio de sesión verificado. Super-Ensamble de aves predeterminado y cinco modelos individuales seleccionables; inferencia real acotada correcta. Los cinco audios históricos diferentes están versionados en GCS, con 1205 filas conservadas en el índice; catálogo SQL de 1220 objetos de aves, 1386 de motores y un audio histórico industrial. Pesos respaldados por contenido y verificados. Los contadores globales ahora recorren todo el bucket: 2646 objetos observados. Siguen pesos del ensamble industrial, respaldo SQL externo/retención y despliegue universitario con HTTPS y servicio estable. [Estado operativo y límites](conciliacion_catalogo_y_pesos_oficiales.md), [recibo actual](../receipts/catalogo_oficial_publicado_20261024.json). Los bloques inferiores conservan sus cortes históricos.

**Corte: 24 de octubre de 2026. Rama: `fix/afinamiento-integral`.** Respaldo y ensayo de recuperación completados; historia trasladada y comprobada posteriormente en `fama_oficial`.

## Origen y archivo conservado

La configuración histórica selecciona `fama_db` en PostgreSQL **18.0 local**, puerto 5432, sin revisión Alembic. Se verificaron destino y versión antes de exportar. Las consultas del operador de respaldo fueron de solo lectura; las credenciales permanecieron locales, sin argumentos con contraseña ni contenido de filas en el recibo público.

Se usaron `pg_dump` y `pg_restore` **18.0**, ya instalados en `C:\Program Files\PostgreSQL\18\bin`. El respaldo en formato custom está en:

`backend/installation/cloud-oficial/backups/legacy-pg18-20261024T045728Z-e5f57977466e/database.dump`

Tamaño **29983 bytes**; SHA-256 **`78855829efeee7bc16a8e893168f9a0d8649e3907c415f4a1b0929f1f2105a6b`**. El directorio y sus archivos tienen acceso limitado al usuario Windows actual/SYSTEM, están excluidos de Git y contienen datos reales, incluido el hash de la cuenta histórica. No deben publicarse como documentación ni subirse automáticamente a un bucket.

| Tabla | Filas del corte |
| --- | ---: |
| `usuario` | 1 |
| `conjunto_datos` | 1 |
| `audio` | 1 |
| `modelo` | 5 |
| `prediccion` | 31 |
| `retroalimentacion` | 1 |
| `feedback_sync` | 1 |
| `metrica_entrenamiento` | 0 |

## Exportación y ensayo

El manifiesto y `pg_dump --snapshot` compartieron una instantánea exportada desde una transacción `REPEATABLE READ READ ONLY`. Se compararon también los estados de secuencias antes/después de la exportación: coincidieron en la ventana observada. Esta observación no sustituye la ventana de corte final con los escritores identificados.

Se recuperó el archivo mediante `pg_restore --single-transaction --exit-on-error --no-owner --no-privileges` en una base exclusiva `legacy_restore`, publicada solo por loopback en un puerto efímero. Se usó la imagen ya almacenada PostgreSQL **18.2**, fijada por ID `sha256:b6b4d0b75c699a2c94dfc5a94fe09f38630f3b67ab0e1653ede1b7ac8e13c197`. No se restauró el dump sobre PostgreSQL 16 ni sobre Cloud SQL.

Los recuentos y huellas de todas las filas, columnas, índices, restricciones distintas de dos CHECK y siete secuencias coincidieron. La comparación inicial detectó dos diferencias textuales: PostgreSQL 18.2 expresó la conversión de un arreglo varchar a text como conversiones individuales de sus mismos elementos. Solo afectó `usuario.chk_usuario_rol` y `feedback_sync.feedback_sync_status`; sus listas literales permanecen iguales.

Se conservó el primer resultado y se verificó esta diferencia expresamente: segundo ensayo sobre el mismo dump, huellas de filas repetidas y ocho entradas por restricción, incluidos todos los valores válidos, inválidos, variantes de mayúsculas/espacios y NULL. Las tablas de verdad coincidieron entre origen 18.0 y recuperación 18.2. No se ignoraron otras diferencias ni se afirmó identidad textual de esos dos CHECK.

Los dos laboratorios usaron almacenamiento tmpfs, sin montajes del origen ni volúmenes persistentes. Se verificaron ID completo, imagen y etiquetas propias antes de retirar cada contenedor. Los cuatro contenedores previos conservaron sus identidades/estados. No se inició una aplicación sobre las copias, ni se cambiaron servicios del nodo, Cloud SQL o GCS.

## Alcance y continuación

**Avance posterior:** el operador aplicó la copia y Codex comprobó igualdad de todos los campos históricos y siguientes secuencias. También se respaldó el destino PostgreSQL 16 y se verificó su recuperación aislada: [catálogo/pesos y respaldo posterior](conciliacion_catalogo_y_pesos_oficiales.md). El dump 18 original de este manual se conserva como origen; no se restauró directamente sobre Cloud SQL 16.

La carpeta privada conserva dump, manifiestos de origen/recuperación, listado del archivo, diagnósticos y comprobaciones de los laboratorios. El [recibo público](../receipts/perfil_oficial_y_respaldo_historico_20261024.json) contiene agregados y huellas, sin filas o credenciales.

Es una copia lógica de la base y un ensayo compatible de recuperación local. No incluye archivos de audio/pesos, roles globales del clúster, una copia externa, política de retención ni recuperación administrada de GCP. Los propietarios/ACL originales se conservan en el archivo, pero no se aplicaron en los ensayos. No acredita calidad de modelos ni compatibilidad automática del esquema histórico con el backend actual.

**Actualización posterior del 24 de octubre:** traslado y adopción ya se implementaron y ensayaron sobre este respaldo. El esquema real de `fama_oficial` y los permisos diarios están confirmados. La vista previa actual conserva la misma huella de campos/secuencias que el ensayo de la copia recuperada; el archivo mantiene tamaño y SHA-256. Sigue ejecutar el [comando oficial de copia](traslado_historia_y_adopcion.md#paso-inmediato-copiar-la-historia-al-esquema-oficial), conciliar archivos/índices y preparar el cambio operativo. No se forzó una revisión sobre el origen ni se restauró el dump 18 sobre PostgreSQL 16. Esta revalidación no representa una congelación permanente del origen. [Orden completo](preparacion_entorno_oficial.md#orden-posterior).

Referencias: [pg_dump 18 e instantáneas](https://www.postgresql.org/docs/18/app-pgdump.html), [pg_restore 18](https://www.postgresql.org/docs/18/app-pgrestore.html), [CLI de respaldo de esquemas versionados y sus límites](respaldo_y_restauracion_postgresql.md).
