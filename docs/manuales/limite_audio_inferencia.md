# Límite de carga de audio para inferencia

La implementación autorizada admite archivos WAV de hasta **100 MiB (104.857.600 bytes)** y configura un margen de **110 MiB por solicitud** en el proxy Next.js. El límite no garantiza duración, memoria ni tiempo de inferencia.

## Alcance y criterios de aceptación

- La interfaz rechaza archivos superiores al límite antes de enviarlos.
- El backend verifica bytes reales con lectura acotada y devuelve HTTP 413 JSON antes de GCS, inferencia y persistencia.
- La interfaz conserva errores JSON y maneja respuestas de texto, HTML o vacías sin mostrar errores de parseo.
- La capacidad del proxy incluye margen multipart; no reemplaza la validación del archivo.
- Sin despliegue, inferencia real, GCS, BD real ni modificación del audio de diagnóstico.
- Preservar cambios previos en `docs/KANBAN.md`. Rama: `fix/limite-audio-inferencia`.

## Seguimiento

- [x] AUDIO-LIMIT-1 — Implementar límites, mensajes y pruebas RED/GREEN en interfaces públicas de selección/inferencia y `/api/predict`. 38 pruebas frontend y 9 backend aprobadas por el escritor; commits locales autorizados por el usuario.
- [x] AUDIO-LIMIT-2 — Verificar el alcance modificado de forma independiente: pruebas enfocadas, build, transporte de proxy y Chromium aprobados. La suite completa conserva el fallo separado AUDIO-LIMIT-4.
- [x] AUDIO-LIMIT-3 — Revisión nativa aprobada y reconocida; autoridad consumida para el candidato congelado. Commits locales autorizados por el usuario; despliegue no autorizado.
- [ ] AUDIO-LIMIT-4 — Resolver el fallo preexistente de `IngestionSync.test.tsx:39`. Fuera del alcance autorizado; pendiente de decisión del usuario, no declarar la suite completa verde.

## Evidencia y restricciones

Diagnóstico: Next.js 16.3.4 registra límite de 10 MiB y `ECONNRESET`; la interfaz intentaba leer JSON antes de comprobar HTTP. `Colilarga.wav` pesa 51.125.318 bytes y dura 177,518313 segundos.

La implementación, las pruebas enfocadas, el build y el recorrido real del proxy se describen abajo. El fallo preexistente de ingesta queda separado del alcance; la revisión nativa fue aprobada y reconocida. El usuario autorizó commits locales de este alcance; no hay despliegue. La comprobación con el audio real requiere autorización aparte.

## Uso y límites operativos

| Capa | Contrato |
| --- | --- |
| Selección y captura WAV | Hasta 104.857.600 bytes inclusive; un archivo mayor se descarta antes de crear URL, decodificar o enviar. Se elimina la selección y el resultado previos. |
| FastAPI `/api/predict` | Cuenta bytes reales mediante lecturas de hasta 1 MiB, sin confiar en `Content-Length` ni `UploadFile.size`. Al exceder devuelve JSON 413 antes de GCS, predictor y persistencia. |
| Proxy Next.js 16.3.4 | `experimental.proxyClientMaxBodySize = 110 * 1024 * 1024` para el cuerpo multipart completo. No es `serverActions.bodySizeLimit`. |
| Respuesta HTTP | Conserva `detail` textual y mensajes estructurados conocidos; texto, HTML, cuerpo vacío o detalles desconocidos muestran HTTP/status sin inventar una causa. JSON de éxito inválido no crea un resultado. |

**No es una arquitectura streaming:** Starlette puede recibir y almacenar temporalmente el multipart antes de entrar al endpoint. El límite protege los efectos posteriores, no impide ese consumo previo de disco/red. El backend conserva hasta 100 MiB y la conversión a `bytes` puede duplicar transitoriamente ese buffer; GCS, temporales, decodificación y tensores agregan memoria. El navegador también decodifica el WAV completo. Varias solicitudes concurrentes multiplican el consumo: limitar concurrencia y medir RAM/disco/latencia antes de autorizar carga productiva. Duración, frecuencia, canales y codec pueden aumentar el costo aun bajo el límite.

Un proxy externo puede imponer límites o timeouts menores. Un HTTP 413 sin `detail` conocido no prueba qué capa lo originó. El margen multipart no autoriza archivos de 110 MiB.

## Evidencia TDD reproducible

Desde la raíz, ejecutar cada comando por separado:

```bash
cd frontend && npm test -- --run components/views/__tests__/PredictionView.test.tsx components/views/__tests__/PredictionView.catalogue.test.tsx
```

- RED selección: 1 fallo / 25 aprobadas; faltaba el mensaje y se intentaba decodificar el archivo excesivo.
- GREEN selección: 26 aprobadas.
- RED respuestas: 8 fallos / 28 aprobadas; errores de parseo, detalles estructurados y un JSON vacío tratado como éxito (fallo al renderizar historial).
- GREEN respuestas: 36 aprobadas; regresiones finales (confianza textual o fuera de rango): **38 aprobadas en 2 archivos**.
- Frontera exacta mediante `File.size` simulado: verifica comportamiento de UI, no transporte de 100 MiB.

```bash
cd backend && DATABASE_URL=sqlite:// ../.venv/bin/python -m pytest tests/test_prediction_audio_metadata.py
```

