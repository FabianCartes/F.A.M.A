# ADR 0040: Ficha técnica basada en datos explícitos, sin presets inventados

**Estado:** Aceptado. **Fecha:** 11 de octubre de 2026.

El historial reconstruía física de audio y taxonomía por nombres, imponía Focal Loss/AdamW y fabricaba tamaños de artefactos. Ahora conserva los hechos relacionales y obtiene física, clases, optimizador y pérdida únicamente de metadatos explícitos del checkpoint local. Si no están disponibles o son inválidos, devuelve campos desconocidos; el cliente y la ficha presentan «No disponible» sin completar defaults.

## Decisión y alternativas

- El registro relacional sigue proporcionando ID, nombre/versionado de presentación, métricas, learning rate, batch size, asociación y tamaño registrado. Los nombres amigables siguen siendo presentación legacy, no prueba de procedencia.
- La raíz configurada de checkpoints limita el archivo consultado; no se descargan pesos desde GCS. La lectura utiliza `torch.load(weights_only=True, map_location='cpu', mmap=True)`: hay deserialización de metadatos y objetos tensoriales, **no lectura solo de cabecera**, pero el almacenamiento de los tensores permanece mapeado sin cargarse entero para mostrar la ficha.
- Física completa válida y clases explícitas únicas/no vacías se muestran como declaradas. Los entrenamientos web nuevos guardan además el optimizador y nombre de pérdida efectivos en `hyperparameters`; no se deducen los históricos por arquitectura ni configuración ausente.
- `audio_specs`, `classes_count`, optimizador/pérdida desconocidos y tamaño no registrado/no accesible se representan con `null`; las clases desconocidas con `[]`. Se usa el tamaño positivo registrado en BD, o el tamaño local observado si aquel falta. Ninguno prueba disponibilidad actual o integridad del binario.
- El cliente tipado conserva la ficha enriquecida y sus `null`. La UI distingue ausencia de datos de valores conocidos iguales a cero, incluidas accuracy y pérdida. Sin sesión de BD, el historial no fabrica modelos de demostración.
- Se descarta mantener presets silenciosos: un modelo industrial con audio personalizado no puede describirse correctamente por su nombre. Se descarta añadir tablas/columnas o sidecars para esta unidad; no requiere migraciones ni reescritura de artefactos existentes.

## Consecuencias y límites

Un checkpoint ausente, corrupto, fuera de raíz, con metadatos inválidos o en un formato/runtime que no admita lectura mapeada deja sus datos técnicos desconocidos, **sin retirar el registro histórico**. No se recurre a una carga completa de pesos como fallback.

La consulta añade acceso local a los artefactos. No comprueba el SHA-256 registrado, no congela archivos contra cambios concurrentes ni certifica compatibilidad de red, capacidad de inferencia o calidad acústica. El tamaño de BD puede describir el artefacto registrado y no sus bytes actuales. PostgreSQL/GCS reales, GPU y navegador real quedan fuera de la verificación.

Interfaces públicas confirmadas: `TrainingService.get_history`, `trainingApi.getHistory` y `TrainingView` renderizada. Evidencia y límites operativos en [KANBAN.md](../KANBAN.md).
