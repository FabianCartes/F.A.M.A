# Predicción y feedback por asignación

El recorrido MVP usa datasets estándar: publicar y asignar el dataset, entrenar con una versión de particiones, seleccionar un modelo accesible y enviar un WAV a `/api/predict`. El inicio de entrenamiento no garantiza que el modelo haya terminado, sido evaluado, publicado o activado.

El catálogo `/api/models` muestra modelos autorizados, incluidos ensambles declarados para la instalación. La disponibilidad de pesos no significa que se hayan cargado para inferencia. El administrador conserva el control de activación; la selección para una predicción no activa el modelo globalmente.

`GET /api/inference/history?model_id=…` devuelve predicciones atribuibles al dataset del modelo seleccionado, sin rutas ni audio. Use `limit` entre 1 y 20 y `next_cursor` para continuar; la respuesta se entrega con `Cache-Control: no-store`. El acceso depende de la asignación actual, no del propietario de una importación. Una revocación impide nuevas consultas y operaciones sobre el dataset.

Con almacenamiento local configurado se conserva una copia privada verificada del audio de la predicción; si no está configurado se conserva el flujo cloud existente. La creación de feedback requiere acceso a la predicción. La aprobación incorpora el audio al dataset y registra un estado de sincronización; no inicia entrenamiento ni sube automáticamente un checkpoint. El respaldo de checkpoints es una operación manual separada.

El catálogo privado y la revisión de pesos de composiciones importadas no forman parte de este recorrido. No se eliminan tablas, registros ni archivos históricos; su compatibilidad no está incluida en esta etapa.
