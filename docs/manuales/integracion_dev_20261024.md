# Integración de dev en afinamiento integral

**Aplicación posterior, 25 de octubre:** la migración pendiente ya se aplicó a la base oficial y el código integrado está activo en el checkout original. [Ejecución, comprobaciones y recuperación](actualizacion_oficial_0004_20261025.md). Los párrafos del corte del 24 describen su estado histórico previo al mantenimiento.

Corte: 24 de octubre de 2026. Integración comprobada y publicada en `fix/afinamiento-integral`, commit [`e86415b`](https://github.com/FabianCartes/F.A.M.A/commit/e86415bc1202db6ccd96052617b6a8f19b378568). Se verificó el SHA remoto y `dev` continúa en `adecb01`. Este cierre documental es posterior al commit de integración. El nodo oficial conserva su código y esquema anteriores.

## Origen y decisiones

El operador pidió integrar los avances del compañero antes de subir nuestra rama y confirmó usar entrenamiento, validación y prueba independientes. El punto de recuperación `aa53e09a9b935f752b01fe464cbc1a5bd10556c0` conserva nuestros avances; se integra `origin/dev` en `adecb01868940421fb44ca56194439908f10b585`, con base común `49f6bd50e88892a8f49abf9909f88c6ca3676aa3`. La rama remota `dev` se conserva.

Se resolvieron 19 conflictos iniciales y diferencias de comportamiento que no producían conflictos textuales. Permanecen las sesiones HttpOnly revocables, asignaciones, propiedad de trabajos, autonomía investigadora y activación explícita por el administrador. La importación/exportación ZIP usa esas sesiones. Se mantienen la inferencia con límites, identidad de checkpoints, entrenamiento en procesos y evaluación independiente de dev. Los repartos nuevos tienen tres grupos sin compartir grabaciones/grupos conocidos; los manifiestos 80/20 se conservan como historia.

La revisión aditiva `0004_integration` reúne 37 tablas de negocio, tres marcadores iniciales de control y 14 secuencias PostgreSQL; `alembic_version` permanece sin escritura para la aplicación. El arranque no crea tablas. La migración desde `0003_autonomy`, la instalación nueva y los permisos diarios se comprobaron en PostgreSQL 16 temporal. La decisión y sus límites están en [ADR 0069](../adr/0069-integracion-de-acceso-evaluacion-y-datasets.md).

Los 17 ADR de acceso/instalación pasan de 0034–0050 a 0052–0068 para conservar los ADR de dev. Se actualizan enlaces Markdown; los recibos JSON anteriores mantienen sus rutas y huellas históricas.

## Verificación de este corte

| Área | Resultado observado |
| --- | --- |
| Backend Linux, 182 archivos | Cobertura acumulada de **2781 PASS / 15 SKIP**, mediante tres grupos y repeticiones focales finales. No fue una única ejecución completa verde. |
| Feedback final | 169 PASS, sobre el último código de prefijos de dataset y rechazo de otro bucket; ya incluidos en la cobertura acumulada. |
| Persistencia/activación final | 46 PASS, después de ajustar una expectativa antigua de activación automática; ya incluidos en la cobertura acumulada. |
| Frontend Vitest | **479 PASS**, sin pruebas pendientes. |
| Frontend estático/compilación | TypeScript sin errores; ESLint sin errores ni advertencias; compilaciones Webpack y Turbopack aprobadas. |
| Windows nativo | 7 PASS de arranque/configuración, 21 PASS de particiones, 7 PASS de rutas/junctions/bloqueos/lanzador y 2 PASS de configuración Compose. |
| Configuración e históricos, raíz del repositorio | 17 PASS en Windows: Compose, identidad del contenedor y coherencia de recibos históricos; no son nuevos benchmarks ML. |
| Lanzadores POSIX | 14 PASS y cinco subtests con usuario sin privilegios, Docker/proceso worker sustituidos y HTTP real solo en loopback. |

Los nueve SKIP de plataforma/Compose de Linux se cubrieron en Windows. Seis casos requieren pesos/audio privados (calidad Chucao, PANNs y predictor entrenado); no se montaron esos insumos. No se atribuye calidad ni rendimiento de modelos reales a las pruebas sintéticas.

Los fallos intermedios se conservaron en los logs privados del laboratorio: contextos HTTP antiguos sin identidad, fixtures de esquema incompletas, prefijos históricos de datasets y expectativas de activación. Se corrigieron sin quitar las guardas de autenticación, origen, confinamiento ni activación. Un primer ensayo de los lanzadores POSIX ejecutado como root fue rechazado correctamente; repetido como UID 10001 pasó sin cambiar su protección.

El [recibo](../receipts/integracion_dev_20261024.json) registra selectores, recuentos, huellas, repeticiones, omisiones y versiones. Los logs completos quedan en `.pytest_cache/dev-integration-tools/results` del checkout original y en `.pytest_cache`/archivos `.vitest-*` del worktree; no se publican credenciales ni cachés.

## Entorno del laboratorio y reproducción

Backend: Python 3.12, dependencias de `backend/requirements.txt`, PyTorch/torchaudio 2.8.0 CPU y torchvision 0.23.0. Los tres grupos se ejecutaron en contenedores desechables, con red interna sin puertos publicados, un PostgreSQL 16 exclusivo por grupo y datos sintéticos. La fuente se montó de solo lectura y se copió al contenedor; no se montaron perfiles, ADC, datasets o pesos institucionales. Los nombres y claves del laboratorio eran sintéticos.

Los selectores exactos y comandos pytest figuran en el recibo. Para repetirlos se prepara una copia temporal del repositorio con esas dependencias, configuración sintética y las variables `FAMA_TEST_*` que documentan las propias pruebas de PostgreSQL. Exigen una base exclusiva de laboratorio y herramientas `pg_dump`/`pg_restore` 16; no apuntar esas variables a Cloud SQL. Para las pruebas de launcher POSIX se usa un usuario sin privilegios; sus límites Docker y worker se sustituyen dentro de las pruebas.

Desde `frontend`, las comprobaciones fueron `npm test -- --run --reporter=json`, `npx tsc --noEmit --incremental false`, `npm run lint`, `npm run build -- --webpack` y `npm run build`. Las dos compilaciones usaron directorios `.next-integration-*` mediante `FAMA_NEXT_DIST_DIR`; no sobrescribieron la compilación del servicio oficial. Las dependencias estaban físicamente dentro del worktree para permitir Turbopack.

Estas comprobaciones no acreditan un nuevo recorrido visual en navegador, entrenamiento GPU, integración real con GCS, construcción/arranque de las imágenes de producción ni un despliegue completo. Las pruebas shell y los dos archivos de configuración Compose POSIX de la raíz no se ejecutaron en este corte; la configuración normal/cloud y los contratos de contenedor sí se verificaron con Docker Compose en Windows.

## Checkout y servicio oficial

La integración se prepara en `C:/Users/fabia/.codex/worktrees/dev-integration/F.A.M.A`. El checkout original `C:/Users/fabia/Desktop/F.A.M.A` conserva `aa53e09` bajo `codex/official-runtime-20261024` para que los procesos oficiales sigan leyendo los mismos archivos. La rama local y remota `fix/afinamiento-integral` se vincula al commit integrado desde el worktree. Esa separación permite publicar el código comprobado sin sustituir archivos del servicio activo ni migrar su base durante una operación de Git.

El nodo de los puertos 3010/8010 conserva `fama_oficial`, el bucket oficial y `runtime/oficial`, con `0003_autonomy`. Las cuentas, contraseñas, perfiles y objetos GCS se conservan. El checkout integrado aún no debe arrancarse contra esa base con el esquema anterior.

## Mantenimiento para usar la versión integrada en el nodo oficial

El mantenimiento descrito a continuación se ejecutó el 25 de octubre; se conserva el procedimiento previsto. El resultado observado y la ejecución con credenciales solo en memoria están en el registro posterior:

1. Definir la ventana de mantenimiento y detener los escritores del nodo. Conservar el checkout y perfil anteriores. Con el código de `aa53e09`, generar y comprobar una copia SQL nueva mediante `app.node backup`; conservar también configuración privada, runtime y checkpoints. La CLI nueva espera `0004_integration` y no sustituye el respaldo previo de una base 0003.
2. Preparar el checkout integrado y sus dependencias sin iniciar servidores. La contraseña del usuario migrador se introduce localmente y solo durante el mantenimiento; no queda en Git ni en recibos.
3. En un proceso temporal con `DATABASE_URL` del migrador oficial, ejecutar desde `backend` `python -m app.schema status`, comprobar el destino y después `python -m app.schema upgrade --apply --revision 0004_integration`. Esperar `schema_current` y la revisión correcta. Limpiar esa variable al terminar.
4. Aplicar `backend/scripts/permisos_tablas_oficial.sql` con el migrador para las tablas/secuencias nuevas y verificar que la aplicación conserva solo sus permisos diarios. El script tiene guardas de base y roles; no eludirlas.
5. Preparar el perfil y runtime existentes en el nuevo checkout mediante los procedimientos de operación. Iniciar un solo propietario del runtime con el usuario de aplicación; comprobar `/ready`, login, asignaciones, ingesta, predicción y una operación de escritura acotada. Crear una copia posterior verificada.
6. Si falla, mantener detenido el candidato. La vuelta al código antiguo requiere también la base restaurada del respaldo previo, porque su comprobador espera 0003; no basta cambiar de rama después de migrar. No restaurar sobre la base activa sin un plan explícito.

`preparar_esquema_oficial.py` es de instalación inicial y rechaza perfiles completados; no se usa para actualizar este nodo. No se ejecutó ninguna de estas escrituras contra Cloud SQL en esta integración.

ZIP, sus workers y la preparación CSV verificada de dev requieren Linux/Docker. Windows nativo informa esa capacidad como no disponible y conserva el resto de funciones, incluidas las particiones locales de tres grupos. El catálogo privado ZIP permanece separado del catálogo compartido de entrenamiento; no se inventan asignaciones ni traslados de contenido. El despliegue universitario, HTTPS y acceso de red siguen en su planificación propia.
