# Glosario de F.A.M.A.

| Término | Definición |
| --- | --- |
| Modelo catalogado | Modelo que el investigador puede descubrir en el catálogo. Su presencia no demuestra disponibilidad de pesos ni una inferencia exitosa. |
| Disponibilidad de pesos | Confirmación de que los pesos requeridos están disponibles según la comprobación del modelo. No certifica compatibilidad, integridad ni calidad de clasificación. |
| Respaldo de checkpoint | Copia de los pesos registrados de un modelo conservada fuera del nodo. Su existencia no equivale a una restauración comprobada ni incluye por sí sola la recuperación de la base o de los audios. |
| Recuperación de checkpoint | Restitución local de los bytes esperados de los pesos de un modelo registrado. No designa al modelo como predeterminado ni acredita calidad de clasificación. |
| Inferencia comprobada | Ejecución exitosa de un modelo sobre una entrada concreta. No demuestra calidad general ni garantiza ejecuciones posteriores. |
| Activación | Designación explícita del modelo predeterminado. Descubrir, seleccionar o recuperar disponibilidad no constituye por sí solo una activación. |
| Alta inicial de administrador | Creación de la primera cuenta de administración a cargo del operador. No es registro público ni cambio de rol de una cuenta existente. |
| Identidad técnica del nodo | Cuenta que autoriza a la instalación a conectarse a los servicios de Google Cloud. No representa a un investigador ni concede por sí sola permisos internos de PostgreSQL. |
| Usuario SQL de aplicación | Identidad con la que el nodo opera diariamente en su base. Se distingue de las cuentas web y del operador que modifica la estructura de la base. |
| Operador de migraciones | Identidad autorizada para actualizar la estructura de la base en una operación explícita. Sus credenciales se conservan separadas de las de la aplicación diaria. |
| Instalación completada | Finalización persistente de la configuración de un nodo. Una caída de PostgreSQL o GCS no revoca esta condición ni autoriza otra alta inicial. |
| Autorización de instalación | Permiso temporal del responsable que controla el equipo para configurar su primera instalación. No es una sesión de investigador ni concede administración sobre una base ya utilizada. |
| Finalización pendiente | Alta inicial iniciada que aún requiere confirmar el cierre del nodo. Reanudarla conserva la identidad y las credenciales originales; no permite crear otro administrador inicial. |
| Disponibilidad operativa | Capacidad observada de atender operaciones con los recursos configurados. Es independiente de que la instalación haya finalizado. |
| Almacenamiento del nodo | Conjunto persistente de archivos locales perteneciente a un entorno de datos. Su pertenencia no implica que esté respaldado ni que pueda compartirse entre procesos o instalaciones. |
| Respaldo lógico SQL | Copia de la estructura y los datos de una base en un momento determinado. No incluye por sí sola archivos externos, identidades técnicas ni contraseñas de los usuarios SQL. |
| Restauración SQL verificada | Recuperación de un respaldo en otra base con comprobación de su estructura y contenido. No implica que las conexiones, archivos y permisos técnicos del nuevo nodo estén preparados. |
| Traslado de historia | Conservación de registros observados y sus relaciones en otro entorno preparado. No crea por sí solo autoría, asignaciones o procedencia que el origen no conoce. |
| Adopción de administrador existente | Reconocimiento explícito de una cuenta administradora activa para continuar la instalación con su identidad e historia. No es alta inicial, cambio de contraseña, ascenso o reactivación. |
| Revisión de esquema | Versión explícita de la estructura SQL, comprobada junto a sus tablas y restricciones. Un número de revisión aislado no acredita compatibilidad. |
| Sesión web | Acceso temporal y revocable de una cuenta autenticada. No implica autorización sobre todos los recursos ni propiedad de los trabajos ejecutados. |
| Suspensión de cuenta | Impedimento de acceso de una cuenta sin borrar su identidad, historia ni asignaciones. Reactivarla no recupera credenciales temporales revocadas. |
| Recuperación administrada | Restablecimiento de contraseña autorizado por un administrador tras verificar al destinatario. No equivale a registro público ni activación de una cuenta suspendida. |
| Recuperación de emergencia del operador | Restablecimiento de acceso de una cuenta administradora existente por el responsable que controla el servidor. Su autoridad técnica es distinta de una sesión web y no implica crear o ascender cuentas. |
| Admisión de acceso | Intento aceptado para evaluar credenciales o recuperación dentro de un presupuesto temporal. No implica autenticación exitosa ni concesión de permisos. |
| Cuota temporal de acceso | Presupuesto de admisiones para una identidad y operación durante una ventana. Agotarlo rechaza nuevos intentos temporalmente; no suspende la cuenta. |
| Evento de seguridad | Constancia mínima de una acción de acceso o administración, su resultado y las identidades verificadas. No contiene credenciales ni pretende describir todo el tráfico. |
| Limpieza de expirados | Eliminación controlada de credenciales temporales vencidas y registros que alcanzaron su retención. No equivale a borrar cuentas o historia de negocio. |
| Recurso asignado | Recurso cuyo acceso fue concedido expresamente al investigador. Haberlo descubierto en un catálogo no constituye una asignación. |
| Autonomía investigadora sobre un dataset | Alcance de una asignación que permite usar el dataset, aportar audios, corregir e incorporar aportes sin aprobación administrativa adicional. No concede acceso a otros datasets ni propiedad de trabajos ajenos. |
| Catálogo de descubrimiento de datasets | Conjunto de metadatos que permite conocer datasets disponibles y solicitar acceso. Descubrir un dataset no permite consultar u operar sus recursos restringidos. |
| Solicitud de acceso a dataset | Petición de un investigador para obtener una asignación, resuelta por un administrador. Mientras está pendiente no concede acceso. |
| Incorporación al dataset validado | Aceptación explícita de un aporte por una persona autorizada sobre el dataset, que puede ser su propio autor. No certifica por sí sola la corrección científica de la etiqueta. |
| Propietario de entrenamiento | Usuario que inició un trabajo. Compartir acceso al dataset no convierte a otro investigador en propietario del trabajo. |
| Procedencia autorizante de predicción | Asociación verificable de la predicción con su dataset de origen y autor. Un nombre histórico coincidente no basta para conceder acceso. |
| Metadatos acústicos registrados | Frecuencia y duración conservadas de una observación anterior. Su presencia no certifica el contenido actual, la calidad ni la aptitud del audio para entrenar. |
| Audio estructuralmente legible | Grabación con formato reconocido y muestras que el decodificador puede recorrer. No acredita clase correcta, calidad acústica ni utilidad para entrenar. |
| Referencia experimental histórica | Resultado conservado de un experimento anterior. No describe por sí solo las métricas, disponibilidad ni configuración actual de un modelo. |
| Versión de particiones | Selección identificada de grabaciones, etiquetas y asignaciones a entrenamiento o validación para un experimento. Añadir audios al dataset no modifica esa selección. |
| Grupo de origen | Conjunto de audios relacionados por una grabación, un derivado o un grabador conocido, que se conserva dentro de una sola partición. La falta de una relación registrada no demuestra independencia. |
| Confianza de predicción | Valor reportado por el clasificador para una salida concreta. No equivale a certeza diagnóstica ni a exactitud general demostrada. |
| Carga observada | Instancia de modelo presente en la memoria del entorno observado. No acredita activación global, vigencia del archivo de respaldo ni inferencia correcta. |
