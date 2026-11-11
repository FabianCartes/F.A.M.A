# Worker local de importación ZIP — entorno principal del MVP

> **Nota de sustitución (2026-11-11):** el worker privado de sincronización a `private-imports/` fue retirado; al confirmar, el ZIP se publica en GCS `datasets/`. Ver [ADR 0078](../adr/0078-gcs-como-fuente-unica-y-publicacion-del-zip.md) y [Importar datasets ZIP](importacion-datasets-zip.md).

## Propósito y límite de seguridad

La API admite trabajos; un proceso separado ejecuta la vista previa y la confirmación. Una subida completa con `queued · 0%` no demuestra validación de audios.

La reparación utiliza el host existente, con UID1000 y la `.venv` del proyecto, para ejecutar el CLI ya implementado. El procesamiento no confiable permanece dentro de Bubblewrap, con namespaces, seccomp, límites de recursos, entorno vacío y acceso mínimo al filesystem. No se modifica la política Docker ni se usa un contenedor privilegiado. La API y PostgreSQL permanecen en sus contenedores actuales.

**Readiness observada:** el validador real pudo decodificar y verificar un WAV sintético válido en ese host, sin BD ni trabajos, con cero errores. Véase [recibo de readiness](../receipts/zip-worker-host-readiness.json). Eso no demuestra por sí solo publicación de un dataset real.

## Configuración histórica de esta instancia

Lo siguiente registra la instalación anterior, no certifica que use el checkout
actual. La retirada de código no modifica servicios ni permisos del host. Para
el contrato vigente, consultar [trabajos locales](trabajos-importacion-datasets.md).
La descarga compartida GCS → local y feedback sync se conservan; no equivalen al
worker privado de sincronización retirado.

- BD: `fama_training_dev_20261105153618`, misma que usa la aplicación.
- Import root físico: `.training-manual-44938bc83ad0184c/runtime/imports`.
- Staging físico: `.training-manual-44938bc83ad0184c/runtime/import-worker-staging`, privado, UID1000 y mismo filesystem que imports.
- Adaptador/configuración privados: `.zip-worker-repair-1bdd65240872a605/`; directorio0700 y archivos0600. No copiarlos a Git ni imprimir sus contenidos.
- La URL no incluye contraseña. El acceso usa el `PGPASSFILE` existente y `PGHOSTADDR` para la IP privada actual de PostgreSQL, sin cambiar la credencial ni publicar el puerto de BD.
- Modo: `--local-only --watch`; consume únicamente `preview` y `confirm`. El worker ya es local por defecto; `--local-only` se conserva para los lanzadores existentes. No existe `--sync-only` ni se usa `FAMA_IMPORT_STORAGE_PROFILE`. No inicia entrenamiento.
- La ejecución activa usa la unidad persistente de usuario `fama-zip-worker-connected-large` (`~/.config/systemd/user/fama-zip-worker-connected-large.service`, habilitada en `default.target`), con `NoNewPrivileges=yes` y umask0077. Un primer `ExecStartPre` espera como máximo120s a que la IP privada de PostgreSQL acepte TCP (`wait-db.py`, privado, solo alcanzabilidad). El segundo `ExecStartPre` comprueba identidad de BD, privilegios efectivos mediante transacción de solo lectura y el validador real bajo esas mismas restricciones, antes de reclamar trabajos. Si esa comprobación falla, no debe comenzar el consumidor.

El adaptador invoca el CLI existente; no es un segundo validador ni un fallback sin sandbox. El servicio ya pasó su preflight bajo `NoNewPrivileges`, comprobó identidad/permisos y el validador real, y permanece activo consultando la cola. Véase [evidencia del despliegue](../receipts/zip-worker-connected-deployment.json).

El trabajo original `47a3ab3adec64dbea026dbd456959dbc` estaba cancelado antes de arrancar este servicio (20:15UTC frente a 20:28UTC), con cero intentos. La reparación no lo canceló ni lo reactivó; el actor que pidió cancelación no está probado. No hay prueba de preview/publicación de ese archivo y no se informa una importación exitosa.

## Operación

Consultar estado sin imprimir configuración protegida:

```bash
systemctl --user status fama-zip-worker-connected-large --no-pager
```

Los logs normales contienen readiness y si hubo trabajo reclamado, no credenciales. El CLI puede indicar `claimed: false` cuando está ocioso: no es un error.

