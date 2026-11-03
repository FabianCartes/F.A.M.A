# Traslado local fuera de línea

## Alcance y condición previa

El comando copia un laboratorio SQLite a un destino nuevo, privado y del mismo
montaje físico calificado. No activa servicios ni cambia el propietario lógico:
`owner_id=-1` sigue siendo el principal de desarrollo, no el UID de Linux.
**Todos los escritores deben permanecer detenidos durante la copia y después de
ella hasta elegir una única instancia operativa. Nunca ejecutar origen y copia
simultáneamente.** El reconocimiento CLI no prueba por sí mismo ausencia de
escritores: se comprueban trabajos, estados, integridad y huellas antes y después.
No es un sandbox ni una defensa contra procesos hostiles del mismo usuario.

Formato admitido: raíz privada con `manual.sqlite3`, `profile.json` y
`environment.json`; SQLite con journal `delete`, sin sidecars; todos los roles
físicos confinados bajo esa raíz y un único pool. Solo importaciones publicadas;
se rechazan trabajos queued/running, recepción incompleta, autoridad desconocida,
enlaces, archivos especiales y archivos con varios enlaces físicos. La limpieza
pendiente de una publicación no se rechaza por sí sola: deben conservarse y
validarse sus objetos, archivos recibidos e intentos respaldados por grants.
No se admiten rutas absolutas persistidas desconocidas; no se sustituyen cadenas
arbitrarias de la base. No usar este comando para adoptar datos históricos con
la activación de laboratorio vacío.

## Ejecución explícita

Desde `backend/`, con el intérprete y dependencias ya validados:

```sh
python -B scripts/relocate_dataset_storage.py \
  --source-root /ruta/privada/laboratorio \
  --destination-root /ruta/privada/instancia-nueva \
  --writers-stopped
```

El destino debe ser inexistente, canónico y ajeno al árbol del origen, con padre
privado del usuario. No se sobreescribe ni reutiliza un intento anterior.
`--help` describe la interfaz; omitir el reconocimiento produce exit 2.
Rechazos de validación/operación producen exit 1, diagnóstico en stderr y ningún
informe de éxito en stdout. Un error posterior a crear el destino conserva la
copia parcial: **no es utilizable**, no se elimina automáticamente y no debe
arrancarse. Seleccionar otra ruta nueva solo tras revisar el fallo.

## Qué se conserva y qué cambia

- SQLite se abre mediante URI de solo lectura y `query_only`; se usa su API de
  backup, sin BEGIN de escritura, checkpoint ni migración en el origen.
- Se copian una sola vez los roles solapados, incluidos staging/receipts,
  objetos, intentos, scratch y manifests; cada archivo se verifica por SHA-256 y
  tamaño, y cada WAV publicado contra su registro persistido.
- Se verifican primero el perfil antiguo y todos sus grants vivos mediante
  `PhysicalStorage.verify/require`. Solo en SQLite copiada cambian los hashes de
  configuración del pool y de política de grants mediante el mapeo validado.
  Una huella de todas las celdas y del SQL de tablas/índices comprueba que ninguna
  otra columna ni objeto de esquema cambió. Se rechazan triggers (incluso no-op),
  vistas y tablas virtuales/shadow antes de crear el destino o ejecutar el rebind;
  no se deshabilitan ni eliminan para forzar una copia.
  Identificadores, propietarios, estados, contadores y envelopes se conservan.
- El perfil copiado contiene únicamente rutas nuevas. Del entorno JSON se
  escriben únicamente límites numéricos `FAMA_IMPORT_*` reconocidos por
  `ImportLimits` y los tres parámetros de recepción: `FAMA_IMPORT_CHUNK_BYTES`
  (1..2³¹−1), `FAMA_IMPORT_RESERVED_BYTES_PER_OWNER` y
  `FAMA_IMPORT_RESERVED_BYTES_GLOBAL` (1..2⁶³−1). Se preservan sus valores
  efectivos, incluidos los defaults del runtime cuando no estaban declarados;
  no se ejecuta configuración ni se copian credenciales,
  scripts o variables ajenas. Un futuro launcher debe seleccionar explícitamente
  la SQLite/perfil/raíces nuevos; este comando no lo crea ni lo arranca.
