# ADR 0045: Respaldo explícito de checkpoints por contenido

**Estado:** implementado; respaldo real y recuperación separada verificados en pruebas. **Fecha:** 23 de octubre de 2026.

Un entrenamiento confirmado conserva pesos y métricas locales; eso no acredita una copia en GCS. Se añaden operaciones explícitas de consulta, respaldo y recuperación para modelos registrados de datasets asignados. El destino se deriva del SHA-256 registrado y del bucket configurado, sin aceptar rutas o buckets del navegador. Se conserva la referencia histórica SQL al fichero local y no se convierte el resultado de un entrenamiento en una promesa de respaldo automático.

El objeto se crea sin reemplazo y se verifica mediante descarga de su generación concreta antes de confirmar la transferencia. Recuperar comprueba tamaño y hash y publica sin reemplazar un fichero local existente; no activa el modelo. Se evita sobrescribir el checkpoint por nombre o confiar solamente en metadatos custom del objeto. La clave por contenido permite reintentos y evita colisiones de nombres, a cambio de depender del registro SQL conservado para reconstruir la asociación con el modelo. Este bloque no recupera por sí solo una base perdida ni una instalación completa.

Las copias con generación de GCS observable se distinguen de las transferencias cuyos bytes fueron comprobados. La interfaz consulta bajo demanda, sin recorrer objetos cloud en cada carga del historial. No se introduce cola automática ni migración SQL en este alcance. Los modelos históricos sin hash/tamaño verificables requieren revisión del operador; no se inventa su integridad.
