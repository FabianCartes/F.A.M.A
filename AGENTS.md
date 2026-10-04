# Directrices de Desarrollo del Proyecto F.A.M.A

Este documento define los principios y flujos de trabajo obligatorios para cualquier tarea de diseño e implementación de código en este repositorio.

---

## 1. Metodología de Desarrollo: TDD (Test-Driven Development)
* **Skill de referencia:** [`tdd`](.agents/skills/tdd/SKILL.md)
* **Ciclo Red-Green-Refactor:**
  1. **Rojo:** Escribir siempre la prueba automatizada primero antes de escribir el código de producción. La prueba debe fallar por la razón correcta.
  2. **Verde:** Escribir el código mínimo necesario para hacer pasar la prueba.
  3. **Refactor:** Limpiar y optimizar la implementación asegurando que las pruebas se mantengan en verde.
* La superficie de pruebas debe corresponder a la interfaz pública del módulo, no a detalles internos de implementación.

---

## 2. Diseño y Arquitectura de Código (Deep Modules)
* **Skills de referencia:** [`codebase-design`](.agents/skills/codebase-design/SKILL.md) e [`improve-codebase-architecture`](.agents/skills/improve-codebase-architecture/SKILL.md)
* **Módulos Profundos:** Diseñar módulos con interfaces pequeñas y claras que oculten una complejidad significativa (evitar módulos "superficiales" que solo pasen llamadas sin aportar valor).
* **Costuras (*Seams*) y Adaptadores:** No crear costuras hipotéticas prematuras; una costura es real cuando existen al menos dos adaptadores reales.
* **YAGNI:** Evitar la sobre-ingeniería; priorizar el código que resuelve problemas concretos y probados.

---

## 3. Modelo de Dominio y Documentación de Decisiones
* **Skills de referencia:** [`domain-modeling`](.agents/skills/domain-modeling/SKILL.md) y [`grill-with-docs`](.agents/skills/grill-with-docs/SKILL.md)
* Mantener consistencia en la terminología del dominio del problema.
* Registrar solo decisiones arquitectónicas o de diseño con consecuencias relevantes mediante ADRs (*Architectural Decision Records*) en `docs/adr/`, con numeración secuencial de cuatro dígitos (continuar desde el último ADR existente).
* Mantener un glosario de términos y conceptos clave si el proyecto lo requiere (`docs/arquitectura/CONTEXT.md`).

---

## 4. Validación Crítica y Grilling
* **Skills de referencia:** [`grill-me`](.agents/skills/grill-me/SKILL.md) y [`grilling`](.agents/skills/grilling/SKILL.md)
* Antes de implementar cambios estructurales grandes o refactorizaciones complejas, someter las ideas a escrutinio: evaluar casos de borde, trade-offs de rendimiento, acoplamiento y alternativas más sencillas.

---

## 5. Búsqueda y Extensión de Skills
* **Skill de referencia:** [`find-skills`](.agents/skills/find-skills/SKILL.md)
* Cuando surja una necesidad especializada de herramientas o procesos, evaluar e incorporar skills disponibles en el ecosistema.

---

## 6. Organización y Destino de la Documentación

Toda documentación de proyecto que se redacte debe quedar bajo `docs/`. Elegir el destino por el contenido del cambio, no por la herramienta o el flujo de trabajo utilizado:

| Tipo de contenido | Destino exacto |
| --- | --- |
| Decisión arquitectónica relevante: contexto, alternativas, decisión y consecuencias | `docs/adr/` (ADR numerado secuencialmente) |
| Diseño de sistemas, componentes, pipelines y arquitectura MLOps | `docs/arquitectura/` |
| Informes de modelos, experimentos, métricas, optimizaciones y ensambles | `docs/modelos/` |
| Límites matemáticos o físicos, restricciones y problemas conocidos | `docs/limites/` |
| Instrucciones de uso, instalación, despliegue y operación | `docs/manuales/` |
| Memoria formal del proyecto de título y análisis de sus objetivos | `docs/tesis/` |
| Evidencia reproducible legible por máquinas (recibos JSON) | `docs/receipts/` |
| Diagramas, gráficos y matrices de confusión para los documentos | `docs/images/` |
| Tablero activo de tareas y seguimiento del proyecto | `docs/KANBAN.md` |
| Vista general de directorios e índice documental | `docs/README.md` |

* No crear ni usar `odd/` como destino documental ni abrir carpetas paralelas fuera de `docs/`.
* No esconder decisiones de diseño en informes experimentales; registrarlas en ADR y enlazarlas desde el informe cuando corresponda. No usar ADR para análisis experimental ni `docs/arquitectura/` para manuales operativos.
* Al introducir un documento o una categoría, actualizar la estructura y el índice de `docs/README.md` con su ruta y propósito.
* Son excepciones intencionales en la raíz `AGENTS.md`, `README.md`, `CONTRIBUTING.md` y los archivos cuya ubicación raíz exija el tooling. No trasladarlos a `docs/` ni usar esta excepción para nuevos informes del proyecto.
* Los docstrings y comentarios locales al código permanecen junto al código fuente. Estas reglas orientan documentos nuevos o actualizados; no implican reorganizar los existentes.

---

## 7. Convención de Mensajes de Commit

* Escribir en español todos los mensajes de commit nuevos, incluidos el alcance y la descripción. Mantener en inglés únicamente los tipos convencionales de Conventional Commits (`feat`, `fix`, `test`, `docs`, `refactor`, `chore`, etc.) y los identificadores técnicos que deban conservar su forma original.
* Usar el formato `tipo(alcance): descripción en español`, con una descripción breve que explique el resultado o propósito del cambio.
* Ejemplos: `fix(inferencia): evitar predicciones con pesos ausentes`; `feat(predicción): permitir seleccionar un fragmento de audio`; `test(registro): aislar las pruebas de modelos`.
