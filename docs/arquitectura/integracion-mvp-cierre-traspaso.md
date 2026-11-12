# Integración MVP: traspaso para el cierre

Estado al 2026-11-12 y pasos pendientes para cerrar la integración de afinamiento integral en `mvp`. Contrastar con el checkout antes de actuar: este documento describe un corte, no prueba el estado posterior.

## Estado de las ramas

- Rama de trabajo: `feat/triad-presentation`; último commit de código `ec9e319`, seguido del commit de este traspaso. Árbol limpio.
- Va 26 commits por delante de `mvp`, contando este traspaso, y `mvp` es ancestro directo: la integración es un avance rápido (fast-forward) sin conflictos.
- Sin push ni PR. Push, PR y merge remoto son decisiones del responsable del repositorio.

## Trabajo cerrado en la rama

| Tema | Commits | Evidencia |
| --- | --- | --- |
| Historial: ficha técnica unificada y partición compartida de la tríada | `d959211` | Pruebas del historial |
| Pesos de tríada fijos desde el entrenamiento ([ADR 0082](../adr/0082-pesos-fijos-de-entrenamiento-en-triadas.md)) | `03e5404`, `e171961`, `bf411b1`, `fec1a43`, `0ce7f63` | [Plan](triada-pesos-fijos-plan.md), [recibo](../receipts/triada-pesos-fijos-cierre.json); verificador independiente S1–S6 sin bloqueantes |
| Predicción: retiro del aviso de SHA-256 coincidente, barra de desplazamiento del modal | `b24593e` | Vitest |
| Tooltips dentro de la pantalla (portal y posición fija), historial de predicciones adaptable a móvil, retiro de «Dispositivo de esta selección» | `6035747` | Vitest |
| Retiro del ID de predicción del historial | `049dd3d` | Vitest |
| Columna «Sincronizar» en el historial de entrenamientos; aviso «Sincronizar en ficha técnica» para tríadas | `671e39c`, `e695b26`, `c2ad381` | Vitest |
| Nombres largos de modelos y datasets en varias líneas | `6f203c7` | Vitest (clases CSS; sin medición de ancho real) |
| Etapa g, hallazgo 2: la interfaz exige una partición guardada para entrenar | `2f570e5` | Vitest; [plan g](integracion-mvp-g-base-integracion-plan.md) L15 |
| Etapa g, hallazgo 1: `get_prepared_data_dir` respeta `FAMA_RUNTIME_DIR` | `ec9e319` | Pytest; plan g L16 |

Últimas comprobaciones observadas: frontend 677 pruebas aprobadas, `tsc` sin errores, ESLint sin hallazgos nuevos (`PredictionView.tsx` conserva 2 errores y 1 advertencia previos). Backend: los módulos afectados pasan; la suite completa con pytest directo tiene unos 205 fallos ajenos que ya existían en la base (`storage`, `t8`, `compose`, entre otros), sin fallos exclusivos de esta rama en la última comparación.

## Pendiente, en orden

1. **Integrar `feat/triad-presentation` en `mvp`** con avance rápido, en local. Comprobar antes que `mvp` sigue siendo ancestro de la rama.
2. **Etapa g, T5 (Cloud SQL).** Hecho el 2026-11-12 sobre `fama-postgres-pruebas` ([recibo](../receipts/integracion-mvp-g-cloudsql.json), plan g L17–L18).
3. **Cierre de la etapa g.**
   - Verificador independiente de la etapa g.
   - Borrar la clave JSON de la cuenta de servicio `fama-pruebas-app` al terminar las pruebas que la usan.

## Opcionales

- **L14 del plan g y API de entrenamiento sin partición:** se conservan; quedan caracterizados en [límite 06](../limites/06_ruta_checkpoint_gcs_y_entrenamiento_sin_particion.md).
- **Tríada local sin evaluación conjunta:** la composición #1 (versión 2) de `fama_pruebas` no tiene intentos conjuntos y muestra «Esta tríada no tiene evaluación conjunta». Se puede conservar o borrar a mano (primero la fila versión 2 y luego la 1, con respaldo previo); ninguna predicción la referencia. No hay función de borrado en la aplicación.
- **Preparación por línea de comandos en un runtime:** resuelto. `python -m training.prepare_dataset` crea el almacén `--versions-dir` y sus padres ausentes, sin seguir symlinks ([manual](../manuales/versiones-preparadas-dataset.md)).

## Entorno local

- Backend nativo en `127.0.0.1:8000` con PostgreSQL `fama-g-pruebas-pg` (`127.0.0.1:5433`, base `fama_pruebas`). Arranque desde `backend/` con `PYTHON_DOTENV_DISABLED=1`, `FAMA_CONFIG_DIR=<instalación nativa>` y `FAMA_RUNTIME_DIR=<runtime>`; listo cuando `GET /ready` responde `schema_current`.
- Frontend con `NEXT_PUBLIC_API_URL= npm run dev` en `:3000`. Con un `NEXT_PUBLIC_API_URL` de otro origen, el cliente rechaza la API con «La API debe usar el mismo origen de la aplicación. Revisa la configuración del proxy.».
- Las migraciones están aplicadas hasta la 0007; esta rama no agrega migraciones.