- RED HTTP público: 1 fallo / 5 aprobadas; el archivo excesivo devolvía 200, no 413.
- GREEN: 6 aprobadas; triangulación final: 9 aprobadas (7/8 bytes aceptados, 9/24 rechazados con umbral reducido a 8 bytes, recepción temporal preservada).
- `TestClient` sin lifespan, SQLite en memoria, registry/predictor/uploader falsos y supresión existente de dotenv. `Content-Length` falso y `UploadFile.size` no autoritativo; lecturas acotadas comprobadas. No hubo inferencia ni servicios reales.
- Avisos ambientales: prefijos del virtualenv y permiso denegado al caché pytest; no afectan las aserciones.

### Verificación independiente

- Backend: `cd backend && DATABASE_URL=sqlite:// ../.venv/bin/python -m pytest -p no:cacheprovider tests/test_prediction_audio_metadata.py tests/test_api_feedback.py`: **22 aprobadas**.
- Build: `cd frontend && NEXT_TELEMETRY_DISABLED=1 API_URL=http://127.0.0.1:49173 npm run build`: compilación, TypeScript y build de producción aprobados.
- Suite frontend completa: **234 aprobadas, 1 fallo**, en `IngestionSync.test.tsx:39` (espera `Feedback #7`, ausente en la fila). Repetición aislada: **6 aprobadas, 1 fallo**. Test, `IngestionView.tsx`, `FeedbackSyncPanel.tsx` y manifiestos npm no difieren de `HEAD`; atribuido como preexistente respecto al candidato, sin ejecutar un snapshot baseline. No se corrige fuera de alcance.
- Proxy de producción aislado con backend falso: archivo de **51.125.318 bytes**, multipart de **51.125.470 bytes**, HTTP 200; archivo de **104.857.600 bytes**, multipart de **104.857.752 bytes**, HTTP 200. Ambos cuerpos llegaron completos.
- Chromium/CDP: ambas comprobaciones finales aprobadas. Primer intento inconcluso por `NEXT_PUBLIC_API_URL` no aislada; reconstrucción con `NEXT_PUBLIC_API_URL=` y `API_URL=http://127.0.0.1:49173`, sin servicios productivos. Se confirmó `/`, encabezado `Predicción y Monitoreo Acústico`, modelo `Aves`, hidratación y selector WAV habilitado. Un WAV sparse sintético de **104.857.601 bytes** mostró el límite y produjo **0 POST**. Un WAV válido pequeño produjo **1 POST** al backend falso, cuya respuesta HTML 500 mostró `Error HTTP 500`, sin `Unexpected token`.
- `git diff --check` limpio, hashes de fuente/pruebas/configuración sin drift; procesos y fixtures aislados limpiados.
- Un intento de `npm test` desde la raíz falló por ausencia de `package.json`; ejecución corregida a `frontend/`.
- Preflight RDD sin autoridad nueva: selección de untracked rechazada por cambios concurrentes del inventario. Se excluyen configuraciones personales de Obsidian y no se leen ni modifican.

Las comprobaciones del alcance modificado pasaron; la suite completa conserva un fallo preexistente separado. No se realizó despliegue ni inferencia real.

### Revisión nativa

- RDD activo; riesgo medio, revisión consolidada `review-reliability`, 260 líneas lógicas congeladas y 9 rutas (incluye cambios externos preservados de `.gitignore` y `docs/KANBAN.md`).
- Linaje: `review-ece55680d6773d8c`; árbol candidato: `48495ac6d612756cc61da1a1f9807715f9bbed7c`; target: `sha256:dc4940ba0cb2b87dbf924bc0f9f951988f85167d88035f5e457707d235748810`.
- Resultado nativo: **approved**. Reconocimiento exacto completado: `native-approved-acknowledgement-completed`, autoridad **burned**, revisión consumida `sha256:23d495b20e796c3721ae731ca78f998203fbd38520b03960bc8a049b0a68f8c3`.
- Aviso `R3-001`, `PredictionView.tsx:649`, `WARNING`, disposición `informational`: no bloqueante, no abrió corrección. No se inventa detalle que el envelope no publicó.
- Esta actualización posterior solo registra el resultado en el manual; no modifica la fuente revisada ni extiende la aprobación a otros candidatos futuros. La revisión no autoriza commit, publicación ni despliegue.

## Activación y reversión (solo instrucciones; no ejecutadas)

Tras autorización operativa, seguir los requisitos de UID/GID y servicios del [manual Docker](./guia_despliegue_operativo_docker.md). Desde la raíz:

```bash
docker compose build backend frontend
docker compose up -d --no-deps backend frontend
```

**Reconstruir, no solo reiniciar:** el frontend incorpora configuración y `API_URL` durante el build. Cambiar variables al iniciar un contenedor existente no recompila rewrites ni este límite. Verificar destino y límites de proxies externos antes del build. No se afirma que el contenedor activo esté actualizado por este cambio de fuente.

La reversión se limita a las imágenes anteriores de backend/frontend y estos cambios de código/configuración/pruebas/documentación; no requiere migración de BD ni modificación de audios. No alterar `docs/KANBAN.md` ni otros cambios previos. Conservar el par frontend/backend coherente y comprobar salud tras una reversión autorizada.

## Próximo paso

Solicitar autorización operativa antes de reconstruir/activar backend y frontend y probar el audio real. Resolver el fallo de ingesta por separado si el usuario lo autoriza. Registrar los commits locales autorizados, sin push. El orquestador conserva la propiedad de los estados y casillas de seguimiento.
