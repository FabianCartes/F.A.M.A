# Historial persistente de predicciones privadas

Implementación autorizada para modelos importados privados. Sin migraciones, nuevos audios ni estados de incorporación.

## Specs

- S1: «Confirmo» la propuesta: «esta primera versión cubriría tus modelos importados privados y sus predicciones locales verificables». Filtrar por sesión, asociación durable del modelo/dataset y referencia local canónica vinculada al mismo propietario. No basta el propietario del modelo. Excluir legacy y referencias ambiguas.
- S2: «solo hacer que muestre el historial». Mostrar fecha, archivo, clase y confianza del modelo exacto; páginas de 20, recientes primero; sin audio, rutas internas, feedback ni estados de incorporación.
- S3: «historial persistente de las predicciones del modelo seleccionado». Cargar al entrar/cambiar modelo, actualizar tras inferencia, impedir resultados obsoletos entre modelos/sesiones y conservar diseño/filtros. Los filtros existentes afectan los registros cargados.
- S4: «No he cambiado código ni datos. ¿Confirmas que implementemos esta primera versión para los modelos importados privados?» — «Confirmo». Implementación/pruebas autorizadas. Sin inferencia/entrenamiento real, GCS, browser automatizado, mutaciones operativas ni publicación Git.

- S5: «Autorizo para el despliege». Desplegar API y vista en el entorno conectado con respaldo validado y conservación de datos, checkpoints, configuración y recuperación. Sin ejecutar predicciones/entrenamientos nuevos ni GCS.

## Tasks

- T1 [done] S1–S2 | route: inline TDD, API pública sintética/SQLite | commit: no creado (índice y dependencias locales previas preservados). Risk: item 2 (nueva consulta privada).
- T2 [done] S2–S3 | route: inline TDD, vista pública React | commit: no creado (índice y dependencias locales previas preservados). API y UI son una unidad dependiente, no escritores paralelos.
- T3 [done] S1–S4 | route: comprobaciones integradas, verificador independiente, documentación | commit: no creado (índice y dependencias locales previas preservados). Preservar índice/checkout ajenos; no incluir sus cambios en commits.

- T4 [done] S1–S3, S5 | route: despliegue padre con baseline exacta, respaldo y smoke HTTP de lectura | commit: no solicitado. Risk: item 5 (reemplazo controlado de API y archivos servidos).

## Log

- L1: «Confirmo».
- L2: Alcance previamente confirmado: «sigamos con el plan anterior mejor, solo hacer que muestre el historial»; investigación solicitada: «Procede con la investigacion y arma el plan».
- L3: Investigación: PredictionView historial useState; Prediccion no tiene autor explícito. La escritura local de inferencia importada vincula el usuario autenticado a una referencia canónica; usar esa evidencia junto con asociación durable coherente, no atribuir filas legacy ni modelos públicos.
- L4: Rutas de prueba: HTTP autenticado de consulta + vista React; SQLite/CPU sintético, red/DB real bloqueadas mediante runner existente. No ampliar retención ni comprobar bytes de audios para listar metadatos históricos.

- L5: TDD backend: job30 RED HTTP404 → job31 6PASS; job35 80PASS (8 de historial + rutas vecinas). SQLite sintético/red bloqueada/30 rutas protegidas intactas. Frontend RED ausencia de registro restaurado → integración; fallos de fixtures/copy y tipos conservados en recibo.
- L6: Verificador independiente mw5b1z21-j-mtfs: 80 backend, 101 frontend y TypeScript exit0; S1 conforme, S2 bloqueante por actualización optimista, S3 parcial, S4 conforme. El padre reprodujo el registro erróneo99 en RED y corrigió el historial privado para usar exclusivamente la consulta persistida. Revalidación limitada mw5b8kh7-k-6r74, sin otra revisión completa.
- L7: Job42: suite completa frontend 469PASS/51 archivos y tipos exit0, incluyendo tres escenarios de respuesta no incorporable y prueba de401 tardío. No se ejecutó browser automatizado, DB real, inferencia real, entrenamiento, GCS ni despliegue. La comprobación AST/textual confirma que main.py solo añade el registro de la nueva ruta respecto al inicio de esta tarea.
- L8: Evaluación nativa no evaluable por alcance no declarado de archivos no rastreados; sin aprobación nativa. Escalado item2 exige verificación independiente. Lint/build no ejecutados; errores previos de lint no aprobados. Sin commit: preservar índice con trabajo previo y dependencias locales todavía no consolidadas; no incluirlas en un commit supuesto de esta tarea.

- L9: Revalidación independiente mw5b8kh7-k-6r74: S2 y brecha S3 cerrados, 9PASS/2 archivos/tipos exit0, sin nuevo barrido backend. Spot check del padre: mismas 9PASS/tipos0/diffcheck0. Implementación y verificación completadas; no desplegada. Detalles y hashes: docs/receipts/private-prediction-history.json.

- L10: «Autorizo para el despliege». Baselines comprobadas byte a byte: main.py activo coincide con respaldo previo a la tarea, PredictionView servido también; hashes del recibo verificado intactos. API vigente5b6a1f4f/image57cd822; despliegue limitado a main.py+nueva ruta y PredictionView+nuevo cliente.

- L11: Despliegue autorizado: build offline job43 y preflight job45 PASS, dump catálogo validado SHA301967cbcf418e30089e7a431b4767dc16b4d28bacadc977e89e8415b320fe6a. Job44 falló en comprobación aislada al usar UID predeterminado de imagen10001 en lugar del UID efectivo1000; única recuperación acotada cambió solo el UID del probe, sin permisos nuevos. Job46 reemplazó API y sirvió vista/cliente, pero el smoke web devolvió401. No se repitió ese despliegue.
- L12: Causa de401 reproducida por HTTP público sintético: la ruta usaba autenticación Bearer exclusiva; la sesión de navegador usa cookie. Corrección limitada a la nueva ruta para reutilizar imported_user existente, sin modificar helpers globales, proxy, origen ni reglas de credenciales conflictivas. RED cookie401 → GREEN job48 101PASS, independiente mw5d1nan-m-x2lk 29PASS y spot del padre13PASS. Advertencias de arranque SQLite por tabla usuario ausente conservadas en logs; sin acceso a DB real durante pruebas.
- L13: Datos comparados tras job46: todos los hashes de tablas legibles, checkpoints y audio privado iguales salvo usuario. Comparación COPY de usuario entre dump previo y estado actual (solo memoria, sin imprimir valores) confirmó únicamente ultimo_acceso de usuario1, actualizado por el login de comprobación. No se restauró ni corrigió ningún dato. Imagen de corrección offline job49 PASS: solo prediction_history.py cambia; aplicación final job50 en curso, sin recopia frontend.

- L14: Job50 exit0: API c79b6101/image2f20b3ab desplegada, mismo entorno/DB/IP/permisos/montajes. Cookie web200, anónimo401, modelo desconocido404, no-store y alias numérico/canónico coherentes; consultas repetidas idénticas. Historial real atribuible: modelo3 un registro, modelo4 cero. Frontend servido/hash/JS comprobados; ningún entrenamiento ni predicción nuevos. Todas las tablas legibles de negocio/checkpoints/audios privados iguales; usuario solo ultimo_acceso del login verificado contra dump. Dos API anteriores y respaldo conservados. Estado desplegado HTTP verificado; aceptación visual humana pendiente. Evidencia: docs/receipts/private-prediction-history.json.
