# Ajustes para autonomía investigadora y solicitudes de datasets

**Estado vigente — 24 de octubre, arranque oficial:** el nodo de `http://localhost:3010` usa `fama_oficial`, `fama-audio-records-2026` y `runtime/oficial`. Perfil completado mediante adopción del administrador histórico, recuperación de contraseña solicitada por el operador e inicio de sesión verificado. Super-Ensamble de aves predeterminado y cinco modelos individuales seleccionables; inferencia real acotada correcta. Los cinco audios históricos diferentes están versionados en GCS, con 1205 filas conservadas en el índice; catálogo SQL de 1220 objetos de aves, 1386 de motores y un audio histórico industrial. Pesos respaldados por contenido y verificados. Los contadores globales ahora recorren todo el bucket: 2646 objetos observados. Siguen pesos del ensamble industrial, respaldo SQL externo/retención y despliegue universitario con HTTPS y servicio estable. [Estado operativo y límites](conciliacion_catalogo_y_pesos_oficiales.md), [recibo actual](../receipts/catalogo_oficial_publicado_20261024.json). Los bloques inferiores conservan sus cortes históricos.

**Relevo vigente del 24 de octubre:** El operador trasladó la historia a `fama_oficial` y Codex confirmó igualdad de todos los campos y siete secuencias: 41 filas, cuenta/hash intactos, cinco modelos y 31 predicciones. El respaldo PostgreSQL 16 posterior también se restauró y verificó en un laboratorio retirado. `runtime/oficial` ya está vinculado al perfil: cinco pesos y un audio copiados con SHA-256 coincidente, sin datos de prueba; los cinco modelos cargan tras corregir el lector AudioCNN histórico. Hay un índice candidato privado de 1205 filas: 1200 audios coinciden con GCS por MD5/tamaño y cinco requieren elegir tratamiento. El operador confirmó las dos preferencias; siguen publicación/catálogo, audios, adopción y arranque; el perfil no está activado. [Estado y decisiones](conciliacion_catalogo_y_pesos_oficiales.md), [recibo](../receipts/traslado_historia_confirmado_y_pesos_20261024.json). Los apartados inferiores conservan sus cortes históricos.

