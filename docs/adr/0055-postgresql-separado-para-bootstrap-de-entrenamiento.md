# PostgreSQL separado para el bootstrap de entrenamiento

Decisión aceptada: preparar un clúster PostgreSQL 16 independiente para el nuevo flujo de datasets importados, con volumen, red interna y credenciales nuevos. La aplicación y sus workers no se conectan durante el bootstrap. La base se creará desde `template0` y la CLI protegida comprobará nombre, OID e identificador del clúster antes de inicializar/verificar sus esquemas.

Reutilizar el clúster anterior ahorraría recursos, pero no permite atribuir sus escritores y privilegios existentes al procedimiento nuevo. La separación cuesta otro servicio y volumen; no aísla frente a administradores del host/Docker. No sustituir esta garantía limitada por una afirmación de exclusividad absoluta.

El runner de bootstrap utiliza únicamente la lista explícita de fuentes de `backend/bootstrap/source-files.txt`, sin arranque de la aplicación, ML, datos ni credenciales cloud. No construir desde el checkout completo ni reutilizar la imagen del runtime anterior. La dependencia de evaluación incluida solo verifica su esquema, no ejecuta evaluación.

Crear/inicializar los recursos nuevos fue autorizado. La activación como base principal, el arranque de la aplicación, la importación real, el entrenamiento y GCS siguen fuera de esta operación. El procedimiento y su evidencia pendiente se describen en [el manual](../manuales/postgresql-entrenamiento-separado.md).
