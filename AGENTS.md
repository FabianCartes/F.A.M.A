# Directrices de Desarrollo del Proyecto F.A.M.A

Este documento define los principios y flujos de trabajo obligatorios para cualquier tarea de diseño e implementación de código en este repositorio.

## Contexto y alcance

F.A.M.A. es un framework MLOps híbrido para clasificación acústica multidominio, con aplicaciones en bioacústica y diagnóstico acústico de motores. No asumir que los datasets, las clases o los modelos de ambos dominios son intercambiables.

| Área | Responsabilidad y referencias |
| --- | --- |
| `backend/app/` | API FastAPI, esquemas, servicios y persistencia de la aplicación. |
| `backend/training/` | Componentes de entrenamiento ML; comprobar sus consumidores antes de cambiar contratos. |
| `frontend/` | Interfaz Next.js/React. Consultar también `frontend/AGENTS.md` y las guías locales que indique. |
| `docs/` | Documentación clasificada por contenido; índice en `docs/README.md` y seguimiento activo en `docs/KANBAN.md`. |

* Antes de editar, revisar `git status` y las diferencias de los archivos afectados. Preservar cambios locales y archivos no rastreados ajenos a la tarea.
* Consultar los `AGENTS.md` específicos del área que se vaya a modificar.
* Contrastar documentos con el código del checkout actual. Distinguir implementación vigente, cambios locales, propuestas y registros históricos; una fecha reciente o un recibo anterior no prueban el estado actual.

---

## 1. Metodología de Desarrollo: TDD (Test-Driven Development)
* **Skill de referencia:** [`tdd`](.agents/skills/tdd/SKILL.md)
* **Ciclo Red-Green-Refactor:**
  1. **Rojo:** Escribir siempre la prueba automatizada primero antes de escribir el código de producción. La prueba debe fallar por la razón correcta.
  2. **Verde:** Escribir el código mínimo necesario para hacer pasar la prueba.
  3. **Refactor:** Limpiar y optimizar la implementación asegurando que las pruebas se mantengan en verde.
* La superficie de pruebas debe corresponder a la interfaz pública del módulo, no a detalles internos de implementación.
* Aplicar TDD a cambios de comportamiento del código de producción. Para investigación o documentación, verificar fuentes, rutas y consistencia; no fabricar pruebas de código sin relación con el cambio.

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
* Usar las skills cuando la tarea corresponda a su propósito. Evaluar skills adicionales ante una necesidad concreta; no convertir su búsqueda o instalación en un paso rutinario de cada cambio.

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

## 7. Convenciones de Git: ramas y commits

* Escribir en inglés los nombres de todas las ramas nuevas. Usar nombres descriptivos, por ejemplo: `feat/training-validation`, `fix/checkpoint-loading` o `docs/project-guidelines`.
* Escribir en inglés el tipo y el alcance del mensaje de commit, y en español la descripción. Los tipos convencionales (`feat`, `fix`, `test`, `docs`, `refactor`, `chore`, etc.) conservan su forma original, igual que los identificadores técnicos que perderían significado al traducirlos.
* Usar el formato `type(scope): descripción en español`, con una descripción breve en imperativo que explique el resultado o propósito del cambio.
* Ejemplos: `fix(inference): fallar de forma segura en el predictor de bundles`; `feat(training): agregar tooltips explicativos para física de audio e hiperparámetros`; `test(registry): aislar fixtures de modelos de PostgreSQL`.

---

## 8. Entornos y comprobaciones

Elegir las comprobaciones según el área y el contrato afectados. Informar comandos, resultados, exclusiones y límites de la verificación; no presentar pruebas deseleccionadas como aprobadas ni resultados históricos como una ejecución nueva.

### Frontend

Desde `frontend/`, los comandos declarados en `package.json` son:

| Tarea | Comando |
| --- | --- |
| Instalar según `package-lock.json` | `npm ci` |
| Desarrollo | `npm run dev` |
| Pruebas | `npm test` |
| Lint | `npm run lint` |
| Compilación | `npm run build` |
| Servir compilación | `npm start` |

Consultar `frontend/package.json` para las versiones vigentes y las instrucciones locales antes de cambiar APIs del framework. No asumir que lint o build están aprobados por un registro previo.

### Backend

* Las dependencias se declaran en `backend/requirements.txt`; la imagen de `backend/Dockerfile` usa Python 3.12. Una prueba con otro intérprete no valida automáticamente la imagen.
* Para comprobaciones de entrenamiento, seguir el procedimiento y sus prerrequisitos en [`integracion-flujo-entrenamiento.md`](docs/manuales/integracion-flujo-entrenamiento.md), junto con la actualización de [`consolidacion-worktrees.md`](docs/manuales/consolidacion-worktrees.md). Usar el runner local `backend/tests/run_isolated_training_checks.py` con selectores pertinentes y un intérprete validado.
* Ese procedimiento usa SQLite en memoria, datos/modelos CPU sintéticos, temporales y cachés privados, red bloqueada y límites de tiempo. Su guarda de aplicación no equivale a un sandbox del sistema operativo ni valida GPU, PostgreSQL real o calidad de modelos.
* No instalar ni cambiar entornos por inercia ante un fallo: identificar primero si falta un prerrequisito o existe una regresión.

---

## 9. Contratos de entrenamiento y evidencia ML

* Distinguir admisión/inicio del trabajo, finalización, persistencia de checkpoints, evaluación, publicación y activación. Una respuesta de inicio no acredita las etapas posteriores.
* Verificar identidad del dataset, particiones y procedencia de pesos y métricas al modificar el flujo. Consultar los ADR vigentes en `docs/adr/` y las pruebas públicas del servicio/API.
* No afirmar disponibilidad de un modelo por su nombre o metadatos: comprobar los artefactos que exige el predictor. No deducir una subida a GCS de una ruta de checkpoint local.
* No usar entrenamiento real, descargas de pesos, modificación de datasets o arranque de Docker como validación rutinaria de cambios documentales o pruebas focalizadas. Elegir esos procedimientos cuando formen parte del alcance solicitado y documentar sus efectos y prerrequisitos.
