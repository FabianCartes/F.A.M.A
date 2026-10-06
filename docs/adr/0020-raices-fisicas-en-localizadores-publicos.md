# ADR 0020: Raíces físicas en los localizadores públicos de datasets

* **Estado:** Aceptado
* **Área:** Localizadores de rutas y asociación canónica de datasets

Los getters raw/processed y sus wrappers `PathResolver` conservan la escritura
original de la raíz declarada, sin resolver enlaces simbólicos. Las raíces con
alias no están soportadas para la asociación canónica de datasets. Se elige este
contrato global para no ocultar evidencia antes de la validación física.

## Contexto

[ADR 0019](0019-referencias-canonicas-por-etapa.md) exige inspeccionar la raíz y
todos sus ancestros antes de resolver una referencia. El comportamiento anterior
de los getters usaba `resolve()`: un alias podía desaparecer del resultado y
parecer una raíz física. Este ADR actualiza esa descripción histórica de los
localizadores en ADR 0019, sin cambiar el contrato del validador.

## Alternativas y decisión

| Alternativa | Resultado |
| --- | --- |
| A: conservar la escritura original en todos los getters raw/processed y wrappers; alias no soportados para asociación canónica | Elegida explícitamente: mantiene visible la declaración que debe validar el consumidor. |
| B: conservar getters resueltos por compatibilidad y añadir una declaración física separada | Descartada: permite seguir borrando evidencia en la interfaz pública existente y divide el contrato entre dos familias de localizadores. |

## Contrato

[training/paths.py](../../backend/training/paths.py) mantiene rutas absolutas e
independientes de cwd. Los getters conservan la escritura de la raíz seleccionada
por ubicación del código o fallback del proyecto, incluido el nombre del dataset.
`PathResolver.raw_data_dir` y `processed_data_dir` tienen el mismo contrato.
`get_dataset_roots(dataset_name)` declara este mapa:

- `raw`: `backend/data/raw/{dataset_name}`.
- `processed`: `backend/data/processed/{dataset_name}/processed_wav`.

El mapa no deduce etapa por etiqueta, CSV, nombre de archivo ni extensión.
Declarar una ruta no prueba que exista ni que sea físicamente segura. El consumidor
usa [resolve_reference](../../backend/dataset_references.py) para validar la etapa
seleccionada, rechazar alias en raíz/ancestros y exigir un archivo regular existente.
La raíz no seleccionada puede estar ausente. Fuentes personalizadas deben declarar
su propio mapa explícito; no se añade descubrimiento ni fallback de validación.

## Consecuencias y límites

Se rompe deliberadamente la promesa anterior de devolver rutas raw/processed ya
resueltas. Las rutas ordinarias sin alias conservan sus valores. `get_project_root`
y `get_checkpoints_dir` mantienen su comportamiento; no se extiende este cambio a
la identidad del repositorio ni a checkpoints.

En [registry.py](../../backend/app/services/registry.py), la asociación local compara
la URI persistida con la ruta declarada antes de comprobar contención resuelta.
Si la raíz configurada es un alias y la URI almacenada usa el destino resuelto,
la comparación puede perder la asociación. Ese caso queda fuera del contrato
soportado; no se ha demostrado una regresión con raíces físicas ordinarias ni se
garantiza que todos los llamadores rechacen alias de forma uniforme o segura.

Las [pruebas públicas](../../backend/tests/test_paths.py) cubren escritura de getters
y wrappers, raíces ordinarias, independencia de cwd, mapa por etapa y rechazo de
alias por el consumidor. No acreditan un corte operativo ni una migración integral.
La validación no garantiza locks, snapshot, hash, contenido acústico ni identidad.
No se reescriben URIs, modelos, historial, índices CSV, audio, BD o outbox, ni se
activa una migración automática. Las decisiones futuras sobre datos y despliegue
requieren autorización separada.
