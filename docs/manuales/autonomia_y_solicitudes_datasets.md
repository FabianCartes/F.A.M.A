# Autonomía investigadora y solicitudes de datasets

Implementación en `fix/afinamiento-integral`, conforme al [ADR 0043](../adr/0043-autonomia-investigadora-en-datasets-asignados.md). **Activada en el entorno de pruebas el 23 de octubre de 2026:** Cloud SQL en `0003_autonomy` y procesos de backend/interfaz actualizados en 8010/3010. El [recibo de implementación](../receipts/autonomia_datasets_implementacion_20261022.json) distingue las pruebas aisladas de la [activación y carga reales](../receipts/autonomia_activacion_real_20261023.json). El recorrido completo investigador continúa en la etapa 8.

## Gestión de audios

El inventario separa **En este equipo** de **En GCS**. «Solo local» indica que se encontraron audios en el equipo y ninguno en el bucket consultado. «Local y GCS» no certifica que el contenido coincida: se muestra «Contenido sin comparar». Cuando no se pudo consultar GCS se informa esa incertidumbre; no se muestran ceros como si fueran una comprobación remota.

- **Descargar desde GCS:** se habilita únicamente para una selección con audios observados en nube. El servidor también rechaza un dataset sin audios descargables. Una descarga vacía no preprocesa archivos locales ni crea un dataset SQL.
- **Preprocesar audios locales:** es una operación explícita y separada; requiere audios locales en todos los datasets seleccionados. Puede reutilizar tensores existentes conforme al preprocesador. No afirma que se hayan regenerado todos los tensores.
- **Subir audios:** elegir dataset, clase y uno o varios archivos `.wav`, `.mp3`, `.flac` u `.ogg`. Los límites efectivos provienen del servidor; el formulario los muestra y valida tamaño por archivo y por envío. El servidor valida además nombres, formato y decodificación.

Al seleccionar un dataset, el formulario ofrece sus clases existentes en un desplegable. Cambiar de dataset limpia la clase anterior; **Añadir una clase nueva…** permite un aporte a una categoría nueva. Un dataset sin clases informadas permite escribir su primera clase. Ver [selección de clases y Dashboard](clases_de_audio_y_dashboard.md), incluida la distinción entre evitar variantes nuevas y revisar variantes históricas.

Un investigador aporta únicamente a sus datasets asignados. Un administrador también puede elegir **Crear un dataset nuevo** y escribir su nombre. Los audios aceptados se registran en PostgreSQL para que el dataset aparezca en asignaciones. El origen del acceso es la sesión de F.A.M.A.; no se pide una cuenta GCP a cada investigador.

La subida nunca reemplaza silenciosamente un objeto existente. Si el mismo nombre y clase ya contienen otro audio, se muestra el conflicto; elegir un nombre diferente para conservar ambos. Repetir una carga idéntica reconoce el objeto existente y puede confirmar/reparar su registro SQL sin transferirlo otra vez. Los resultados separan subidos, ya existentes y fallidos. Tras un resultado parcial con SQL confirmado se conservan los fallidos; si SQL no queda confirmado se conserva la selección para reintentar. No se registra un dataset vacío cuando todos los archivos fallan. El registro conserva hashes y un evento de aporte atribuido a la sesión.

## Corrección e incorporación

En Predicción, **Guardar corrección** registra la propuesta. En Gestión de audios, **Revisar audios → Incorporar al dataset** realiza la aceptación humana explícita. El investigador asignado puede incorporar su propia propuesta; no exige administrador ni segundo revisor.

La incorporación verifica y publica audio/CSV locales y confirma, en una transacción SQL, el audio/clase/metadatos, los contadores del dataset, el feedback procesado y la intención de sincronización. Una respuesta de error no debe interpretarse como confirmación: la misma intención permite reintentar tras una interrupción. Los estados muestran por separado **Incorporado localmente**, **Registrado en PostgreSQL** y **Pendiente de copia cloud / Copia cloud confirmada**. Una interrupción de GCS no impide aceptar localmente; el worker conserva la intención y sus reintentos.

