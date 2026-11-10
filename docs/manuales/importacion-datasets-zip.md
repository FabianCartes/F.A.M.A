# Importar datasets ZIP localmente

## Alcance vigente del MVP

**Importar ZIP** conserva una copia persistente local después de validar el archivo.
No sube a GCS, prepara particiones ni inicia entrenamiento. En la unidad b,
un ZIP confirmado localmente todavía no aparece en el inventario compartido:
la publicación y sus permisos corresponden a la unidad c.

Se retiraron la subida privada, sus revisiones/manifiestos, la exportación ZIP y
el presupuesto físico opt-in. No configurar `FAMA_IMPORT_STORAGE_PROFILE` ni
arrancar un worker de exportación o sincronización privada. No se eliminan tablas
congeladas ni datos persistidos por esta retirada. Se conservan la descarga del
inventario compartido GCS → local y la sincronización de retroalimentación.

## Importación desde la interfaz

1. Inicia sesión con una cuenta real y abre **Importar ZIP** en Gestión de audios.
   La admisión anónima está deshabilitada, incluso con flags locales antiguos.
2. Introduce nombre y descripción opcional. Selecciona un ZIP con una carpeta por
   clase, directamente en su raíz, y WAV inmediatamente dentro de cada clase:

   ```text
   chucao/audio_01.wav
   colilarga/audio_01.wav
   ```

3. No uses carpeta contenedora ni subcarpetas de sesiones, aunque estén vacías.
   `aves/chucao/audio_01.wav` se rechaza: «Organiza el ZIP como clase/audio.wav,
   sin carpeta contenedora ni subcarpetas.» No se corrige automáticamente.
4. Pulsa **Importar ZIP** para autorizar validación e importación local automática.
   Las solicitudes nuevas fijan `layout: "class_folders"` y `auto_import: true`.
   La API sigue comprobando seguridad, estructura y audio; no publica un resultado parcial.
5. Espera el resultado local. Recibir todos los bytes o admitir un trabajo no
   demuestra validación ni guardado. No hay acción posterior de subida privada.

Se admite una clase poblada y al menos un WAV válido único. Clases vacías o pequeñas
generan advertencias, no garantías de aptitud para entrenar. Mismo hash y clase se
omite; mismo contenido con otra clase bloquea la importación. Un hash no demuestra
equivalencia acústica de audios recodificados.

Cerrar el modal solo lo oculta: no cancela una operación. Una subida en curso
necesita terminar antes de abandonar la vista; el trabajo ya admitido continúa en
el servidor. Tras recargar, **Recuperar importaciones anteriores** consulta las diez
más recientes del propietario. Si falta completar la recepción, selecciona otra vez
el ZIP original; el cliente compara todos los bloques reconocidos antes de continuar.

Las solicitudes históricas sin `auto_import` conservan **Validar ZIP → Confirmar
importación local**, su raíz revisada y rutas históricas. Abrirlas o consultarlas no
las confirma. El backend conserva la ampliación de datasets locales del propietario;
la interfaz no ofrece añadir a un dataset existente. No se reasignan datos históricos.

## API local conservada

- `GET /api/ingestion/imports/datasets` conserva el catálogo local acotado por
  propietario para consumidores existentes: `file_count`, `class_count`,
  `total_size_bytes`, revisión e `imported_at`. No entrega `synced_file_count`.
- Las importaciones y los archivos no entregan `sync_status`; la vista previa
  no entrega `synced_count`. El estado de incorporación de feedback es otro contrato.
- Las páginas de miembros y la descarga individual local conservan autorización
  de propietario y comprobación SHA-256. Una copia corrupta no se sirve como válida.
- Los endpoints privados de sync, revisiones/manifiestos y exportaciones fueron
  retirados; no existe una API nueva de manifiesto local como reemplazo.

El inventario compartido muestra conteos locales y GCS procedentes de su flujo
existente. Un conteo remoto desconocido no equivale a cero ni a una subida confirmada.
Véase [transferencias](transferencias-datasets.md).

## Almacenamiento, límites y worker

`FAMA_IMPORT_ROOT` sigue configurando la raíz física persistente de importaciones.
Debe ser absoluta, sin enlaces, fuera del descubrimiento legacy `data/raw` y de
cualquier servidor público de archivos. No usar `/tmp` ni la capa efímera del
contenedor para datos persistentes. API y worker deben ver los mismos archivos.

| Límite predeterminado | Valor |
| --- | ---: |
| ZIP recibido | 6 GiB |
| Contenido expandido | 10 GiB |
| Entradas | 2.000 |
| WAV individual | 96 MiB / 600 s |
| Profundidad / ruta UTF-8 | 12 / 240 bytes |
| Validación | 900 s |
| Margen de espacio libre | 512 MiB |
| TTL | 86.400 s |
| Importaciones activas globales | 4 |
| Dataset acumulado | 15 GiB / 50.000 WAV únicos |

Se configuran mediante `FAMA_IMPORT_<CAMPO_EN_MAYÚSCULAS>` de `ImportLimits`.
El endpoint autenticado `/api/ingestion/imports/limits` informa los valores efectivos.
Los overrides no prueban capacidad, rendimiento ni viabilidad de un archivo concreto.
Se conserva el chequeo de espacio libre local y la reserva SQL de recepción;
esta última no preasigna disco ni protege frente a otros programas que lo llenen.

El proxy conserva su límite de 110 MiB por petición; la recepción fragmentada usa
16 MiB por defecto, no un cuerpo HTTP de 6 GiB. El endpoint legacy de archivo completo
no elude el proxy. La expansión se cuenta con bytes realmente leídos. Se rechazan
rutas ambiguas, enlaces/archivos especiales, cifrado, archivos no WAV y ZIP anidados.

El worker externo conserva sandbox y controles de propietario, cuotas, journals,
leases y recuperación. Ya es local por defecto; `--local-only` sigue aceptado para
los lanzadores existentes. `--sync-only` no existe. No necesita un perfil físico
ni configuración GCS. Comandos, recepción, limpieza y límites de verificación en
[trabajos locales](trabajos-importacion-datasets.md).

## Fallos y recuperación

Un rechazo definitivo anterior al journal cancela la importación, conserva motivos
y libera la promesa lógica; envía una solicitud nueva con el ZIP corregido.
Una desconexión no prueba fallo terminal: consulta el estado antes de repetir.
No borres staging ni cambies contadores para forzar éxito.

Un journal `committing` conserva la publicación pendiente: recuperar mediante el
trabajo existente y las mismas raíces. Se verifica el destino ya movido y se completa
membresía una sola vez. La limpieza es mantenimiento explícito, no un efecto HTTP;
conserva objetos publicados y trabajo recuperable. Liberar reserva no acredita
recuperación física de espacio.

## Operación y evidencia

El código del checkout no acredita actualización de la instancia instalada.
No iniciar Docker, servicios, migraciones o acceso cloud por seguir este manual:
requieren autorización y prerrequisitos independientes. Los recibos anteriores
siguen siendo cortes históricos, no evidencia del contrato reducido actual.

La comprobación ordinaria usa el runner aislado descrito en
[integración del entrenamiento](integracion-flujo-entrenamiento.md#reproducir-comprobaciones-aisladas),
con SQLite en memoria, ZIP/WAV sintéticos, temporales privados y red bloqueada.
La suite local no valida PostgreSQL, navegador, GCS real, sandbox OS ni Docker/Python 3.12.
No ejecutar el caso de inventario real `test_cli_paths.py::test_ingestion_service_both_datasets_synced`.
