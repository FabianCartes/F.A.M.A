# Caché del hash de checkpoints por identidad de archivo

`GET /api/models` publicaba el catálogo verificando la integridad de cada checkpoint con SHA-256 sobre el archivo completo. La misma petición repetía ese cálculo en varios puntos (`_metadata_candidate`, `inspect_checkpoint` antes y después de deserializar, `assert_checkpoint_unchanged` y la propiedad `TrainedModelPredictor.metadata`, que además se leía una vez por campo al renombrar). Con 13 modelos y ~0,93 GB de checkpoints, cada petición hasheaba ~8,7 GB y tardaba ~5,4 s en un contenedor de 1 CPU; el modo estricto de React en desarrollo duplica la petición y la segunda espera el lock de publicación.

Se introduce `app.services.checkpoint_digest.file_sha256`, que reutiliza el hash mientras la identidad del archivo abierto no cambie: `(st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns)` obtenida con `fstat` del descriptor leído. Los tres puntos de verificación de identidad la usan. La caché es por proceso, protegida con lock y acotada (LRU de 512 entradas).

## Límite de confianza aceptado

Cualquier escritura actualiza `ctime`, que un proceso sin privilegios no puede restaurar; reemplazar el archivo cambia el inode. Por eso una reescritura del mismo tamaño con `mtime` restaurado o un `os.replace` siempre fuerzan un nuevo hash (cubierto por pruebas). Riesgo residual aceptado:

- Un actor con privilegios de root o con escritura que eluda el VFS (bloques del dispositivo, cambio del reloj del sistema) podría alterar bytes sin cambiar la identidad.
- En sistemas de archivos con marcas de tiempo gruesas (p. ej. resolución de segundos), una escritura in situ del mismo tamaño dentro del mismo tic no se distinguiría. Los volúmenes del proyecto (ext4/btrfs) tienen resolución de nanosegundos.

Un hash calculado mientras el archivo cambiaba queda guardado bajo una identidad que ya no existe, por lo que no se reutiliza.

## Lo que no cambia

La carga para inferencia (`TrainedModelPredictor._read_checkpoint_snapshot`) sigue hasheando la instantánea exacta de bytes que deserializa `torch.load`; ese guarda vincula verificación y carga y no usa la caché. La huella de implementación de las evaluaciones (`implementation_provenance`) no incluye las funciones modificadas, de modo que las evaluaciones persistidas siguen siendo admisibles.

## Alternativas

- **Mantener el hash completo en cada verificación:** correcto pero cuesta segundos por petición y escala con el tamaño de los modelos.
- **Confiar solo en el hash persistido en la base de datos:** no detecta un archivo alterado en disco.
- **Cachear por ruta y `mtime`:** `mtime` se restaura con `os.utime`; insuficiente sin `ctime` e inode.
- **Calcular el hash una vez al arrancar:** no detecta cambios posteriores sin otro mecanismo de invalidación.

## Consecuencias

Medido en el contenedor local con los datos reales: la primera petición baja de 6,8 s a 2,8 s y las siguientes de 5,4 s a 0,9 s; el catálogo publicado y sus errores son idénticos. El costo restante en caliente proviene de la tríada, que reconstruye predictores lazy y deserializa sus componentes en cada petición; optimizarlo queda como trabajo condicional separado.
