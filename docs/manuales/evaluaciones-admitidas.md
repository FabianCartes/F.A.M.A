# Evaluaciones admitidas en el catálogo

El catálogo público distingue la historia de los informes de la evidencia que la guarda de publicación admite para un modelo estándar.

## Interpretar la respuesta del catálogo

En `GET /api/models`, cada split puede incluir:

- `latest_attempt`: el intento más reciente, independientemente de su estado.
- `latest_completed`: el informe completado más reciente para ese split; es historia y puede no ser compatible con el runtime publicado.
- `admitted_completed`: el informe de ese split que forma parte del par val/test admitido por la guarda para el checkpoint y la configuración de runtime efectivos.

La guarda selecciona el par completo, no cada split por separado. Por ello, los informes aplicables de validación y test comparten la procedencia del mismo par. Los informes más nuevos que no corresponden a esa configuración permanecen visibles como historia, pero no reemplazan la evidencia admitida. Un intento fallido nuevo tampoco invalida un par completado previamente admitido.

`admitted_completed` solo aparece cuando la publicación estándar tuvo éxito y la guarda pudo validar ambos informes juntos. La publicación falla de forma cerrada si falta el par, si la configuración del predictor no corresponde, si la identidad de los manifiestos no es conjunta o si los informes no son coherentes. La respuesta conserva los códigos y motivos públicos acotados de esos rechazos; no incluye rutas locales del checkpoint.

## Modelos legacy y límites de la evidencia

Los modelos legacy o no estándar pueden conservar informes en `latest_completed`, sin `admitted_completed`. La interfaz los etiqueta como historia. Una coincidencia del SHA-256 identifica el archivo de checkpoint comparado; por sí sola no demuestra compatibilidad de configuración ni qué parámetros están cargados en runtime. Incluso un par admitido no constituye prueba continua de la instancia actualmente cargada ni una verificación de inferencia.

La lectura del catálogo es de solo lectura: no crea ni modifica evaluaciones, no agrega tablas ni ejecuta evaluación o inferencia. La selección repite la guarda canónica durante la publicación de cada solicitud; no conserva una decisión entre solicitudes ni usa una lista manual de modelos admitidos.
