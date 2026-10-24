# ADR 0047: Respaldo lógico y restauración SQL separada

**Estado:** aceptado; implementado y comprobado con respaldo de pruebas y restauración local separada. **Fecha:** 23 de octubre de 2026.

Se adopta un archivo PostgreSQL custom acompañado por un manifiesto privado de revisión, huellas por tabla y secuencias, obtenido con la misma instantánea exportada que utiliza `pg_dump`. Esto permite comprobar una recuperación concreta sin detener las lecturas/escrituras normales ni confundir un archivo generado con una restauración verificada. Si las secuencias cambian durante la exportación, el respaldo no se confirma y debe repetirse en una ventana sin altas. Se exige la misma versión principal de servidor y herramientas para mantener acotada la compatibilidad comprobada.

La CLI restaura únicamente en una base vacía de nombre distinto al origen. No usa `--clean` ni `--create`; la carga se ejecuta en una transacción y se compara con el manifiesto del respaldo, no con una base de origen que puede haber cambiado después. Las cuentas web y sus asignaciones forman parte de los datos conservados. Los roles globales SQL, sus contraseñas y las identidades IAM se preparan por separado; al restaurar se omiten propietarios y ACL del archivo para evitar aplicar automáticamente identidades del entorno anterior. Esa restauración de contenido no constituye por sí sola una instalación lista para operar.

Se conserva el respaldo en una carpeta privada con acceso local restringido, fuera del código versionado y de imágenes Docker. El manifiesto confirma coincidencia con el archivo producido, no autenticidad frente a un operador que altere ambos; se restauran únicamente archivos propios de origen confiable. Esta copia lógica y su ensayo local no sustituyen las copias administradas/PITR de Cloud SQL, una copia fuera del equipo ni la recuperación de audios, pesos y configuración.

El [manual](../manuales/respaldo_y_restauracion_postgresql.md) y el [recibo](../receipts/respaldo_postgresql_20261023.json) registran el resultado y la separación de permisos. El origen `fama_pruebas` se conservó; el ensayo no abrió un segundo servidor web sobre las cuentas recuperadas.