Se distinguen el autor de la propuesta y el de la incorporación. La migración no atribuye a otra persona las incorporaciones históricas: sus campos nuevos quedan desconocidos. Los registros históricos sin fila de audio comprobable se muestran como SQL sin confirmar. Una aceptación humana no garantiza la corrección científica de la etiqueta.

## Catálogo y solicitudes

En Gestión de audios, **Explorar datasets disponibles** muestra nombres, finalidad y recuentos registrados, además de **Asignado**, **Solicitar acceso** o **Solicitud pendiente**. Este catálogo consulta identidades SQL; no enumera carpetas privadas ni expone rutas de almacenamiento, audios, modelos o predicciones de datasets no asignados.

La solicitud se guarda sin conceder permisos. En **Administración → Solicitudes de datasets**, el administrador consulta pendientes y decisiones anteriores y elige **Aprobar acceso** o **Rechazar solicitud**. La aprobación confirma solicitud y asignación en la misma transacción. El rechazo no concede una nueva asignación. Una decisión ya confirmada no se puede cambiar por un reintento opuesto; se conservan los eventos de auditoría de cada ciclo. La persona puede volver a solicitar un acceso rechazado o revocado.

Solo hay una solicitud actual por persona y dataset; los envíos simultáneos no multiplican la solicitud ni la asignación. La bandeja conserva ese último ciclo; los ciclos anteriores quedan sujetos a la retención de Auditoría. Repetir una aprobación antigua después de revocar el acceso no lo restaura, y el resultado informa de que ya no existe asignación. Rechazar una solicitud tampoco revoca una asignación que se hubiera concedido por otra vía; la interfaz lo indica. La cuenta debe estar activa para aprobar. Los controles HTTP siguen aplicándose aunque se evite la interfaz.

## Activar la actualización en la instancia de pruebas

La revisión `0003_autonomy` añade `solicitud_dataset` y dos campos de autoría en `feedback_sync`. Conserva los datos existentes; no crea cuentas ni migra colecciones locales a GCS. El usuario diario continúa sin poder modificar `alembic_version` ni realizar DDL. Las migraciones no se ejecutan al abrir una vista o iniciar la aplicación.

1. Mantener abierto el Cloud SQL Auth Proxy existente, conectado a `proyectotesis-fama:us-central1:fama-postgres-pruebas` en `127.0.0.1:5433`.
2. Ejecutar en PowerShell:

   ```powershell
   Set-Location "C:\Users\fabia\Desktop\F.A.M.A\backend"
   .\.venv\Scripts\python.exe -m scripts.actualizar_autonomia_pruebas --apply
   ```

3. Introducir localmente la contraseña SQL de **`fama_migrador`**. El comando no la muestra ni guarda; no enviarla por chat. La entrada por tubería es una opción explícita para automatización y se prueba únicamente con credenciales sintéticas.
4. La confirmación esperada es `{"code": "autonomy_update_ready", "revision": "0003_autonomy"}`. El comando comprueba/migra el esquema y aplica el script actualizado de permisos dentro de una transacción de permisos. Es repetible. Si informa `runtime_permissions_unconfirmed`, el esquema puede haber quedado actualizado; los permisos aún requieren confirmar y se puede repetir el comando. Comunicar solo el código obtenido.
5. Después de la confirmación, Codex actualizará/reiniciará el backend de pruebas y la copia de interfaz en 3010, y comprobará sesión/permisos. Hasta ese reinicio no usar el entorno antiguo para nuevas operaciones: su comprobación de esquema puede dejar de estar lista tras migrar. El resto del recorrido real requiere elegir audios y artefactos compatibles y acotados con el operador.

El operador ejecutó el comando y comunicó `autonomy_update_ready`/`0003_autonomy`. Codex verificó el esquema y los permisos efectivos, reinició exclusivamente los servicios de pruebas y confirmó la sesión administradora conservada. La versión de migraciones sigue en solo lectura para `fama_app`; no tiene DDL. El asistente permanece cerrado (410).

## Recorrido real iniciado el 23 de octubre

