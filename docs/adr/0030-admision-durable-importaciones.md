# ADR 0030: separar importaciones y trabajos con admisión transaccional

Estado: implementación aditiva T2a; integración y ejecución del Corte 2 pendientes.
Fecha: 2026-10-16.

## Contexto

Una importación conserva el archivo recibido y la revisión presentada al usuario.
No puede representar a la vez la validación, la publicación y sucesivas
sincronizaciones con identidades y recuperaciones independientes. El candado
global de archivos del flujo HTTP actual tampoco coordina una reserva durable de
ejecución entre instancias de API.

## Decisión

Persistir los trabajos separadamente de las importaciones, con identidad
idempotente por propietario, importación, tipo y clave de operación. Guardar los
parámetros exactos y la identidad de revisión esperada. Un trabajo pendiente o en
ejecución ocupa capacidad; un estado terminal la libera transaccionalmente. Las
consultas no renuevan actividad ni leases.

Usar inicialmente una compuerta de base de datos: un `UPDATE` de su única fila
serializa las transacciones cortas de admisión antes de contar capacidad e
insertar. Un índice parcial además impide dos trabajos activos por importación.
La compuerta no se mantendrá durante hashing, decodificación, red o publicación
de archivos. La cola persistida será la fuente de verdad, no una señal en memoria.

La migración es explícita y aditiva. El límite global conserva el predeterminado
4 existente y el límite por propietario comienza en 1, ambos configurables. Es
admisión de ejecución, no cuota ni reserva física de almacenamiento.

## Alternativas

- `count()` seguido de inserción sin coordinación: permite sobrepasar límites y
  no satisface la admisión atómica.
- Contadores por propietario y global: permiten menos contención al crecer, pero
  introducen reconciliación adicional de reservas y estados terminales. No se
  justifican para el límite actual de cuatro trabajos.
- Broker externo o avisos en memoria como autoridad: añaden infraestructura o
  pierden operaciones admitidas tras una caída. Se difieren; un aviso podrá
  reducir latencia sin cambiar la autoridad persistida.

## Consecuencias y alcance

La compuerta centraliza solo transacciones breves, con coste de serialización de
admisiones, no exclusión prolongada de trabajos independientes. El índice y los
checks aportan defensas persistidas además del módulo de cola. Las filas
terminales retienen identidad y resultado para no ejecutar otra vez una solicitud
repetida; su política de retención se resolverá con limpieza posterior.

Esta entrega no cambia el contrato HTTP ni elimina aún `mutation.lock`. Tampoco
implementa reclamación, heartbeat, fencing ni el worker: los campos preparados
para ellos no acreditan esas garantías. La evidencia de procesos usa SQLite
privado, no PostgreSQL operacional. Véanse el [seguimiento](../arquitectura/large-zip-gcs.md)
y el [procedimiento](../manuales/trabajos-importacion-datasets.md).
