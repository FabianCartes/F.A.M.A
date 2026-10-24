# ADR 0069: Integrar acceso, evaluación y datasets entre ramas

Fecha: 2026-10-24. Estado: aceptado por el operador para el reparto de tres grupos; integración comprobada en laboratorio sintético; despliegue pendiente.

## Contexto

`fix/afinamiento-integral` contiene instalación y sesiones web revocables, permisos por dataset y un esquema controlado hasta `0003_autonomy`. `dev` añade evaluaciones independientes, procesos de entrenamiento e importaciones ZIP con metadatos privados. Fusionar solo los conflictos textuales deja diferencias de autenticación, esquema y fuentes de entrenamiento.

## Decisión

Crear `0004_integration` como revisión aditiva y congelada, conservando las anteriores. No crear tablas al arrancar ni aplicar migraciones sobre Cloud SQL durante la comprobación de Git. Incluir marcadores de control de las colas sin confundirlos con datos institucionales durante el alta inicial o el traslado de historia. La aplicación diaria conserva DML limitado y solo lectura del número de revisión; los scripts de permisos enumeran las tablas actuales.

Las funciones ZIP del navegador usan la sesión HttpOnly existente y verifican el origen de las escrituras. Se conservan consumidores Bearer explícitos y el modo de desarrollo local de dev, con identidad reservada y condiciones originales. Las importaciones privadas siguen separadas del registro compartido de entrenamiento; no se inventan asignaciones ni migraciones de contenido.

Las nuevas particiones SQL/locales tienen entrenamiento, validación y prueba sin compartir grupos conocidos. El operador eligió este criterio. Las versiones 80/20 se pueden consultar, pero no se admiten como entrenamiento nuevo con evaluación estándar. Se conservan las preparaciones CSV verificadas de dev en Linux y se admite identidad de datasets propios. La evaluación final mantiene el modelo inactivo hasta una activación explícita del administrador, como en el flujo de acceso existente.

Los workers y el confinamiento ZIP requieren POSIX. Windows comunica esa capacidad como no disponible y conserva las rutas de audio, GCS, predicción y particiones locales. No se sustituyen sus bloqueos y protecciones por implementaciones vacías.

## Alternativas consideradas

Mantener dos sistemas de login duplicaría credenciales en el navegador. Crear las tablas automáticamente eliminaría la separación del usuario migrador. Entrenar con una versión 80/20 y reutilizar validación como prueba daría una evidencia final incorrecta. Emular las primitivas POSIX con operaciones sin bloqueo debilitaría el contrato de importación.

## Consecuencias

El despliegue del código integrado exige detener escritores, respaldar y aplicar la nueva revisión con el migrador; luego se aplican permisos y se verifica `/ready`. El servicio oficial anterior puede seguir con su código y esquema comprobados mientras se prepara ese mantenimiento. La revisión de Git y las pruebas sintéticas no acreditan una migración real, entrenamiento con datasets institucionales ni funcionamiento del worker ZIP en Windows.

Los ADR de acceso/instalación se renumeran 0052–0068 para conservar los 0034–0051 de dev. Los recibos históricos mantienen sus referencias al corte original.
