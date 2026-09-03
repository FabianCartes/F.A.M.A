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
* Cuando se tomen decisiones arquitectónicas o de diseño relevantes, registrarlas mediante ADRs (*Architectural Decision Records*) en `docs/adr/`.
* Mantener un glosario de términos y conceptos clave si el proyecto lo requiere (`CONTEXT.md`).

---

## 4. Validación Crítica y Grilling
* **Skills de referencia:** [`grill-me`](.agents/skills/grill-me/SKILL.md) y [`grilling`](.agents/skills/grilling/SKILL.md)
* Antes de implementar cambios estructurales grandes o refactorizaciones complejas, someter las ideas a escrutinio: evaluar casos de borde, trade-offs de rendimiento, acoplamiento y alternativas más sencillas.

---

## 5. Búsqueda y Extensión de Skills
* **Skill de referencia:** [`find-skills`](.agents/skills/find-skills/SKILL.md)
* Cuando surja una necesidad especializada de herramientas o procesos, evaluar e incorporar skills disponibles en el ecosistema.
