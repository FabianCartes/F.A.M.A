# Worker local de importación ZIP — entorno principal del MVP

## Propósito y límite de seguridad

La API admite trabajos; un proceso separado ejecuta la vista previa y la confirmación. Una subida completa con `queued · 0%` no demuestra validación de audios.

La reparación utiliza el host existente, con UID1000 y la `.venv` del proyecto, para ejecutar el CLI ya implementado. El procesamiento no confiable permanece dentro de Bubblewrap, con namespaces, seccomp, límites de recursos, entorno vacío y acceso mínimo al filesystem. No se modifica la política Docker ni se usa un contenedor privilegiado. La API y PostgreSQL permanecen en sus contenedores actuales.

**Readiness observada:** el validador real pudo decodificar y verificar un WAV sintético válido en ese host, sin BD ni trabajos, con cero errores. Véase [recibo de readiness](../receipts/zip-worker-host-readiness.json). Eso no demuestra por sí solo publicación de un dataset real.

## Configuración de esta instancia

- BD: `fama_training_dev_20261105153618`, misma que usa la aplicación.
- Import root físico: `.training-manual-44938bc83ad0184c/runtime/imports`.
- Staging físico: `.training-manual-44938bc83ad0184c/runtime/import-worker-staging`, privado, UID1000 y mismo filesystem que imports.
- Adaptador/configuración privados: `.zip-worker-repair-1bdd65240872a605/`; directorio0700 y archivos0600. No copiarlos a Git ni imprimir sus contenidos.
- La URL no incluye contraseña. El acceso usa el `PGPASSFILE` existente y `PGHOSTADDR` para la IP privada actual de PostgreSQL, sin cambiar la credencial ni publicar el puerto de BD.
- Modo: `--local-only --watch`; consume únicamente `preview` y `confirm`. No consume trabajos cloud ni inicia entrenamiento.
- La ejecución activa usa una unidad transitoria de usuario `fama-zip-worker-connected-large`, con `NoNewPrivileges=yes` y umask0077. Su `ExecStartPre` comprueba identidad de BD, privilegios efectivos mediante transacción de solo lectura y el validador real bajo esas mismas restricciones, antes de reclamar trabajos. Si esa comprobación falla, no debe comenzar el consumidor.

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

La parada debe respetar la finalización cooperativa del intento actual. No cancelar trabajos, borrar staging ni restaurar la BD para detener el proceso. El servicio transitorio no constituye instalación permanente ni arranque automático al reiniciar el equipo; API, BD y worker deben estar disponibles para continuar importaciones después de un reinicio.

Antes de reactivarlo tras cambiar la IP de PostgreSQL, las rutas o la versión de fuentes, revisar la configuración privada y repetir la comprobación de arranque correspondiente a la nueva configuración. No repetir un sandbox indisponible sin resolver su prerrequisito.

### Reactivación tras detener o reiniciar el equipo

Si la unidad todavía existe, `systemctl --user restart fama-zip-worker-connected-large` vuelve a ejecutar su preflight. Si el equipo se reinició y la unidad transitoria ya no existe, desde la raíz de este checkout, después de verificar que API/BD y su IP privada no cambiaron:

```bash
PROJECT="$PWD"
ADAPTER="$PROJECT/.zip-worker-repair-1bdd65240872a605/run-worker.py"
PYTHON="$PROJECT/.venv/bin/python"
systemd-run --user --unit=fama-zip-worker-connected-large --service-type=exec \
  --property=NoNewPrivileges=yes --property=UMask=0077 \
  --property=TimeoutStartSec=30 --property=TimeoutStopSec=1830 \
  --property=Restart=no \
  --property="ExecStartPre=$PYTHON -I -B $ADAPTER --check" \
  --working-directory="$PROJECT/backend" "$PYTHON" -I -B "$ADAPTER"
```

No imprimir `worker.json` ni `PGPASSFILE`. Un fallo de preflight impide arrancar el consumidor y no dispara reintentos automáticos. Detenerse a resolver el requisito, no desactivar la comprobación.

## Aceptación desde la aplicación

1. Abrir la importación existente; no volver a subir el mismo archivo por estar en cola.
2. Observar transición desde `queued` hacia ejecución y resultado terminal.
3. Si hay errores de estructura/audio, revisar los códigos públicos: un rechazo correcto no es un fallo del consumidor.
4. Si la vista previa es válida, revisar clases y audios y confirmar desde la interfaz. El worker no inventa esa confirmación.
5. Comprobar que el dataset aparece y conserva miembros/objetos localmente. GCS continúa pendiente hasta configurar y autorizar su sincronización.

No confundir trabajo terminado con publicación confirmada. Un archivo de368bytes recibido no acredita por sí solo contener WAV válidos. La evidencia debe distinguir readiness sintética, resultado del archivo del usuario, confirmación y publicación.

## Valores predeterminados para ZIP grandes

La API y el worker comparten por defecto6GiB recibidos,10GiB expandidos,96MiB por WAV y900s de validación. El intento del worker tiene1800s cooperativos; la parada admite1830s. Mantener lease60s, heartbeat20s, bloques16MiB y sandbox intactos. Los overrides explícitos conservan prioridad. El recibo de despliegue es [large-zip-defaults-deployment.json](../receipts/large-zip-defaults-deployment.json). Estos presupuestos no son una garantía de rendimiento ni acreditan importación/entrenamiento real.
