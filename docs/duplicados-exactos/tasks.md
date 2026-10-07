# Aprobación de feedback sin duplicados exactos

## Intención y alcance

Evitar que `FeedbackService.approve_feedback` incorpore bytes ya indexados en otra fila del mismo dataset, incluso si pertenecen a otra clase. El rechazo devuelve HTTP 409 y mantiene la retroalimentación pendiente, sin crear una intención local, audio, fila CSV ni entrada de sincronización.

Unidad de trabajo aislada en `fix/feedback-exact-duplicates`. La revisión y el commit quedan a cargo del orquestador; este documento no acredita aceptación RDD ni despliegue.

## Decisiones de implementación

- Comparar únicamente el SHA-256 del audio con `hash_archivo` del índice canónico local. Sin búsqueda cloud, hashes perceptuales, migración de esquema ni reparación histórica.
- Releer el índice dentro de `.metadata.lock` y mantener ese bloqueo durante la admisión y publicación. La resolución previa de clase no basta para detectar otra incorporación intercalada.
- Publicar la intención nueva solamente después de superar el control de duplicados. Las intenciones durables preexistentes se conservan para recuperación.
- Excluir únicamente el `file_path` del destino canónico exacto (`storage_class/feedback_ID.wav`) del control de duplicados. El replay sigue verificando identidad, audio y metadatos con los controles existentes.
- Un hash ausente no prueba duplicación; bytes distintos y hashes iguales en otro dataset no bloquean la aprobación. No se recalculan hashes históricos.
- Los archivos de bloqueo pueden crearse al intentar aprobar; no representan una intención ni una incorporación de audio.

## Checklist

- [x] Escribir primero pruebas de la interfaz pública para duplicados en la misma clase y en otra clase.
- [x] Observar RED por aprobación indebida, no por fallo de infraestructura.
- [x] Comprobar digest bajo el bloqueo antes de publicar intención/audio/CSV.
- [x] Verificar estado pendiente, cola vacía y preservación de audio e índice ante HTTP 409.
- [x] Proteger bytes distintos, hash ausente, aislamiento entre datasets y replay idempotente.
- [x] Simular una fila publicada entre la resolución de clase y la adquisición del bloqueo.
- [x] Ejecutar la suite enfocada autorizada e indexar este documento.
- [x] Verificación independiente de la suite enfocada: 73 aprobadas; estado Git sin variaciones antes/después.
- [ ] Revisión nativa RDD del commit de trabajo.
- [ ] Commit único autorizado, a cargo del orquestador.

## Evidencia reproducible

Comando ejecutado desde la raíz del repositorio, sin bytecode ni caché de pytest:

```bash
PYTHONDONTWRITEBYTECODE=1 /home/kevin/Work/fama/.venv/bin/python -m pytest backend/tests/test_feedback_local_approval.py -q -rs -p no:cacheprovider
```

| Etapa | Resultado observado |
| --- | --- |
| RED, antes de cambiar producción | 2 fallidas y 70 aprobadas; ambos duplicados fallaron con `DID NOT RAISE HTTPException`. |
| GREEN, implementación mínima | 72 aprobadas. |
| Triangulación, relectura bajo bloqueo | 73 aprobadas, sin omisiones, en 1,39 s. |

No se ejecutaron suites amplias, servicios desplegados ni validación cloud. ASSESS devolvió `unassessable` porque el worktree contiene el documento de tarea aún no declarado; se trató como riesgo alto y se ejecutó self-verification más verificación independiente. La garantía depende del índice canónico y de escritores que respeten `.metadata.lock`; no detecta duplicados históricos sin `hash_archivo` ni similitud acústica.
