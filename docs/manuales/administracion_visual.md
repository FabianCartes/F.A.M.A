# Administración visual de cuentas y acceso

**20 de octubre de 2026. Rama `fix/afinamiento-integral`.** Continuación de ACCESO-4A sobre las sesiones y contratos existentes de ADR 0052–0039. El cierre de pruebas y sus límites se registran en [KANBAN](../KANBAN.md).

## Mi cuenta

Todos los usuarios autenticados disponen de **Mi cuenta** en la navegación. Muestra nombre, correo y rol confirmados por el backend. El cambio de contraseña exige la contraseña actual, una nueva de 12–1024 caracteres y su confirmación. Las contraseñas se vacían al enviarse; no se guardan en storage.

Después de una respuesta 204 se vuelve a consultar la sesión. El backend revoca todas las sesiones al cambiar la contraseña; la interfaz retorna al login al confirmar esa revocación. Un fallo de transporte no garantiza que el cambio no haya ocurrido.

## Cuentas y asignaciones

Solo un administrador confirmado ve **Administración**. El backend conserva la autoridad de cada operación; la navegación no concede permisos.

1. Abrir **Administración → Cuentas y asignaciones**.
2. Consultar las cuentas en páginas de veinte y seleccionar **Administrar** sobre la persona correspondiente.
3. La cuenta seleccionada abre un panel con nombre, correo, rol y estado confirmados; la marca **Tu cuenta** identifica al administrador conectado. **Cerrar detalle** vuelve el foco a la cuenta de origen.
4. En **Perfil y estado**, modificar nombre, rol o estado. **Guardar cambios** se habilita cuando hay modificaciones; **Descartar cambios** restaura los valores guardados. El perfil conserva el borrador al pasar a otra opción de la misma persona. Cerrar el detalle, cambiar de persona o actualizar el catálogo descarta el borrador.
5. Los cambios de rol/estado muestran un aviso antes de guardar: cierran sesiones e invalidan recuperaciones pendientes del destinatario; no cancelan entrenamientos. El último administrador activo sigue protegido por el backend. Tras confirmar, el mensaje aparece junto a la cuenta y la tabla se vuelve a consultar.
6. En **Acceso a datasets**, cada tarjeta distingue el acceso permitido del acceso sin asignar. **Conceder acceso** y **Revocar acceso** se aplican al pulsarlos, independientemente del formulario de perfil. Los datasets se identifican por su ID persistido; los nombres se usan para presentarlos. Después de confirmar la escritura se vuelve a leer el inventario.

Para una cuenta administradora, esta última opción explica el **Acceso global por rol** y presenta el catálogo sin controles de concesión individual. Las asignaciones existentes se conservan; se usarán si el rol guardado pasa a investigador. Para una cuenta suspendida se aclara que sus permisos podrán utilizarse al reactivarla.

Las cuentas nuevas se crean desde el formulario lateral; el rol inicial propuesto es investigador. No hay registro público ni borrado físico de cuentas. Los administradores tienen acceso global; las asignaciones delimitan el acceso de investigadores.

**Alcance comprobado por lectura de código el 22 de octubre:** una asignación no es un permiso solo de lectura/entrenamiento. Las rutas de ingesta permiten subir audios a datasets asignados y las de feedback permiten aprobar/rechazar correcciones vinculadas a ellos; esas decisiones no están reservadas al administrador. El operador definió después que esa autonomía de uso, carga e incorporación forma parte de la asignación: no se exigirá revisión administrativa ni un permiso separado de curador. La política figura en el [ADR 0061](../adr/0061-autonomia-investigadora-en-datasets-asignados.md); sus ajustes pendientes, en el [plan](plan_autonomia_investigador_y_catalogo.md). El panel de asignaciones solo enumera datasets registrados en PostgreSQL. No existe todavía un catálogo general ni solicitudes de acceso para investigadores. Ver el detalle y límites en la [bitácora viva](bitacora_acceso_e_instalacion.md).

Actualizar o paginar el catálogo descarta el editor seleccionado para evitar conservar una edición basada en datos anteriores. Cambiar de persona aborta las lecturas previas y descarta su enlace de recuperación. Los errores HTTP no se convierten en estados de éxito ni muestran detalles internos del backend.

## Recuperación administrada

Abrir **Recuperar acceso** en el panel de la persona seleccionada. La explicación separa la emisión del enlace, su entrega manual y la elección de la contraseña por el destinatario. Verificar su identidad antes de emitir el enlace. **Generar enlace de recuperación** reemplaza la recuperación anterior y revoca sesiones, sin cambiar todavía la contraseña. La cuenta debe estar activa.

