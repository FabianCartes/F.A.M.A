# Preparación automática del dataset — MVP

## Flujo previsto

En Entrenamiento, seleccionar el dataset importado y la **Arquitectura de Red Neuronal** dentro del bloque de preparación; después pulsar **Preparar dataset**. El reparto objetivo es70% entrenamiento,15% validación y15% prueba. La preparación no inicia entrenamiento; **Iniciar entrenamiento** continúa siendo una acción independiente.

Hay un único selector de arquitectura para preparar y entrenar. Conserva EfficientNet-B0, ConvNeXt-Nano, ResNet-34d, PANNs-CNN14 y AudioCNN. En la fuente Legacy, el selector mantiene su ubicación y comportamiento anteriores. Los controles de física de audio y semilla no cambian de ubicación; siguen formando parte del perfil de preparación. La aplicación genera internamente el mapa de miembros y el perfil completo; no se solicita escribir JSON ni seleccionar snapshots/versiones antiguas.

Preparar solo procesa el perfil seleccionado: no prepara todas las arquitecturas ni descarga pesos. PANNs-CNN14 permanece disponible, pero en este flujo se inicializa sin pesos preentrenados y requiere al menos64bandas mel. Al cambiar arquitectura, audio o semilla, la interfaz deja de utilizar una preparación incompatible y bloquea el inicio hasta contar con una compatible; una respuesta antigua no debe restaurar la selección descartada. No hace falta volver a importar el ZIP y las preparaciones anteriores se conservan.

## Suposición de procedencia aprobada

Para esta modalidad, **cada WAV se trata como grabación y grupo independientes**. Los identificadores son estables por miembro y la procedencia registra `per-wav-independent-assumption-v1`. No se ha verificado independencia científica: si distintos archivos son recortes relacionados, pueden quedar en particiones distintas y producir métricas optimistas.

Los audios byte-idénticos que el importador omitió como duplicados no se reincorporan mediante esta preparación. Las clases deben tener suficientes miembros para aparecer en las tres particiones; el error debe identificar la restricción en lugar de publicar una preparación incompleta.

## Versiones y cambios

Snapshots y preparaciones permanecen inmutables. Tras recargar la página y volver a seleccionar el dataset, la interfaz muestra **«Ya preparado para entrenar»** y recupera su selección si el catálogo acredita una preparación vigente con el mismo perfil de audio, semilla, política70/15/15 y procedencia automática. No vuelve a solicitar preparación ni inicia entrenamiento. Si falta esa información o no coincide, mantiene **Preparar dataset**; no selecciona una versión histórica80/10/10 ni muestra un selector de versiones.

El catálogo comprueba propietario, revisión vigente, perfil y los manifiestos/índices de la preparación, sin recorrer todos los WAV. «Ya preparado» indica compatibilidad de esos metadatos; no acredita una comprobación nueva de todos los bytes de audio. Al pulsar **Iniciar entrenamiento**, la admisión vuelve a verificar la integridad completa de los audios y la coherencia de las particiones antes de lanzar el proceso. Un archivo ausente o alterado sigue impidiendo iniciar entrenamiento.

Solicitar la misma preparación puede reutilizar la versión determinista existente. Cambios de revisión, perfil o semilla requieren una preparación compatible. Las preparaciones históricas con el reparto80/10/10 y grupos explícitos conservan su política; no deben presentarse como70/15/15 por cambiar una etiqueta.

El aviso de revisión nueva se oculta cuando hay una preparación compatible lista, tanto recién creada como recuperada del catálogo. Si cambia el perfil o la semilla y deja de existir una selección compatible, el aviso puede mostrarse de nuevo mientras el catálogo indique `preparation_stale`. Este ajuste de mensajes no modifica revisiones ni preparaciones del servidor.

La retroalimentación pendiente o rechazada no incorpora audios. Una aceptación que sí cambia el dataset puede dejar obsoleta una preparación: preparar otra vez antes de iniciar un entrenamiento nuevo. Los modelos anteriores conservan su fuente histórica para inferencia.

## Aceptación manual

El usuario comprobará la interfaz sobre el entorno principal conectado; no se usa Playwright. Verificar una sola selección visible para el dataset importado, botón asociado a esa selección, mensajes de preparación/éxito/error y que preparar no inicia entrenamiento. Si se cambia de dataset durante una operación, una respuesta antigua no debe seleccionar la preparación anterior como si perteneciera al nuevo dataset.

**Estado de entrega de la preparación automática original:** desplegado en la aplicación conectada; salud y catálogo comprobados, prueba UI del usuario pendiente. La reorganización del selector también está desplegada en la copia del entorno manual de http://127.0.0.1:3000: los dos componentes coinciden con el checkout, hay respaldos verificados y la API conserva contenedor, imagen y hora de arranque. La comprobación del contenido servido pasó; una verificación independiente confirmó archivos, respaldos, preservación del panel de importación y respuestas HTTP200 de UI/API, sin inspeccionar los scripts servidos. La aceptación visual sigue pendiente del usuario; no se inició entrenamiento. [Recibo de despliegue](../receipts/automatic-preparation-deployment.json). Consultar el plan y su evidencia: [automatic-preparation-mvp-plan.md](../arquitectura/automatic-preparation-mvp-plan.md). Este manual describe el contrato, no prueba por sí mismo que la versión esté desplegada ni que un entrenamiento real haya finalizado.

## Archivos grandes y almacenamiento temporal

La preparación conserva el snapshot verificado y usa su almacenamiento privado para el segundo archivo temporal de validación WAV. Esto evita duplicar los audios grandes en el temporal global de128MiB; no reduce las verificaciones ni requiere borrar/reimportar el dataset. La corrección se validó con los1194WAVreales/15clases/8,52GB, sin publicar la preparación: la aceptación por UI sigue a cargo del usuario. [Recibo reproducible](../receipts/preparation-temporary-storage-runtime.json). El spool verificado de T1 también usa ahora almacenamiento privado, por lector simultáneo; el temporal global conserva el requisito del manifiesto, no de un WAV grande por validación. El almacenamiento privado necesita espacio de trabajo adicional por lector. Dos consultas simultáneas al catálogo real fueron verificadas con resultado200 y preparación elegible, sin crear ni modificar preparaciones. [Recibo concurrente](../receipts/snapshot-concurrent-spool.json).
