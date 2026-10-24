# Subida de MP3 y rótulo de épocas del entrenamiento

Revisión del 23 de octubre de 2026, rama `fix/afinamiento-integral`. Corresponde al primer bloque previo a preparar particiones y respaldos; no cambia al bucket oficial.

## Comportamiento disponible

La subida acepta MP3 Layer III completos cuya duración de cabecera es aproximada. Se comprueban los límites de sus tramas y se decodifica en bloques con frecuencia y canales nativos mediante `miniaudio`, sin convertir ni reemplazar el archivo enviado. Se admiten etiquetas ID3v2 iniciales y etiquetas APEv2/ID3v1 finales. La duración registrada en PostgreSQL procede del decodificador elegido; el escaneo de metadatos durante la descarga utiliza el mismo criterio para MP3.

Un MP3 con una trama final cortada se rechaza con HTTP 422 antes de transferir cualquier archivo del lote. WAV, FLAC y OGG conservan su validación y comparación de muestras. Siguen vigentes los límites de tamaño, las subidas sin sobrescritura, la reparación del registro al reenviar un objeto idéntico y la distinción entre operación completa y parcial.

El indicador del gráfico individual de Entrenamiento usa el total de épocas del trabajo. Una ejecución de una época presenta «Punto 1/1» en vez de tomar las diez épocas ocultas de la configuración de ensamble. Las configuraciones de dúo/tríada conservan su tratamiento independiente. Esto complementa el ajuste anterior del [Dashboard](clases_de_audio_y_dashboard.md).

## Diagnóstico comprobado

Con SoundFile 0.14.0/libsndfile 1.2.2, `Canastero/50707.mp3` anunciaba 449720 muestras y devolvía 436608 al leer mediante SoundFile, tanto desde disco como desde memoria. Por tanto, la explicación anterior de una diferencia exclusiva de `BytesIO` queda corregida. Otros MP3 sin tabla de búsqueda pueden anunciar menos muestras y detener la lectura antes del final de su audio.

La biblioteca [mpg123 documenta que la longitud puede estimarse por el tamaño del archivo](https://www.mpg123.org/api/group__mpg123__status.shtml); la [implementación de libsndfile 1.2.2](https://github.com/libsndfile/libsndfile/blob/1.2.2/src/mpeg_decode.c) usa esa longitud y no siempre fuerza un escaneo completo. Se eligió una decodificación MP3 por bloques independiente de esa estimación, usando la interfaz pública de [miniaudio](https://github.com/irmen/pyminiaudio). No se relajó globalmente la comprobación de los demás formatos.

## Evidencia y reproducción

Se añadieron cinco pruebas HTTP: MP3 completo con longitud sobreestimada, trama final truncada, etiquetas APE/ID3v1, duración subestimada y coherencia entre subida/descarga. Los dos archivos de `backend/tests/fixtures/audio/` son silencio y un tono sintéticos de un segundo a 44.1 kHz, generados con SoundFile/LAME y sin su primera trama de tabla Xing; no contienen grabaciones de usuarios. Se conserva una excepción exacta de `.gitignore` para cada fixture.

Desde `backend`, con sus dependencias instaladas:

```powershell
$env:PYTHON_DOTENV_DISABLED='1'
$env:DATABASE_URL='sqlite:///:memory:'
.venv/Scripts/python.exe -m pytest tests/test_ingestion_upload_validation.py tests/test_ingestion_upload_integrity.py tests/test_api_ingestion_validation.py -q
```

Resultado final: **103 pruebas backend aprobadas**, sin omisiones. La regresión de interfaz y utilidades del gráfico pasó **46 pruebas**; TypeScript sin diagnósticos. ESLint conserva 23 errores `any` anteriores en el archivo de pruebas y una importación sin uso anterior en TrainingView; el nuevo caso no añade mensajes. No se presenta ese lint como aprobado.

Los cinco Canastero originalmente rechazados (`50707`, `44352`, `15290`, `59857`, `50705`) completaron el servicio público de subida con una base SQLite temporal y GCS simulado. Sus hashes originales permanecieron iguales. Esta comprobación no subió esos audios a ningún bucket real.

## Activación y límites

Se instaló `miniaudio` 1.71 en el entorno virtual y se declaró `miniaudio>=1.71,<2` en `backend/requirements.txt`. Otras instalaciones deben instalar las dependencias actualizadas antes de arrancar. Se sincronizó el código con las copias locales de pruebas y se reinició exclusivamente el backend 8010; `/ready` respondió `schema_current`. Frontend 3010 y proxy 5433 conservados. La sesión administradora, el dataset de doce audios y el modelo existente siguieron visibles.

No hubo migración SQL, modificación de permisos, carga nueva en GCS, entrenamiento nuevo ni cambio del perfil oficial. Los recibos anteriores conservan sus cortes históricos. [Recibo de esta revisión](../receipts/mp3_y_curvas_entrenamiento_20261023.json).

La validación no certifica etiquetas, calidad acústica ni que una grabación sin longitud original conocida no haya perdido tramas completas antes de llegar a F.A.M.A. Rechaza límites de trama incoherentes y errores detectados por el decodificador; no es una auditoría forense del audio. MP3 free-format y variantes de etiquetas no contempladas no quedan certificados por estas pruebas. No se modificaron otros lectores MP3 del entrenamiento o la inferencia.

## Orden siguiente

1. Preparar y versionar particiones desde la aplicación, con procedencia, hashes y control de originales/derivados; preservar los CSV históricos hasta una decisión explícita.
2. Implementar respaldo verificable y recuperación de checkpoints desde GCS.
3. Preparar directorios persistentes por entorno, recuperación administrativa, HTTPS/proxy y una restauración comprobada.
4. Inventariar los recursos oficiales y preparar el corte de datos/configuración. `fama-audio-records-2026` continúa sin cambios por este bloque.