El operador eligió diez audios de AvesChilenas en dos clases. Se creó `FAMA_Prueba_Aves` en `fama-pruebas`, con cinco audios de Canastero y cinco de Chucao, 3.849.209 bytes. Ambas cargas se realizaron por el formulario y confirmaron PostgreSQL. Se comprobaron los diez objetos, sus checksums MD5 frente a los originales y los SHA-256 SQL, dos eventos de aporte y cero asignaciones. Los archivos de origen se conservaron. [Manifiesto de la muestra](../receipts/autonomia_muestra_aves_20261023.json).

La primera selección MP3 recibió 422 antes de transferirse: al decodificar desde memoria se obtuvieron menos frames que los declarados, aunque la lectura desde disco completaba el recuento. Se seleccionaron otros archivos de las mismas clases que cumplen la validación actual; no se relajó esa validación. La discrepancia queda registrada como **E8-04, pendiente de diagnóstico y corrección con TDD**; no acredita por sí sola que los originales sean inválidos.

El plazo de login de 120 segundos ya está activo: una identidad sintética inexistente recibió cinco 401 y después 429 con 111 segundos restantes. Esta prueba consume cuotas diagnósticas y registra rechazos, sin crear cuentas, emitir sesiones ni agotar cuotas de cuentas reales. El vencimiento exacto al segundo 120 conserva su prueba aislada; no se esperaron dos minutos en la comprobación remota.

**Avance vigente del 23 de octubre:** Recorrido investigador acotado verificado: acceso concedido por el operador, descarga y preprocesamiento de diez audios, entrenamiento de una época/lote dos, predicción, corrección propia e incorporación SQL/GCS. La carga investigadora de un audio idéntico se omitió sin duplicarlo. El dataset tiene ahora once audios: diez MP3 originales y una copia WAV derivada para la prueba, no una observación independiente. El modelo quedó inactivo globalmente y su checkpoint solo está respaldado localmente. Siguen E8-04 (discrepancia MP3 disco/memoria), un rótulo del gráfico individual que aún puede indicar «Punto 1/10» pese a ejecutar 1/1, y la operación institucional de etapas 9–10. La prueba no acredita calidad científica, independencia por grabador, recuperación de desastres, GPU ni la suite global. [Evidencia del recorrido](../receipts/autonomia_recorrido_investigador_20261023.json).

- [Inventario real antes de la carga](../images/autonomia_inventario_real_20261023.png).
- [Bandeja real de solicitudes inicialmente vacía](../images/autonomia_solicitudes_real_20261023.png).
- [Muestra cargada: diez audios solo en GCS](../images/autonomia_muestra_cargada_20261023.png).

## Entorno de esta validación y siguiente paso

El backend local de pruebas está aislado en `.pytest_cache/stage8-live/backend`, con sus once audios y una copia del checkpoint. Se mantuvieron Cloud SQL `fama_pruebas`, bucket `fama-pruebas` y la configuración privada `backend/installation/cloud-pruebas/native`. El archivo de intención antiguo de la carpeta de trabajo original permanece intacto. El puerto 3010 usa asimismo una copia de fuentes; editar `frontend/` no actualiza esa copia automáticamente.

No compartir `data/raw` e intenciones entre bases de entornos distintos. Antes del despliegue se necesitan directorios persistentes exclusivos y respaldo/restauración del checkpoint. No tratar la caché de esta prueba como instalación institucional. Las particiones siguen siendo ocho/dos: incorporar un audio no reasigna automáticamente train/val ni convierte el WAV derivado en una observación independiente.

- [Incorporación con autoría y copia cloud confirmadas](../images/autonomia_incorporacion_real_20261023.png).
- [Particiones de la muestra](../receipts/autonomia_particiones_muestra_20261023.json).
- [Bitácora completa: intentos, correcciones y límites](bitacora_acceso_e_instalacion.md).

## Evidencia visual aislada

Las siguientes capturas usan los componentes nuevos y datos sintéticos en un servidor temporal, sin conexión a GCP. No acreditan actualización del entorno real:

- [Inventario y acciones locales](../images/autonomia_inventario_demo_20261023.png).
- [Catálogo con solicitud pendiente](../images/autonomia_catalogo_demo_20261023.png).
- [Bandeja administrativa](../images/autonomia_solicitudes_demo_20261023.png).
