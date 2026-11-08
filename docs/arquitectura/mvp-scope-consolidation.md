# Alcance del MVP y consolidación local

Se ejecutan únicamente los pasos 1–2 aprobados: definir el alcance y consolidar fuentes locales en commits verificables.
Base: `a76b2bf5c95ee8491ecc2c01866c08504aebadf5`, rama `feat/local-mvp`. No es una certificación de reproducción ni producción.

## Specs

- S1. Solicitud original: «con este cambio creo que ya estamos preparados para definir bien el area del mvp y que sea reproducible en otros equipos, haz la investigacion correspondiente y que cosas se deben commitear para que todo lo necesario este en github. esto como prepaso a produccion».
- S2. Autorización acotada: «hagamos hasta el 2. por ahora». Comprende el alcance del MVP y la consolidación de cambios locales; no la preparación de la receta portable, la prueba desde un clon limpio ni el despliegue.

### Alcance aprobado por referencia a los pasos 1–2

| Área | Incluido | Límite |
| --- | --- | --- |
| Acceso | Sesión y espacio privado por usuario. | Los secretos y la identidad del operador no son contenido Git. |
| Datasets | Importar ZIP, validar/rechazar/cancelar, consultar catálogo y audios, archivar. | Importar no prepara ni entrena; archivar no elimina físicamente. |
| Entrenamiento | Preparación explícita, entrenamiento y métricas para fuentes/arquitecturas admitidas. | Una preparación depende de perfil de audio, arquitectura, semilla y revisión; no hay entrenamiento automático. |
| Predicción | Catálogo, ficha, predicción e historial con modelos admitidos y artefactos disponibles. | Un nombre de modelo no acredita pesos utilizables ni calidad en otro dominio. |
| Feedback | Registro e incorporación revisada de audios. | Copia local y confirmación cloud son estados distintos. |
| Dominios | Conservar bioacústica y motores como capacidades separadas. | No intercambiar datasets, clases o modelos ni ampliar listas de admisión. |
| Perfiles | CPU como referencia propuesta; GPU y GCS opcionales explícitos. | Su instalación reproducible y aceptación en otro equipo quedan fuera de esta etapa. |

### Consolidación y preservación

- Incluir únicamente fuentes de aplicación ya implementadas, sus dependencias nuevas, pruebas y documentación pertinente; no diseñar funcionalidades nuevas.
- Revisar por separado el proxy GCS no rastreado: no pertenece automáticamente al MVP mínimo ni a esta consolidación de interfaz.
- Mantener secretos, audios, ZIP, pesos, bases, backups, logs, recibos crudos, diagnósticos temporales y envoltorios operacionales privados fuera de los commits.
- Conservar los datos y servicios activos. No ejecutar entrenamiento, inferencia, importaciones, cloud, Docker ni navegador como comprobación rutinaria.
- No push, PR, merge, limpieza, instalación de dependencias, migraciones reales, actualización de imágenes ni reinicios.
- No fabricar un nuevo RED para funcionalidades existentes: conservar la evidencia RED/GREEN previa y comprobar de nuevo los candidatos exactos. Cualquier corrección de comportamiento necesaria sí requiere reproducción/RED significativo antes del cambio.

## Tasks

- T1 | S1–S2 | route: parent documentation | done | Alcance/exclusiones definidos e indexados; lectura estructural de enlaces y límites. Commit: corte documental inicial, identificado en el Log posterior.
- T2 | S1–S2 | route: one read-only explorer over exact diff | in_progress | Explorer mw8hgrdr-19-716m asigna fuentes, pruebas y hunks compartidos a unidades coherentes; manifiesto/hash inicial preservado. Commit: evidencia en este documento.
- T3 | S1–S2 | route: parent scoped commit | pending | Consolidar sesión/sidebar y cierre de consulta con pruebas y documentación, separando unidades si corresponde. Commit: pendiente.
- T4 | S1–S2 | route: parent scoped commits | pending | Consolidar importación, resúmenes/progreso/rechazo e incorporación/fecha con pruebas y documentación; evitar commits incompletos. Commit: pendiente.
- T5 | S1–S2 | route: parent scoped commit | pending | Consolidar selección/preparación y presentación de dominios con sus pruebas y manual. Commit: pendiente.
- T6 | S1–S2 | route: parent checks and scoped assessment | pending | Verificar candidatos aislados, suite aplicable, tipos, lint acotado y build; registrar exclusiones/límites y cierre sin despliegue. Commit: pendiente.

## Delivery and verification

- Estrategia heredada: `feature-branch-chain`; continuar commits locales en `feat/local-mvp`, sin crear/publicar PRs. Las unidades se encadenan por dependencias; no revisar el acumulado de toda la rama como un solo candidato.
- Pronóstico inicial: más de 400 líneas autoradas en total; cada unidad incluye comportamiento, pruebas y documentación y procura un corte revisable de aproximadamente 400 líneas. No comprimir código ni omitir pruebas para cumplir el presupuesto.
- Base de esta consolidación: `a76b2bf`; registrar límites y conteos reales de cada corte después de la asignación de hunks. El historial anterior no se reescribe.
- Pruebas frontend: focales por unidad y suite completa final, TypeScript sin caché incremental, lint de superficies tocadas y build aislado Webpack con dependencias existentes. No modificar la copia frontend activa.
- Backend: usar el runner aislado existente con SQLite sintético, red bloqueada e inventario rastreado para la fecha de incorporación; no reabrir pruebas físicas o fallos de entorno terminales anteriores.
- Evaluación nativa por candidato cuando sea aplicable; su indisponibilidad no es aprobación. Verificación independiente solo si el diff concreto afecta un riesgo alto identificado, no por tamaño o por commitear código ya existente.
- Aceptación visual/manual, entrenamiento/inferencia real, GPU, GCS, PostgreSQL real, latencia y reproducción desde clon limpio no se afirman en esta etapa.

## Log

L1. Solicitud original: «con este cambio creo que ya estamos preparados para definir bien el area del mvp y que sea reproducible en otros equipos, haz la investigacion correspondiente y que cosas se deben commitear para que todo lo necesario este en github. esto como prepaso a produccion».
L2. Autorización posterior: «hagamos hasta el 2. por ahora». El informe previo enumeraba 1) cerrar alcance, 2) consolidar cambios locales, 3) receta portable, 4) clon limpio, 5) recorrido funcional y 6) producción; solo 1–2 están autorizados.
L3. Preflight: HEAD `a76b2bf5c95ee8491ecc2c01866c08504aebadf5`, rama `feat/local-mvp`, índice vacío y 36 fuentes/pruebas/manuales rastreados modificados; once archivos nuevos de código/pruebas candidatos ya inventariados. No se han commiteado cambios en esta fase. Plantilla env previamente bloqueada permanece sin inspeccionar; no se vuelve a intentar. Documentación nueva bajo `docs/` conforme a las reglas del proyecto; no se crea otro directorio `odd/`.
L4. Documento de alcance creado con seis tareas e índice actualizado. No hay RED significativo para esta documentación pasiva; se verifica estructura, enlace existente y límites explícitos. Manifiesto privado initial-source-manifest.json: 36 archivos rastreados y nueve fuentes/pruebas nuevas a consolidar; proxy GCS y su prueba excluidos de esta etapa, no borrados. Diff exacto de 1764 líneas preservado en existing-source.diff; explorer mw8hgrdr-19-716m asigna únicamente esos cambios a cortes y no redescubre portabilidad. No se altera ninguna fuente de aplicación.
