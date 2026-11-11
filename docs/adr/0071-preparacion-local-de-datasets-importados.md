# ADR 0071: Preparación local de datasets importados con grupos explícitos

**Estado:** Contrato de diseño aceptado para el plan; T1 implementada en `36bf338`, T2 implementada con verificación funcional y límite independiente documentado/aceptado; T3–T7 pendientes. El perfil de T2 debe ser explícito (S9 del plan), sin defaults silenciosos. Autoridad y evidencia: [plan, resultado T0 y Log](../arquitectura/entrenamiento-datasets-importados-plan.md#resultado-técnico-de-t0).

## Contexto

Una importación local válida no acredita particiones independientes. Los miembros actuales no contienen identidad explícita de grabación/grupo y el manifiesto completo existente acredita publicación remota, no preparación local. Reutilizar su estado `complete` sin GCS alteraría el contrato del ADR 0037.

## Decisión

- Primera versión: WAV, clasificación supervisada con una etiqueta por archivo; preparación y entrenamiento locales por identidad autorizada. El importador ZIP y los flujos legacy mantienen sus contratos.
- Exigir un mapa explícito de grabación/grupo vinculado y validado contra los miembros del snapshot. Si falta, la importación sigue válida y la preparación espera metadatos; ni rutas ni hashes prueban independencia. Registrar procedencia del mapa no certifica por sí solo la veracidad de su contenido.
- Separar grupos antes de segmentar/aumentar; cada clase debe aparecer en train, val y test. Objetivo 80/10/10 subordinado a grupos y factibilidad, no porcentajes exactos. Menos de diez grabaciones independientes por clase genera advertencia; solo la incompatibilidad o imposibilidad estructural bloquea.
- Diseñar un snapshot local de entrenamiento separado del ciclo remoto: capturar membresía completa y propietario bajo la compuerta compartida con confirmación; materializar copia privada verificada, con identidad canónica, publicación atómica e integridad comprobada antes de consumirla. Persistencia de aplicación y raíces locales durables, sin rutas del cliente. El detalle de esquema y las garantías de carrera/retención deben implementarse y probarse en T1 antes de admitir jobs.
- Seleccionar el predictor por ID registrado, con clases explícitas y procedencia; no activar ni cambiar default por publicar. Mantener el contrato actual de `POST /api/predict`, que exige GCS antes de inferir. Las pruebas futuras usarán almacenamiento sintético, no operaciones cloud reales.

## Alternativas y consecuencias

Asumir independencia por archivo permitiría avanzar sin metadatos, pero no sostendría una afirmación de particiones sin fuga. Permitir clases ausentes en val/test simplifica datasets pequeños a costa de evaluación incompleta; el usuario eligió cobertura en las tres particiones. Reutilizar `complete` remoto para bytes locales evitaría otro ciclo de snapshot, pero confundiría dos garantías distintas.

La copia privada aumenta almacenamiento e I/O y requiere presupuesto, limpieza de staging propio y retención de snapshots referenciados; no se introduce borrado de originales ni un recolector automático. Un mapa explícito puede requerir trabajo de anotación y no garantiza calidad estadística. Cambiar la predicción pública a cloud-free sería otro alcance, no efecto implícito de entrenar localmente.

## Límites de autorización

T0 cierra diseño e investigación de código, no ejecución funcional. Sin implementación de producción, entrenamiento real, migraciones existentes, servicios, GCS, instalaciones o acceso externo. T1–T6 requieren autorización de implementación y T7 autorización operacional separada.
