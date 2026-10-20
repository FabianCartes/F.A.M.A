# ADR 0041: Selección con disponibilidad de pesos confirmada

**Estado:** Aceptado. **Fecha:** 12 de octubre de 2026.

El selector podía elegir un modelo sin pesos, incluso por defecto, y el backend subía el audio antes de descubrir su indisponibilidad. Se mantiene el catálogo visible, pero solo una confirmación explícita de pesos permite seleccionar y ejecutar desde la UI; la solicitud HTTP vuelve a comprobar disponibilidad antes de leer/subir el audio.

## Decisión y alternativas

- `has_weights=true` habilita la selección; `false`, campo ausente o disponibilidad desconocida la bloquean. Las entradas permanecen visibles y deshabilitadas como «no disponible», en vez de ocultarlas y perder explicación del estado.
- Si el predeterminado no está disponible, se elige una entrada disponible. Al perder disponibilidad una selección, se prioriza otra disponible del mismo dominio. Si ninguna confirma pesos, no se inventa respaldo y se deshabilita inferencia. El refresco permite recuperación sin reemplazar otra selección válida ni alterar el resultado/feedback de una inferencia previa.
- `POST /api/predict` comprueba de nuevo `AudioPredictor.has_weights`, tanto para modelo explícito como predeterminado. Falta de confirmación o error del probe produce HTTP 503 sin subir a GCS ni registrar una predicción. Los errores del probe se sanitizan.
- Se descarta confiar únicamente en el catálogo: los pesos pueden perder disponibilidad entre GET y POST. Se descarta cargar la red completa para este preflight: la disponibilidad de almacenamiento y la compatibilidad de inferencia son comprobaciones diferentes.
- No se cambia la política de inclusión de modelos. Decidir catálogo exclusivamente relacional frente a ensambles estáticos sigue separado; se preservan los cambios locales previos de `registry.py`. La selección de UI no modifica activación en BD.

## Límites

La comprobación no reserva archivos ni elimina carreras entre verificación y lectura. Un checkpoint presente pero corrupto/incompatible, o un fallo posterior, puede descubrirse después de una subida; no hay compensación cloud ni transacción distribuida nuevas. No se descargan/reparan pesos ni se modifica GCS, datos o modelos históricos.

La UI distingue disponibilidad reportada de «pesos verificados» o inferencia garantizada. Los términos están definidos en el [glosario](../arquitectura/CONTEXT.md), y los resultados de pruebas en [KANBAN.md](../KANBAN.md). La validación usa adaptadores/HTTP controlados, no redes entrenadas, GPU ni servicios reales.
