# ADR 0024: Entrenamiento aislado mediante spawn

* **Estado:** Implementado y verificado localmente con CPU y datos sintéticos.
* **Fecha:** 2026-10-15.

## Contexto

El worker en un hilo compartía los RNG de Python, NumPy y Torch con la API.
El candidato en proceso separado resolvía ese aislamiento, pero dependía del
sondeo HTTP para consumir progreso y no conciliaba siempre el evento terminal
con el código de salida. Un cliente desconectado podía dejar de drenar la cola.

## Decisión

Ejecutar el pipeline existente en un hijo creado con `spawn`. El padre conserva
la admisión y supervisa al hijo mediante un hilo dedicado, independiente de las
solicitudes HTTP. El transporte admite ocho eventos pendientes y aplica
contrapresión; el supervisor consume durante toda la vida del hijo, antes de
esperar su salida. No hay cola adicional de trabajos de entrenamiento.

La finalización requiere snapshot terminal, evento `finished` y código de salida
cero. Un snapshot `completed` no se expone como final hasta comprobar la salida.
Una salida anormal, incluso posterior a `finished`, produce `failed`.
`wait_for_completion(timeout)` espera la conciliación y liberación del proceso.
Si falla el arranque del supervisor, se termina y recoge el hijo que quedó sin
propietario; las cancelaciones normales siguen siendo cooperativas.

El hijo abre sus propias sesiones de BD. La configuración de conexión del
entorno debe ser accesible al proceso nuevo; una conexión SQLite en memoria del
padre no se comparte. Se conserva la fuente admitida y no se trasladan sesiones
ORM ni modelos vivos entre procesos.

## Cancelación y persistencia

La señal IPC se comprueba dentro del entrenamiento, tras validación y antes de
escribir el checkpoint. Si se observa después del registro durable y antes de
evaluar, se conserva el checkpoint registrado, pendiente e inactivo, sin crear
informes ni cambiar el modelo activo anterior. No se promete atomicidad entre
el filesystem y la BD ni reversión de operaciones ya confirmadas.

La evaluación iniciada conserva el contrato existente: `stop_training` admite
solicitudes mientras el estado es `training`, no mientras es `evaluating`.
Una cancelación concurrente posterior a la última barrera no revierte por sí sola
una publicación ya iniciada. No se cambia la política de activación automática
del principal tras informes estándar válidos.

## Alternativas y consecuencias

* Mantener el hilo era más simple, pero no aislaba el estado de RNG de la API.
* Drenar desde HTTP evitaba un supervisor, pero hacía depender el ciclo de vida
  de la presencia y frecuencia de sondeo del cliente.
* El proceso añade serialización, coste de imports y recursos IPC. La admisión
  sigue siendo local al proceso API: no coordina múltiples workers de servidor,
  no reanuda trabajos tras reinicio y no constituye un scheduler distribuido.

Se registran semilla, inicialización, runtime y modo de ejecución en el checkpoint.
Esto acredita procedencia; no garantiza reproducción bit a bit entre equipos CUDA.

## Evidencia

`backend/tests/test_training_spawn.py` comprueba nueve casos con procesos reales:
progreso abundante sin sondeo, salida anormal tras terminal, salida sin terminal,
cancelación cooperativa, rollback de arranque, RNG aislado y repetible, y pipeline
sintético con BD temporal en archivo, checkpoint e informes `val`/`test`, incluidas
cancelaciones durante validación y tras registro. La factoría externa del modelo
se sustituye por un clasificador diminuto; no se descargan pesos.

Véase [consolidación local](../manuales/consolidacion-worktrees.md) para los
comandos, resultados y límites de la verificación.