**Relevo posterior del 24 de octubre:** contraseñas oficiales confirmadas por el operador; comprobador local probado con PostgreSQL sintético y proxy cotejado. Siguen logins reales mediante entrada oculta, identidad/perfil y migración de historia antes del corte. [Paso actual](preparacion_entorno_oficial.md#siguiente-paso-comprobar-acceso-desde-este-pc).

**Relevo del 24 de octubre:** roles oficiales ejecutados según confirmación del operador; ambos usuarios presentes en la API. Siguen contraseñas SQL, comprobaciones locales y perfil/traslado de historia; no hay corte oficial activado. [Paso actual](preparacion_entorno_oficial.md#siguiente-paso-asignar-contraseñas-sql).

**Relevo oficial del 23 de octubre:** equipo inicial confirmado como este PC, con traslado universitario posterior. El operador eligió reutilizar la instancia y Codex creó `fama_oficial`, con `fama_pruebas` conservada. Inventario y referencias/huellas de 1205 audios históricos comprobados sin publicación. Script de roles oficiales listo con ocho casos PostgreSQL; sigue ejecutarlo con el operador, asignar secretos y preparar perfil y traslado de historia/catálogo antes del cambio de uso. [Preparación oficial](preparacion_entorno_oficial.md). Los relevos fechados posteriores en este documento conservan su corte histórico.

**Política definida por el operador:** [ADR 0043](../adr/0043-autonomia-investigadora-en-datasets-asignados.md). El investigador asignado usa, aporta e incorpora por sí mismo. El administrador decide accesos; no revisa obligatoriamente cada audio o corrección. No se añade permiso de curador.

**Avance del 23 de octubre:** puntos 1–4 activos en pruebas y recorrido acotado del punto 5 verificado. Recorrido investigador acotado verificado: acceso concedido por el operador, descarga y preprocesamiento de diez audios, entrenamiento de una época/lote dos, predicción, corrección propia e incorporación SQL/GCS. La carga investigadora de un audio idéntico se omitió sin duplicarlo. El dataset tiene ahora once audios: diez MP3 originales y una copia WAV derivada para la prueba, no una observación independiente. El modelo quedó inactivo globalmente y su checkpoint solo está respaldado localmente. Siguen E8-04 (discrepancia MP3 disco/memoria), un rótulo del gráfico individual que aún puede indicar «Punto 1/10» pese a ejecutar 1/1, y la operación institucional de etapas 9–10. La prueba no acredita calidad científica, independencia por grabador, recuperación de desastres, GPU ni la suite global. [Bitácora](bitacora_acceso_e_instalacion.md); [recibo](../receipts/autonomia_recorrido_investigador_20261023.json).

## Orden de implementación

### 1. Corregir el inventario y las acciones de Gestión de audios

- Resolver E8-02: distinguir recuentos/tamaños locales y del bucket actual; usar «Solo local», «Solo en GCS» o un resultado de comparación comprobado. La mera existencia local o igualdad de recuentos no demuestra sincronización.
- Resolver E8-03: impedir descargar una colección ausente del bucket, tanto en la UI como en el servidor. Una consulta remota vacía no debe generar tensores ni crear un dataset SQL como efecto de una descarga supuestamente completada.
- Ofrecer el preprocesamiento local como acción explícita, utilizable sin una descarga nueva.

**Comprobación:** bucket de pruebas vacío y colecciones locales no muestran audios en nube ni permiten descargar; el preprocesamiento local se ejecuta únicamente cuando se solicita.

### 2. Ofrecer la subida desde la interfaz

**Refinamiento del 23 de octubre:** selector con clases del dataset y alta nueva explícita implementados; selección enviada por su identidad exacta. Dashboard ajustado para reflejar carga y métricas por época. [Guía](clases_de_audio_y_dashboard.md).

- Añadir selección de audios, dataset de destino y clase, con límites, avance y resultado de carga.
- El investigador solo puede aportar a datasets asignados; el administrador conserva el acceso global y el alta de datasets que ya permite su API.
- Validar formato y nombres, tratar duplicados/reemplazos de forma explícita y mostrar éxitos parciales sin atribuir a SQL o GCS una escritura no confirmada.
- Registrar dataset y audios aceptados en PostgreSQL para que aparezcan en asignaciones; no hace falta una cuenta de Google por investigador.

**Comprobación:** una carga permitida aparece con origen y registro correctos; una carga a un dataset no asignado se rechaza en el servidor aunque se evite la UI.

### 3. Completar corrección e incorporación autónomas

- Distinguir «Guardar corrección» de «Revisar e incorporar» y ajustar los mensajes que sugieran revisión obligatoria por otra persona; ambas acciones son operables por el investigador asignado, incluso sobre su propia propuesta. La revisión no exige administrador ni segundo revisor.
- Terminar la integración de audio/clase/origen en el catálogo SQL al incorporar, además del feedback y su intención de sincronización existentes.
- Mostrar de forma separada incorporación local confirmada, registro SQL y copia GCS pendiente/confirmada. Reintentar sin duplicar la incorporación.
- Registrar quién propuso y quién incorporó; no presentar aceptación humana como certeza de la etiqueta.

**Comprobación:** el investigador incorpora sin intervención administrativa, el registro persiste y una interrupción GCS no se presenta como copia cloud completada.

### 4. Añadir descubrimiento y solicitudes de acceso

- Mostrar un catálogo de metadatos de datasets disponibles con estado «Asignado», «Solicitar acceso» o «Solicitud pendiente». La fuente de identidades es el catálogo registrado, no una enumeración de carpetas privadas.
- Sin asignación no se ofrecen audios, archivos, modelos, predicciones ni operaciones del dataset.
- Persistir solicitudes pendientes, aprobadas y rechazadas, con solicitante, dataset, fechas y decisión administrativa; evitar duplicados pendientes.
- Añadir a Administración una bandeja de solicitudes. Aprobar concede la asignación y confirma la solicitud de forma consistente; rechazar no concede permisos. Mostrar la respuesta al investigador dentro de F.A.M.A.
- Preparar migración de esquema y permisos conforme al flujo de migrador/usuario diario. Su aplicación remota se realiza como paso controlado, no al abrir una vista.

**Comprobación:** descubrir y solicitar no habilita acceso; la aprobación sí lo habilita y la revocación vuelve a impedir las operaciones. Los eventos permiten atribuir cada decisión.

**Relevo operativo del 23 de octubre:** después de particiones y checkpoints, el nodo nativo ya utiliza almacenamiento persistente exclusivo en `runtime/pruebas` y ejecuta las fuentes originales. Se conservaron 29 archivos por hash y se verificaron la partición 8/2 y las copias del modelo. [Guía y límites](directorios_persistentes_por_entorno.md). El siguiente bloque es copia/restauración SQL en un destino separado; siguen recuperación del operador, configuración institucional, procedencia manual y clases históricas. El corte oficial aún no se ejecuta; el párrafo siguiente conserva el resumen anterior a este relevo.

### 5. Verificar el recorrido integrado y actualizar la guía

**Relevo del operador del 23 de octubre:** ya se comprobó la recuperación local de un administrador existente, con revocaciones y auditoría atómicas; [guía](recuperacion_emergencia_administrador.md). La comprobación vigente solo inspeccionó la cuenta real, conservando su contraseña. Sigue preparar el entorno y catálogo oficiales y cambiar con verificación acotada, una vez definido el equipo/acceso final. Los resúmenes inferiores conservan su fecha de corte.

**Relevo de recuperación del 23 de octubre:** la copia lógica real de PostgreSQL ya se recuperó y comparó en un destino local separado, sin cambios en origen ni GCS; [manual](respaldo_y_restauracion_postgresql.md). Sigue recuperación del operador y preparación de base/perfil/catálogo oficiales, seguida del cambio y comprobación acotada. Las políticas de copias del destino final y la evaluación científica mantienen sus alcances propios. Los resúmenes previos conservan sus cortes históricos.

Aplicar TDD por interfaces públicas HTTP/UI antes de cambiar producción. Cubrir inventarios mixtos, nube vacía, permisos por dataset, resultados parciales, reintentos y solicitudes concurrentes. Después recorrer con cuentas y activos de pruebas elegidos: solicitud → aprobación → carga/registro → descarga o preprocesamiento → entrenamiento → predicción → corrección → incorporación SQL/GCS. Las pruebas locales y las verificaciones reales conservarán evidencias y límites separados.

No se subieron las colecciones originales. La muestra elegida completó el recorrido, con una época/lote dos y posterior incorporación de un derivado WAV. La revisión posterior del 23 de octubre corrigió E8-04 y E8-11 con TDD, 103 pruebas backend/46 frontend y activación local de pruebas, sin cargas cloud nuevas. Véase el [detalle de MP3 y gráfico](validacion_mp3_y_curvas_entrenamiento.md). El bloque posterior ya permite preparar y seleccionar particiones versionadas desde la aplicación: 147 PASS/8 SKIP backend, 73 PASS frontend y guardado real de ocho train/dos val; [uso y límites](particiones_versionadas.md). El bloque siguiente también quedó comprobado: respaldo explícito del checkpoint en `fama-pruebas` y recuperación exacta en ubicación separada; [uso y límites](respaldo_y_recuperacion_checkpoints.md). Continúan procedencia manual, clases históricas, copias SQL y operación persistente. La etapa 8 sigue abierta por esos límites y las variantes no verificadas.
