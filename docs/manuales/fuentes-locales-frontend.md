# Fuentes locales del frontend

## Objetivo y alcance

El frontend ahora incluye Montserrat y Open Sans como WOFF2 locales cargadas mediante `next/font/local`. La compilación y el navegador ya no dependen de Google Fonts. Se conservan las variables CSS, `display: swap`, el layout, metadatos, viewport e hijos.

Superficies: `frontend/app/layout.tsx`, `frontend/app/fonts/`, `frontend/app/__tests__/layout.test.ts`, este manual y `docs/README.md`. Sin cambios de dependencias, compilador ni backend. No se crearon commits, ramas ni publicaciones.

## Seguimiento de la corrección

- [x] FONTS-1: fuentes locales y licencias incorporadas; layout migrado y pruebas, build de producción, Docker, compilación sin red externa y navegador aprobados. El orquestador repitió la prueba enfocada: 6/6 aprobadas. Sin commits por falta de autorización explícita; revisión nativa se informa por separado.

## Implementación y procedencia

Ambos activos son WOFF2 variables, estilo normal, subset `latin`; sus rangos incluyen los pesos solicitados. La API oficial de Google Fonts usada para resolver los activos fue `https://fonts.googleapis.com/css2?family=Montserrat:wght@500..800&family=Open+Sans:wght@400..600&display=swap`.

| Familia / archivo local | Pesos | URL oficial WOFF2 | SHA-256 | Tamaño |
| --- | --- | --- | --- | ---: |
| Montserrat — `frontend/app/fonts/Montserrat-latin-variable.woff2` | 500–800 | `https://fonts.gstatic.com/s/montserrat/v31/JTUSjIg1_i6t8kCHKm459Wlhyw.woff2` | `06b16db7a969135d48d38c49183be7fb88d4452e2a3011957c7851941f4e4879` | 37.956 B |
| Open Sans — `frontend/app/fonts/OpenSans-latin-variable.woff2` | 400–600 | `https://fonts.gstatic.com/s/opensans/v44/memvYaGs126MiZpBA-UvWbX2vVnXBbObj2OVTS-muw.woff2` | `d8e4fe0452aa2076429a9bb5d8757d00a994dd95986cf950e9a1a371b9a072a0` | 48.320 B |

Se conservaron las licencias SIL Open Font License 1.1 descargadas de Google Fonts en el commit fijado `bd8f81ddb5c74d5c8897b36ad88b440266245103`:

- `frontend/app/fonts/Montserrat-OFL.txt` — [fuente fijada](https://github.com/google/fonts/blob/bd8f81ddb5c74d5c8897b36ad88b440266245103/ofl/montserrat/OFL.txt), SHA-256 `8b7141c03fa4f8d44e6345d5d4931709290f0f67875e452e95ac1fd3a027802e`.
- `frontend/app/fonts/OpenSans-OFL.txt` — [fuente fijada](https://github.com/google/fonts/blob/bd8f81ddb5c74d5c8897b36ad88b440266245103/ofl/opensans/OFL.txt), SHA-256 `fbbbcfef55318de350562559b671360de6d597112ecc5c73881b05092db89602`.

La declaración oficial del subset latino usa el rango Unicode `U+0000–00FF`, que cubre `ñ`, vocales acentuadas, `ü`, `¿` y `¡`. `woff2_info` reconoció ambos archivos como WOFF2 válidos (firma `0x774f4632`) con tablas `cmap` y `fvar`. Chromium cargó y mostró el texto de prueba `ÁÉÍÓÚÜ¿¡Ññáéíóúü` con ambas familias. Las licencias y los hashes fijan la procedencia de los activos.

## Evidencia de implementación y validación

- `frontend/app/layout.tsx` declara `Montserrat` con peso variable `500 800` y `Open Sans` con `400 600`, ambos `style: normal`, `display: swap` y las variables `--font-montserrat` / `--font-open-sans`. El CSS de producción emitió esos rangos, variables y las dos caras locales WOFF2.
- La prueba pública renderiza hijos con caracteres españoles y comprueba idioma/clases del documento, clase del cuerpo y metadatos/viewport existentes. El mock solo representa la frontera de compilación de `next/font/local`; las compilaciones reales verifican archivos y loader.
- `cd frontend && npm test -- app/__tests__/layout.test.ts` — 6/6 pruebas aprobadas después del cambio (también pasó antes de la migración). No había un RED conductual significativo: esta corrección reemplaza el loader conservando el resultado público. Se evitó inventar un fallo mediante mocks; el build y la compilación Docker son la evidencia determinista de la frontera.
- `cd frontend && npm test` — 20 archivos y 250 pruebas aprobadas.
- `cd frontend && npm run build` — build de producción aprobado, incluyendo TypeScript y prerenderizado.
- `docker compose build --no-cache frontend` — build de la imagen aprobado; los WOFF2 entraron en el contexto y el `next build` de Docker terminó. Se ejecutó con variables de entorno aisladas, `COMPOSE_ENV_FILES=/dev/null` y un HOME descartable para no leer el `.env` raíz. El `npm ci` ocurre solo en la imagen; reportó 9 vulnerabilidades durante la auditoría (8 altas, 1 crítica), sin cambios de dependencias en el repositorio.
- Build sin red externa — aprobado en un namespace de red nuevo, con loopback local activo para la comunicación interna de Turbopack, `.env.local` enmascarado y `.next` temporal en tmpfs. Dependencias locales ya estaban instaladas; la build limpia compiló, generó páginas y finalizó. Un primer intento con loopback abajo falló al iniciar el proceso CSS de Turbopack; al habilitar solo `lo`, la repetición pasó. El primer intento generó el registro de pánico habitual de Next en `/tmp`; no se inspeccionó ni modificó.
- Chromium headless — familias y pesos calculados: Montserrat 800 en título; Open Sans 400 en cuerpo y 600 en texto destacado. Carga de ambas caras con el texto español aprobada y comprobación visual del screenshot temporal `frontend/.next/font-preview.png` (ignorado, no versionable).
- La extracción directa de la tabla cmap no estaba disponible: `ttx` carece de la extensión Python Brotli y `fc-scan`/`hb-info` no pudieron abrir WOFF2. La tabla existe en ambos binarios; rango Unicode oficial, build local y renderizado real cubren la comprobación práctica sin añadir dependencias.

Una ejecución inicial del test nuevo falló por sintaxis JSX en un archivo `.ts`; se reemplazó por `createElement` antes de cambiar producción y el test pasó. Una primera invocación del build Docker con HOME inexistente falló antes de construir; se repitió con HOME temporal y aprobó.

## Próximo paso

Corrección funcional verificada; completar la revisión nativa antes del informe final. Evaluar las 9 vulnerabilidades reportadas por npm en un trabajo separado, sin inferir su explotabilidad de la auditoría. Reversión: retirar activos/licencias locales y restaurar layout y mock, sin cambios ajenos a fuentes.