Detener solo este consumidor:

```bash
systemctl --user stop fama-zip-worker-connected-large
```

La parada debe respetar la finalización cooperativa del intento actual. No cancelar trabajos, borrar staging ni restaurar la BD para detener el proceso. `stop` no deshabilita la unidad: vuelve a arrancar al siguiente inicio de sesión. Para retirarla, `systemctl --user disable --now fama-zip-worker-connected-large`.

Antes de reactivarlo tras cambiar la IP de PostgreSQL, las rutas o la versión de fuentes, revisar la configuración privada y repetir la comprobación de arranque correspondiente a la nueva configuración. No repetir un sandbox indisponible sin resolver su prerrequisito.

### Reactivación tras detener o reiniciar el equipo

Tras un reinicio no hay pasos manuales si se cumplen estos prerrequisitos:

| Pieza | Configuración | Motivo |
| --- | --- | --- |
| Daemon Docker | `docker.service` habilitado (`sudo systemctl enable docker.service`) | Con solo `docker.socket` el daemon no arranca hasta el primer uso y los contenedores no vuelven. |
| BD y API | `--restart unless-stopped` | Vuelven al arrancar el daemon; un `docker stop` explícito se respeta. |
| IP privada | BD `172.23.0.2`, API `172.23.0.3`, consumidor GCS `172.23.0.4`, fijas en la red interna | `worker.json` usa `PGHOSTADDR` y Next.js la IP de la API; con asignación dinámica podían cambiar o intercambiarse. |
| Alias de red | La BD conserva el alias `db` | API y consumidor GCS conectan a `db:5432`. Al reconectar la BD para fijar su IP, usar `docker network connect --ip 172.23.0.2 --alias db`; sin `--alias` ambos pierden la BD aunque el health de la API siga en200. |
| Worker | Unidad de usuario habilitada | Arranca al iniciar sesión. Sin `loginctl enable-linger` no arranca antes del login. |

Para relanzarlo manualmente, `systemctl --user restart fama-zip-worker-connected-large` vuelve a ejecutar la espera y el preflight. No imprimir `worker.json` ni `PGPASSFILE`. Un fallo de preflight impide arrancar el consumidor y no dispara reintentos automáticos (`Restart=no`); si la BD no responde en120s la unidad queda fallida. Detenerse a resolver el requisito, no desactivar la comprobación. Si cambian las IP, las rutas o la versión de fuentes, actualizar la configuración privada antes de reiniciar.

Esta persistencia es propia del host local. En un servidor que sea a su vez un contenedor no hay systemd ni daemon Docker propios, y Bubblewrap requiere user namespaces que el perfil por defecto de Docker bloquea; esa receta pertenece a la preparación de despliegue, no a este manual.

## Aceptación desde la aplicación

1. Abrir la importación existente; no volver a subir el mismo archivo por estar en cola.
2. Observar transición desde `queued` hacia ejecución y resultado terminal.
3. Si hay errores de estructura/audio, revisar los códigos públicos: un rechazo correcto no es un fallo del consumidor.
4. Si la vista previa es válida, revisar clases y audios y confirmar desde la interfaz. El worker no inventa esa confirmación.
5. Comprobar que la importación termina y conserva miembros/objetos localmente. Al terminar, el dataset aparece en GCS y en el inventario compartido, asignado al importador; si la publicación falla, la importación sigue local y **Reintentar trabajo** la completa. La subida privada y la exportación ZIP se retiraron: no configurar ni arrancar sus workers.

No confundir trabajo terminado con publicación confirmada. Un archivo de368bytes recibido no acredita por sí solo contener WAV válidos. La evidencia debe distinguir readiness sintética, resultado del archivo del usuario, confirmación y publicación.

## Valores predeterminados para ZIP grandes

La API y el worker comparten por defecto6GiB recibidos,10GiB expandidos,96MiB por WAV y900s de validación. El intento del worker tiene1800s cooperativos; la parada admite1830s. Mantener lease60s, heartbeat20s, bloques16MiB y sandbox intactos. Los overrides explícitos conservan prioridad. El recibo de despliegue es [large-zip-defaults-deployment.json](../receipts/large-zip-defaults-deployment.json). Estos presupuestos no son una garantía de rendimiento ni acreditan importación/entrenamiento real.
