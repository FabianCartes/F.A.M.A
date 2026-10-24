# Clases de audio y lectura del Dashboard

Actualización del 23 de octubre de 2026 en `fix/afinamiento-integral`.

## Elegir la clase al subir audios

1. En **Gestión de audios → Subir audios**, elige el **Dataset de destino**.
2. **Clase de los audios** muestra las clases informadas por el inventario de ese dataset, respetando sus nombres exactos.
3. Elige una clase y los archivos. Al cambiar de dataset se limpia la clase anterior para evitar enviarla al destino equivocado.
4. Si necesitas una clase que todavía no existe, elige **Añadir una clase nueva…**. En un dataset nuevo o sin clases informadas se escribe directamente la primera clase.

Al escribir una clase nueva, se eliminan espacios al principio/final y se reutiliza una clase existente si solo cambia el uso de mayúsculas. Si ya hay variantes históricas distintas, una coincidencia exacta conserva su identidad: seleccionar `chucao` envía `chucao`, seleccionar `Chucao` envía `Chucao`. Esta ayuda pertenece al formulario; no añade una restricción nueva a la API ni fusiona datos antiguos.

En la revisión real se observaron `Canastero`, `Chucao` y `chucao` en `FAMA_Prueba_Aves`. La unificación de las dos últimas requiere revisar audios y metadatos; no se hizo en este cambio. No se subieron audios durante la comprobación visual.

## Carga de métricas

El Dashboard consulta las métricas y la telemetría del equipo por separado. Las métricas se muestran cuando responde su consulta, sin esperar la respuesta de hardware. La primera consulta indica **Cargando métricas…**, con marcadores de espera en las tarjetas. La latencia de red y de PostgreSQL sigue existiendo; este cambio no garantiza una respuesta instantánea.

Si una consulta falla, se informa que los datos no están disponibles. Cuando ya existía una lectura, se conserva y se identifica como anterior. Los ceros registrados se siguen mostrando como ceros; un valor desconocido no se convierte en cero. No se añadió una caché compartida entre usuarios.

## Gráfico de convergencia

- **Sin épocas registradas:** aparece una explicación en lugar de un gráfico vacío.
- **Una época:** se muestran los puntos de precisión y pérdida centrados y se explica que hacen falta al menos dos épocas para observar evolución. No se inventa una línea de convergencia.
- **Varias épocas:** se muestran las observaciones y las líneas de precisión/pérdida registradas.

El gráfico aparece directamente al recibir las métricas. Se retiró la animación de revelado de 2,2 segundos que antes volvía a ocultarlo al actualizarse. Los valores y las épocas proceden de la respuesta del Dashboard; la presentación no ejecuta otro entrenamiento ni acredita calidad del modelo.

En la revisión real, el modelo tenía una época: precisión registrada 50 % y pérdida 11,6400. La incidencia pendiente E8-11 corresponde al rótulo «Punto 1/10» de **Entrenamiento**, no a este gráfico del Dashboard.

## Evidencia

- [Selector de clases](../images/subida_selector_clases_20261023.png).
- [Dashboard con una época](../images/dashboard_una_epoca_20261023.png).
- [Recibo de implementación y validación](../receipts/subida_clases_y_dashboard_20261023.json).

Comprobación: 56 pruebas aprobadas en tres archivos de interfaz (15 del flujo de ingesta, 34 de su vista y siete de Dashboard), TypeScript y ESLint sin diagnósticos en los archivos revisados. Es una regresión focal; no se reejecutó la suite global ni se modificó el backend.