- Se vuelven a validar ambas autoridades y la huella del origen antes de emitir
  `relocation-complete.json` y un informe JSON por stdout con exit 0. El informe
  incluye recuentos, bytes, hashes de configuración, SQLite e inventarios.

### Cadena de publicación admitida

La autoridad necesaria se deriva del estado persistido y se compara en ambos
sentidos con los grants vivos; no basta con verificar los que todavía existen.
Para limpieza `pending`, se exige receipt sellado/completo con reserva lógica
liberada, archive vivo, transferencia initial retirada y una única preview
succeeded. Se admite publicación automática dentro de esa preview o una sola
confirmación succeeded: su salida requiere el grant attempt, y la preview
conserva preview vivo o la transferencia retired-preview → retained vivo.
El `staging_attempt` debe identificar esa preview; `execution_id` identifica la
última operación admitida (preview automática o confirmación).

El manifiesto local de preview es **ImportSummary + ImportFile en SQLite**, no
un supuesto `manifest.json` del directorio de intentos. Se validan binding,
fingerprint, recuentos, clases, tamaños, nombres y SHA de toda la extracción
retenida, además de su correspondencia con la publicación. Un directorio vacío
no acredita extracción. El archive se comprueba también contra la secuencia de
fragmentos persistida, leyendo por bloques acotados. Los manifiestos JSON de
revisiones pertenecen al flujo de sincronización remota, que esta operación
acotada no adopta.

Para limpieza `done`, la autoridad restante debe corresponder a los bytes
publicados conservados; no se reactivan concesiones retiradas. Se rechazan
limpieza deleting/desconocida, sincronización pendiente de recuperación y cadenas
con múltiples previews/confirmaciones o reintentos no representables por estas
reglas. Esto limita el traslado, no modifica el comportamiento del runtime.
La forma conocida de S23–S24 —preview automática succeeded, publicación terminada
y limpieza pending— está cubierta sintéticamente con intentos separados de imports.

## Capacidad y retiro humano

Los grants son presupuesto, no preasignación física. La comprobación exige espacio
libre para la copia completa, metadatos, dos veces los envelopes vivos y el piso
del pool. Es conservadora: no descuenta objetos ya materializados del presupuesto.
La cifra contextual de 166 GB libres frente a dos presupuestos de unos 26 GiB no
sustituye la medición del momento ni autoriza dos escritores. No se inventan dos
capacidades independientes sobre el mismo SSD.

El original se conserva indefinidamente como respaldo hasta retiro humano
explícito. Este comando no borra, libera grants, limpia staging, cambia permisos
del origen, transfiere propietarios, sincroniza GCS, entrena ni activa la copia.
Las lecturas pueden actualizar atime; las comprobaciones de estabilidad cubren
contenido, inode, tamaño, mtime y ctime, no prometen atime inmutable.

## Evidencia y aceptación S23–S24

Las pruebas focales usan únicamente colecciones sintéticas y el CLI público:
catálogo/revisión/descarga idénticos, acceso del principal -1, guards antiguos y
nuevos, inodes independientes y rechazo sin alterar origen/destino previo.
La ejecución calificada pertenece al helper aislado del orquestador; no usar el
runner de entrenamiento para este seam de subprocess/SQLite en archivo.
La verificación independiente de datos persistidos (riesgo 1) y autoridad/rutas
(riesgo 2), las regresiones runtime/activación/migración y la eventual copia real
siguen siendo responsabilidad del orquestador. Pruebas sintéticas no acreditan
por sí mismas los 1.194 audios reales ni una instancia dedicada operativa.
