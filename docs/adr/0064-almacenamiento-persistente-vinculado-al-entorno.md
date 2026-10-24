# ADR 0064: Almacenamiento persistente vinculado al entorno

**Estado:** aceptado; implementado y activado en el nodo nativo de pruebas. **Fecha:** 23 de octubre de 2026.

El entorno de pruebas usaba una copia del backend bajo `.pytest_cache`, mientras varios consumidores seguían resolviendo archivos junto al código. Se adopta una raíz persistente explícita por nodo, conservada en su configuración de instalación, con audios crudos, derivados, particiones, checkpoints y logs separados del código. La raíz se vincula mediante una huella a la identidad de la base y el bucket; no incorpora contraseñas. Un nodo configurado no recurre a carpetas del repositorio cuando faltan archivos en su raíz.

El operador prepara una carpeta vacía y la selecciona mediante CLI, preservando el cierre del asistente y las referencias a secretos. No se incorpora automáticamente el contenido de carpetas históricas: el traslado es explícito, conserva los originales y comprueba hashes antes del nuevo arranque. Esto evita reproducir intenciones antiguas de corrección con IDs que pertenecen a otra base. Se descarta mantener copias ejecutables con datos dentro de cachés y multiplicar variables independientes para cada clase de archivo, porque permiten mezclar entornos accidentalmente.

La pertenencia a un entorno y la exclusión de otro proceso local son controles distintos. El nodo mantiene un bloqueo de la raíz durante su ejecución; no se presenta como coordinación distribuida ni como soporte de réplicas compartiendo un filesystem de red. Los arranques legacy sin raíz explícita conservan compatibilidad, pero no acreditan aislamiento operativo. La persistencia local tampoco sustituye copias de seguridad SQL/GCS ni la recuperación administrativa.

La identidad corresponde al destino configurado, no a un identificador de una instantánea SQL. Preparar el árbol y publicar el perfil no constituyen una transacción única; una interrupción requiere revisar los archivos conservados. Un conflicto de bloqueo entre la construcción de la aplicación y su inicio aborta el arranque, para no exponer rutas funcionales sin propiedad del árbol. El código ejecutable permanece en el repositorio y la caché frontend se separa por puerto.

El [manual operativo](../manuales/directorios_persistentes_por_entorno.md) y el [recibo](../receipts/directorios_persistentes_20261023.json) registran el traslado comprobado de 29 archivos y sus límites. La variante Compose solo fue validada como configuración.
