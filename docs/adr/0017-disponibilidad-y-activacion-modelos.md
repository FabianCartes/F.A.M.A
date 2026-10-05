# ADR 0017: Disponibilidad y activación de modelos

* **Estado:** Aceptado
* **Área:** Catálogo de inferencia y refresco de Predicción

## Decisión

Reconciliar los modelos persistidos faltantes al atender `GET /api/models` y refrescar
Predicción al montar la vista, recuperar foco o volver visible. Publicar no activa:
se conservan predictores existentes y el predeterminado, sin escribir flags `activo` en BD.
El [manual](../manuales/manual_usuario_plataforma.md#611-disponibilidad-del-catálogo-y-activación)
distingue persistencia, publicación, activación e inferencia comprobada.

## Contexto

El [ADR 0016](0016-procedencia-y-persistencia-entrenamiento.md) reserva `completed`
para checkpoint, modelo y métricas confirmados. Esa persistencia no implica preparación
para inferencia ni incorporación al registro en memoria de un proceso ya iniciado.
El catálogo usa un registro por proceso; el worker no lo sincroniza al terminar.
`register_from_db()` en `training.py:1246` está dentro de `set_active_model()`, no del worker.

El modelo real 11 estaba persistido, con checkpoint presente y hash verificado antes
de la corrección, pero no aparecía en el catálogo. No se atribuye esa ausencia al UUID,
a la URI local ni a un checkpoint dañado. El catálogo corregido en vivo y la inferencia
real de ese modelo siguen sin verificarse; el diagnóstico previo no sustituye esa comprobación.

## Alternativas Consideradas

| Alternativa | Motivo para descartarla como solución de descubrimiento |
| --- | --- |
| Activación manual | Mezcla disponibilidad con cambio de selección activa/predeterminada; no debería exigirse para descubrir un modelo guardado. |
| Reinicio del backend | Interrumpe servicios y deja sin resolver el descubrimiento posterior en procesos ya iniciados. |
| Hook solo al terminar el worker | No recupera modelos antiguos y no sincroniza registros de otros procesos. |
| Polling del frontend | Añade consultas periódicas innecesarias; los eventos de entrada, foco y visibilidad cubren el retorno a la vista. |

## Alcance de la Reconciliación

- Consulta modelos en BD e incorpora solo los faltantes bajo su identificador persistido.
  No reemplaza instancias ya publicadas, duplica modelos ni elige un nuevo predeterminado.
- Resuelve el basename del localizador bajo la raíz física configurada de checkpoints.
  Rechaza escapes por symlink antes de deserializar; no descarga desde GCS.
- Inicializa el predictor diferido existente con deserialización CPU de metadatos una vez
  por publicación exitosa en el proceso. No construye aún la red de inferencia.
  No es lectura de cabecera ni garantía de cero asignaciones tensoriales; tampoco valida
  compatibilidad de inferencia ni comprueba el SHA registrado en cada GET.
- Devuelve HTTP 200 con modelos sanos y `publication_errors` sanitizados por archivo.
  Solo `database_unavailable` produce HTTP 503 en el contrato de publicación.
  `only_available` sigue siendo el filtro existente de almacenamiento, no de inferencia exitosa.
- La UI conserva selecciones válidas, descarta respuestas/errores tardíos y muestra avisos parciales.
  Mantiene el modelo ejecutado y las clases de feedback del resultado; no inventa opciones.

## Consecuencias

Cada GET añade lecturas de BD. La primera publicación paga el costo de deserializar
metadatos; los intentos fallidos pueden repetirse en consultas posteriores.
Los registros siguen siendo locales a cada proceso, no una sincronización global inmediata.
Una consulta fallida conserva el catálogo previo en la UI; un catálogo vacío no habilita inferencia.

La activación explícita mediante `POST /api/training/models/{id}/activate` permanece separada.
Su implementación confirma BD antes del intento de registro: no garantiza carga exitosa
ni atomicidad conjunta. La corrección no modifica ese orden ni convierte descubrimiento en activación.

La identidad local del dataset no prueba un destino canónico de incorporación GCS.
La reparación de modelos históricos y la verificación de almacenamiento siguen fuera de este alcance.
Después del despliegue autorizado, el operador vuelve a Predicción, selecciona el modelo
y prueba inferencia; no necesita reentrenar ni activar solo para descubrirlo.
No se efectuaron despliegue, reset, migración, cambios GCS ni entrenamiento real.

## Referencias de Implementación

- [API de catálogo y activación](../../backend/app/main.py): `list_models` y `activate_model`.
- [Registro por proceso](../../backend/app/services/registry.py): `publish_from_db` y `list_models`.
- [Predictor entrenado](../../backend/app/services/predictors/trained_predictor.py): inicialización diferida y carga de inferencia.
- [Entrenamiento y activación](../../backend/app/services/training.py): `set_active_model` y persistencia del worker.
- [Vista Predicción](../../frontend/components/views/PredictionView.tsx): refresco por eventos, selección y avisos.
- [Script de arranque](../../iniciar_fama.sh): admite `./iniciar_fama.sh --build backend frontend`;
  reconstruir y desplegar interrumpe servicios y requiere autorización operativa separada.
