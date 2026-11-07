# GPU opcional para entrenamiento local

La aplicación ya elige CUDA si PyTorch la detecta y CPU en caso contrario. Este cambio habilita acceso GPU en el despliegue local existente, sin modificar el entrenador, los modelos, los datasets ni el esquema de base de datos. La configuración CPU se conserva por separado.

## Uso desde la interfaz

1. Abrir `http://127.0.0.1:3000` y comprobar que el indicador de hardware reconoce la GPU.
2. Seleccionar dataset, arquitectura y una preparación compatible.
3. Para la primera prueba manual de PANNs-CNN14 en una GPU de4GiB, usar un **batch size de1**. Los valores mayores no quedan certificados por la prueba sintética.
4. Iniciar el entrenamiento de forma explícita. Confirmar que el registro inicial indica `CUDA`.

Habilitar la GPU no inicia entrenamiento, no reanuda el anterior y no activa modelos. El tamaño del lote es un hiperparámetro de entrenamiento: cambiarlo no equivale a importar nuevamente el dataset.

## CPU y GPU son configuraciones de despliegue

| Configuración | Acceso a dispositivos | Comportamiento |
| --- | --- | --- |
| CPU conservada | Sin solicitud GPU; visibilidad CUDA vacía | El entrenador utiliza CPU. |
| GPU opcional | Runtime NVIDIA, una GPU seleccionada y dispositivo lógico0 visible | El entrenador utiliza CUDA cuando PyTorch la detecta. |

El fallback del entrenador solo se decide al iniciar el trabajo. No convierte un error CUDA o falta de VRAM en una continuación automática por CPU. Tampoco permite que Docker arranque una configuración que exige GPU cuando faltan el dispositivo o su runtime: en ese caso se debe desplegar la configuración CPU conservada.

No se ha añadido una dependencia obligatoria de GPU al código del backend ni se han cambiado los archivos Compose generales del proyecto. La configuración del equipo y sus identificadores de GPU permanecen en registros operativos privados, no en valores predeterminados de producción.

## Preservación y recuperación

El cambio conserva imagen, usuario1000:1000, raíz de solo lectura, `cap-drop ALL`, `no-new-privileges`, red interna, IP de conexión del proxy, límites tmpfs y configuración de logs. Los montajes de datasets, preparaciones, audios y checkpoints se reutilizan. La caché de pesos y el archivo de credenciales PostgreSQL permanecen de solo lectura; los indicadores offline no se deshabilitan.

El registro privado de esta operación está en `.optional-gpu-environment-qpk2clbr/`: contiene la inspección del contenedor CPU, los argumentos de creación CPU/GPU, archivos de entorno0600 y evidencia de verificación. El directorio es0700. No publicar, añadir a Git ni copiar su contenido a incidencias: incluye configuración sensible. Los JSON públicos contienen únicamente evidencia seleccionada sin credenciales.

La recuperación requiere comprobar que no hay entrenamiento ni evaluación activos, conservar la API GPU antes de sustituirla y recrear la API CPU con la imagen y montajes capturados. No arrancar un contenedor histórico ni restaurar una base de datos sobre datos posteriores. Este manual documenta la vía de recuperación; no autoriza una parada o rollback futuro ni afirma que se haya ensayado un failover del servicio activo.

No se necesita copiar todos los WAV ni migrar tablas para habilitar GPU. El inventario operativo registra tamaños, modos y marcas de modificación de archivos persistentes; añade SHA256 a checkpoints y archivos pequeños. No equivale a una verificación nueva de todos los bytes de cada WAV grande ni a un respaldo restaurado de toda la base.

## Pruebas y límites

La comprobación aislada usa la misma imagen, red deshabilitada, usuario no administrador, raíz de solo lectura y guardas conservadas. PANNs-CNN14 recibe un tensor sintético de forma `[1,1,128,94]`, derivada del perfil nominal32kHz/1,5s/128mel/hop512 del entrenamiento terminado. Se comprueban CUDA, salida de13clases, pérdida finita, backward y un paso Adam. La prueba limita el proceso al75% de VRAM. No accede a datasets ni persiste checkpoints o métricas de entrenamiento.

Esto no certifica calidad predictiva, velocidad por época, lectura real del dataset con GPU, otros tamaños de lote, sesiones concurrentes ni producción. La prueba de fallback CPU se ejecuta separadamente sin GPU, red ni datos. La verificación independiente y el estado final se registran en [el recibo GPU](../receipts/optional-gpu-environment.json); el seguimiento y los fallos observados están en [el plan](../arquitectura/optional-gpu-environment-plan.md).

Para producción se debe validar el hardware y controlador del destino, elegir explícitamente la configuración CPU o GPU y comprobar la carga de checkpoints con el dispositivo de destino. Este despliegue local no modifica ni aprueba el despliegue productivo.
