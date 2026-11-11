# Integración del capítulo 8 en Overleaf

Preparado el 4 de noviembre de 2026 a partir del PDF incompleto aportado por el autor y del checkout actual de F.A.M.A. Es un borrador académico revisable.

## Archivos y uso

- `capitulo_08.tex`: capítulo completo para la tesis. Incluye `\chapter`, introducción y las tres secciones de la pauta.
- `main.tex`: envoltorio de vista previa independiente. Fija capítulo 8 y página 62 solo para aproximarse al borrador recibido. No reemplaza el documento principal de Overleaf.

Para integrar:

1. Subir `capitulo_08.tex` al proyecto de Overleaf.
2. Reemplazar el contenido del capítulo 8 actual por este archivo, o sustituir su llamada por `\input{capitulo_08}`. Si se coloca en una subcarpeta, ajustar la ruta.
3. Conservar una sola declaración `\chapter` para este capítulo. No copiar el preámbulo ni los contadores de `main.tex` al cuerpo de la tesis.
4. Compilar el documento principal y revisar la numeración, el índice y la ubicación de las tablas con la plantilla real.

El cuerpo utiliza comandos estándar de LaTeX, sin bibliografía nueva, imágenes externas ni paquetes adicionales propios. La plantilla principal debe conservar su configuración habitual de español y codificación UTF-8. Las referencias `\ref` corresponden a las tablas incluidas en el propio capítulo.

## Criterios de redacción

- Se respetan los apartados solicitados: 8.1 Objetivo del Plan de Capacitación; 8.2 Fases del Plan de Entrenamiento; 8.3 Estrategia de Implantación y Puesta en Marcha.
- La capacitación es una propuesta. Seis fases y 300 minutos son una estimación editorial de planificación, no una actividad o resultado acreditado.
- «Entrenamiento» en 8.2 significa formación de personas. El entrenamiento de redes es una actividad enseñada dentro del plan.
- La puesta en marcha local documentada se distingue del despliegue institucional pendiente.
- No se afirma capacitación impartida, aceptación institucional, operación permanente, calidad científica nueva, cumplimiento de latencias ni disponibilidad de pesos industriales.
- No se incorporan correos personales, contraseñas, tokens, cookies, rutas privadas de credenciales o contenido SQL privado.

## Correspondencia de las afirmaciones operacionales

Las rutas siguientes son relativas a la raíz del repositorio. Se contrastaron documentos con los archivos de implementación pertinentes; los recibos respaldan solo sus observaciones históricas.

| Afirmación o tratamiento | Fuente de contraste |
| --- | --- |
| Estructura y tono del informe; capítulo 8 vacío | PDF incompleto de la tesis, proporcionado por el autor; páginas PDF 5 a 7, 14 a 18 y 68 a 73. Página impresa 62 para el inicio del capítulo 8. |
| Puesta en marcha local y límites del catálogo | `docs/manuales/conciliacion_catalogo_y_pesos_oficiales.md`; `docs/adr/0068-declaracion-explicita-de-ensambles-por-instalacion.md`. |
| Mantenimiento oficial, esquema 0004, catálogo y restauraciones | `docs/manuales/actualizacion_oficial_0004_20261025.md`; `docs/receipts/actualizacion_oficial_0004_20261025.json`. |
| Reanudación de servicios y límite del arranque permanente | `docs/receipts/restablecimiento_login_oficial_20261101.json`. |
| Segundo integrante: cuenta y permiso comprobados; Linux pendiente | `docs/manuales/instalacion_segundo_nodo.md`; `docs/receipts/alta_administrador_secundario_20261104.json`. La disponibilidad de archivos comunicada por el operador no se convierte en comprobación independiente de su equipo. |
| Asistente, adopción y arranque condicionado al esquema | `backend/app/entrypoint.py`; `backend/app/installation.py`; `backend/app/history_adoption.py`; `docs/adr/0058-configuracion-persistente-y-migraciones-explicitas.md`. |
| Identidad y bloqueo del runtime | `backend/app/runtime.py`; `docs/manuales/directorios_persistentes_por_entorno.md`. |
| Separación de identidades cloud, SQL y web | `docs/manuales/identidad_tecnica_oficial.md`; `backend/app/connections.py`; `backend/app/services/access.py`. |
| Particiones train/val/test y activación explícita | `backend/app/services/partitions.py`; `backend/app/services/training.py`; `docs/adr/0069-integracion-de-acceso-evaluacion-y-datasets.md`. |
| Capacidad ZIP condicionada por plataforma | `backend/app/routes/import_capability.py`. |

## Aspectos para acordar antes de presentar la versión definitiva

Confirmar participantes, responsable institucional, fechas de las sesiones y calendario de transferencia. Si la capacitación o la implantación institucional se realizan después, actualizar tiempos verbales y resultados únicamente con sus actas y evidencia.

La composición tipográfica de la vista previa aproxima el borrador, pero no reproduce una plantilla cuyo código fuente no fue proporcionado. Las cifras de precisión, las recetas de modelos, las mitigaciones de memoria y la terminología técnica de otros capítulos necesitan su revisión propia; este aporte no modifica esos capítulos.

## Verificación de la entrega

El proyecto independiente compiló correctamente con un compilador LaTeX integrado en el editor. También se comprobaron la existencia de una sola declaración de capítulo, las tres secciones solicitadas, la unicidad de etiquetas, la resolución de referencias internas y la suma de 300 minutos del plan propuesto. La revisión de diferencias de Git no informó errores de espacios.

La integración con la plantilla real de Overleaf queda sujeta a su compilación allí: se recibió el PDF, no el proyecto fuente de la tesis. La vista previa independiente conserva los archivos de contenido y no incorpora una nueva portada o bibliografía.
