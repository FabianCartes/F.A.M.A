# Preparar el siguiente entrenamiento tras crecer un dataset

La aceptación revisada de un audio no inicia entrenamiento ni inventa sus grupos o
identificadores de grabación. Cuando cambia la revisión del dataset importado,
una preparación de la revisión anterior deja de ser elegible para **iniciar otro
entrenamiento**. El catálogo conserva visible el dataset y muestra el motivo
`preparation_stale`; el inicio devuelve ese mismo código con instrucciones.

Para continuar de forma manual:

1. Crear un nuevo snapshot de la membresía actual del dataset.
2. Completar explícitamente la procedencia de todos sus miembros, incluidos los
   audios incorporados: `recording_id` y `group_id`. No asumir independencia entre
   grabaciones por sus nombres ni asignar grupos automáticamente.
3. Preparar nuevamente las particiones train, val y test con esas anotaciones y
   el perfil de audio elegido. Todos los miembros deben quedar cubiertos, sin
   compartir grupos o grabaciones entre particiones.
4. Seleccionar la nueva preparación e iniciar explícitamente el entrenamiento.

Una anotación incompleta impide preparar la nueva cohorte. Crear un snapshot o
prepararlo no inicia trabajos automáticamente. Los perfiles de audio mantienen
sus validaciones existentes; este control no añade restricciones de arquitectura
ni resuelve limitaciones preexistentes de ensambles importados. Tampoco ejecuta
sincronización GCS ni acredita subidas remotas.

Los snapshots y preparaciones anteriores conservan su identidad y siguen
legibles. La resolución histórica usada por evaluación/checkpoints/inferencia no
exige coincidir con la revisión actual. El control nuevo se aplica solamente al
catálogo de elegibilidad y a la admisión del siguiente entrenamiento manual.