El enlace se presenta como texto seleccionable, sin navegación automática, almacenamiento local ni envío de correo. Se valida que pertenezca al mismo origen y a `/reset-password#token=...`. Se mantiene solo en memoria mientras permanece abierta la recuperación; se retira al ocultarlo, cambiar de cuenta/opción/sección, actualizar el catálogo o alcanzar el temporizador de presentación. Ocultarlo no lo invalida en el backend. Su vigencia real y su consumo único dependen del backend.

Entregarlo por un canal institucional seguro. Para la cuenta del administrador conectado se ofrece **Mi cuenta**, evitando emitir un enlace que revocaría la sesión desde la que se está mostrando. Un 429 bloquea temporalmente la emisión según `Retry-After`, sin reenviar automáticamente la petición.

## Auditoría y mantenimiento

**Auditoría y mantenimiento** consulta eventos con cursor y páginas de cincuenta. Muestra acción, resultado, fecha UTC e identificadores; no reconstruye nombres históricos ni incorpora cuerpos de solicitudes. **Más recientes** reinicia la consulta y **Eventos anteriores** utiliza el cursor confirmado por el backend.

La limpieza requiere marcar una confirmación explícita. Se propone un lote de 500 registros por categoría y se admiten enteros entre 1 y 1000. Solo solicita la eliminación de sesiones/recuperaciones/cuotas vencidas y auditoría que alcance la retención configurada. Conserva cuentas e historia de negocio, datasets, audios y modelos.

Se muestran los conteos devueltos y si quedan más candidatos. No se encadenan limpiezas automáticamente; cada lote adicional exige otra acción. No se ejecuta mantenimiento por abrir la pantalla.

## Lectura complementaria de asignaciones

Las operaciones individuales existentes no proporcionaban un inventario completo con IDs persistidos. Se añade `GET /api/access/users/{user_id}/datasets?limit=20&offset=0`, solo para administrador, con la política de sesión/origen/no-store existente.

Devuelve `user_id`, `datasets` (`dataset_id`, `name`, `assigned`), `total`, `limit` y `offset`. Solo consulta registros de la BD; no enumera GCS ni archivos locales, no crea asignaciones y no restringe el inventario a los dos datasets admitidos por el entrenamiento web. Límite máximo cien; usuario desconocido 404, paginación inválida 422. No requiere una nueva tabla ni sustituye las migraciones previas pendientes.

## Verificación y límites

Las pruebas de interfaz recorren la entrada real de la aplicación con HTTP simulado. Las del nuevo inventario recorren el router con cookies y SQLite temporal. Incluyen roles, mutaciones confirmadas, cambio de contraseña/revocación, recuperación efímera, errores, asignaciones, respuestas tardías, cursor y limpieza explícita. Resultados exactos en [KANBAN](../KANBAN.md).

Cierre: 115 pruebas backend aprobadas en cinco archivos; frontend completo 296 aprobadas en 29 archivos. Los 17 casos nuevos están incluidos en ese total; su ejecución focal posterior al refuerzo de una espera también pasó. TypeScript sin emisión/incremental y ESLint focal finalizaron sin diagnósticos. Las ejecuciones parciales anteriores no se suman como pruebas adicionales.

Rediseño de cuentas del 20 de octubre: navegación por tareas, borradores de perfil y distinción del acceso global incorporados mediante ciclos rojo/verde en la interfaz pública existente. Suite frontend: 299 pruebas aprobadas en 29 archivos. Tras ajustar la confirmación junto al formulario, los 20 casos administrativos volvieron a pasar. TypeScript y ESLint focal sin diagnósticos. Revisión visual y de navegación en el navegador local con cuentas sintéticas y backend de acceso aislado; no acredita servicios de audio, entrenamiento o GCS.

Unificación visual posterior: Mi cuenta y Administración adoptan los títulos, tarjetas, formularios, bordes y controles compactos de Gestión de audios y Entrenamiento. El espacio y el desplazamiento corresponden al contenedor común de la aplicación. Se verificaron visualmente ambas vistas con las cuentas locales de prueba; 28 pruebas de sesión y administración aprobadas en tres archivos, TypeScript y ESLint focal sin diagnósticos.

Se conserva el login y el fondo [SlicedWaves](acceso_web_y_sliced_waves.md) con sus parámetros y condiciones originales. No se cambian dependencias, secretos, cuentas reales, datasets, checkpoints ni configuración operacional. Las dificultades del sandbox para temporales y sockets internos de TestClient se distinguen de fallos funcionales.

Siguen pendientes setup protegido, configuración institucional GCS, recuperación de emergencia, Cloud SQL, migraciones/HTTPS/proxy/CORS y comprobación visual/E2E con servicios autorizados. Las pruebas DOM no certifican apariencia, WebGL real ni despliegue; Node 22.20.0 conserva la incompatibilidad de runtime documentada para jsdom.
