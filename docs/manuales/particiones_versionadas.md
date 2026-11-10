# Preparar y utilizar particiones versionadas

Implementación del 23 de octubre de 2026, actualizada al integrar dev el 24 de octubre, rama `fix/afinamiento-integral`. Disponible para administradores e investigadores con acceso al dataset. No requiere migración SQL ni permisos administrativos adicionales.

## Uso en Entrenamiento

1. Selecciona el dataset y abre **Gestionar particiones**.
2. Puedes elegir una versión guardada o preparar otra desde los audios registrados que están descargados en este equipo. La opción **Usar CSV existentes** conserva el funcionamiento anterior y requiere preparaciones de tres grupos verificadas en Linux. En Windows, preparar una versión desde los audios locales.
3. Deja inicialmente **20 % de validación**, **20 % de prueba** y **semilla 42**, o ajusta cada grupo entre 10 y 40 %, dejando al menos 40 % objetivo para entrenamiento. La semilla permite repetir el reparto con la misma selección y procedencia; no mide calidad.
4. Pulsa **Previsualizar reparto**. Revisa las cantidades reales de entrenamiento/validación/prueba por clase y las advertencias. Se intenta respetar el porcentaje sin dividir grupos ni dejar una clase fuera del entrenamiento; el porcentaje efectivo puede diferir.
5. Cuando existan advertencias, confirma que las revisaste. Pulsa **Guardar versión y seleccionarla**. Esta operación guarda el manifiesto local y lo elige para el próximo trabajo; todavía no entrena.
6. Inicia el entrenamiento con los parámetros habituales. El trabajo comprobará los archivos de esa versión y el modelo guardado conservará su manifiesto. El historial muestra el identificador corto de particiones cuando el checkpoint lo contiene.

**Entrenamiento** es el conjunto utilizado para aprender; **validación** se utiliza durante el ajuste para observar rendimiento. **Prueba** se reserva para evaluar el checkpoint final con grabaciones distintas. Las versiones nuevas tienen formato 2; las 80/20 de formato 1 permanecen como historia y deben sustituirse por una versión nueva para entrenar. La evaluación final no activa por sí sola el modelo global: esa acción sigue correspondiendo al administrador.

## Qué queda fijado

Una versión conserva identidad del dataset y su destino de almacenamiento, política y semilla, IDs de los audios, rutas relativas canónicas, etiquetas, tamaños, SHA-256, grupos conocidos y reparto. El identificador depende del contenido. El autor y la fecha de la primera publicación quedan registrados por separado; reenviar la misma publicación no los reemplaza.

Añadir audios no modifica las versiones existentes. Para incluir los aportes nuevos se prepara otra versión. Si el contenido cambia entre la vista previa y el guardado, la aplicación pide generar otra propuesta. Si cambia un audio de una versión ya guardada, el entrenamiento falla explícitamente; no elige automáticamente otros CSV ni otro dataset.

Se conserva el manifiesto en `backend/data/raw/<dataset>/.partitions/<version>.json`, bajo la raíz del backend que está ejecutándose. Los CSV históricos no se reescriben. El fichero identifica una selección y sus bytes esperados: no contiene una copia física del audio. Debe respaldarse junto con las grabaciones y checkpoints; este bloque no implementa su respaldo a GCS.

## Duplicados, procedencia y exclusiones

- Grabaciones con el mismo SHA-256, un mismo `source_group` o un grabador conocido se agrupan de forma transitiva. Un grupo completo permanece dentro de una sola partición.
- Una grabación idéntica con etiquetas contradictorias bloquea la propuesta hasta revisar las clases. Las variantes de clase históricas, como `Chucao` y `chucao`, no se fusionan automáticamente.
- La información adicional se lee de `metadata.csv` canónico, enlazada por `file_path`/`file_stage`. Los metadatos ambiguos o una etiqueta incompatible con el registro SQL requieren revisión.
- Los audios sin copia local se excluyen y se informa su cantidad. Descárgalos si deben participar.
- Los audios incorporados mediante corrección que no tengan un grupo de origen registrado se excluyen de la propuesta. Esto evita tratar un posible derivado como una observación independiente; no borra ni revierte su incorporación. En este alcance, documentar ese origen en los metadatos sigue siendo un paso manual. La interfaz nueva no incluye un editor de procedencia.
- Un grabador desconocido no se transforma en un grabador inventado. Marcadores como `unknown` o `human_feedback` no acreditan procedencia. La advertencia indica que no se puede garantizar independencia de grabadores o de derivados cuya relación no se conoce.
- Si una clase solo dispone de un grupo, puede quedar únicamente en entrenamiento, con advertencia. Se necesitan validación y prueba no vacías y ninguna clase de validación puede quedar ausente de entrenamiento.

No se reutilizan las funciones históricas que permiten separar filas cuando faltan grupos suficientes. Las preparaciones CSV verificadas conservan su identidad y selección histórica explícita de dev. No se reutiliza validación como prueba.

## Operación y límites

Las cuatro operaciones de vista previa, publicación, listado y lectura exigen sesión y acceso vigente al dataset. Revocar la asignación vuelve a bloquearlas. No se cambia la asignación ni se requiere revisión de otro administrador para publicar.

Se admiten hasta 10000 audios registrados por preparación, y el listado consulta hasta cincuenta manifiestos recientes. Leer y calcular hashes puede tardar en datasets grandes. Los metadatos canónicos se limitan a 16 MiB/100000 filas. Solo se utilizan audios del registro SQL; una carpeta local no registrada no se incorpora por descubrimiento de archivos.

Se verifican los hashes al admitir el trabajo, al entrar en su ejecución y antes de publicar pesos. Estas verificaciones no bloquean el filesystem durante todo el entrenamiento ni garantizan detectar una alteración que se produzca y revierta entre controles. Las etiquetas y relaciones declaradas siguen dependiendo de la revisión humana. El manifiesto no es una firma criptográfica del autor ni una identidad portable entre bases reconstruidas.

Los manifiestos dañados o de otro destino de almacenamiento se rechazan. No editar su JSON para corregir una versión: preparar otra. La publicación utiliza temporal, fsync y creación sin reemplazo; el fsync del directorio se realiza donde el sistema operativo lo permite. No existe transacción común entre estos ficheros y la base SQL.

## Verificación

Las pruebas se realizan mediante HTTP autenticado y la interfaz renderizada, con SQL/archivos temporales y ejecución ML sintética pequeña. Cubren grupos y duplicados, correcciones sin origen, clases contradictorias, permisos/origen de la petición, cambios de archivos, reintentos, destino de almacenamiento y manifiestos dañados. Las pruebas de entrenamiento comprueban la versión conservada en el checkpoint y rechazan publicar un modelo si cambia el audio durante la ejecución.

Resultados y recorrido visible del entorno real de pruebas: [recibo](../receipts/particiones_versionadas_20261023.json). Diseño: [ADR 0062](../adr/0062-particiones-explicitas-y-manifiestos-inmutables.md). El bloque posterior ya permite [respaldar y recuperar checkpoints](respaldo_y_recuperacion_checkpoints.md); no copia por separado los manifiestos externos al checkpoint. El bucket oficial no se cambia con estas implementaciones.

Comprobación operativa del 23 de octubre: versión `2262aaf0364a`, ocho train/dos val de `FAMA_Prueba_Aves`, guardada y seleccionada desde la sesión administradora. Se mantuvieron los quince archivos anteriores y el modelo existente. El manifiesto también se conservó junto a la muestra original fuera de `.pytest_cache`; no se respaldó en GCS. [Captura del resultado](../images/particiones_versionadas_20261023.png).
