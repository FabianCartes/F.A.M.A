# Identidad técnica del nodo oficial

**Actualización oficial aplicada, 25 de octubre:** `fama_oficial` está en `0004_integration` y la carpeta habitual ejecuta `fix/afinamiento-integral` (`54bdaaf`). Login real, permisos, GCS, datasets, dashboard y catálogo de seis modelos comprobados; cinco hashes históricos completados tras contrastarlos con GCS. Respaldos anterior/posterior restaurados y verificados en laboratorio aislado. Perfil, contraseñas e índices conservados. [Operación y límites](actualizacion_oficial_0004_20261025.md), [recibo](../receipts/actualizacion_oficial_0004_20261025.json).

**Estado vigente — 24 de octubre, arranque oficial:** el nodo de `http://localhost:3010` usa `fama_oficial`, `fama-audio-records-2026` y `runtime/oficial`. Perfil completado mediante adopción del administrador histórico, recuperación de contraseña solicitada por el operador e inicio de sesión verificado. Super-Ensamble de aves predeterminado y cinco modelos individuales seleccionables; inferencia real acotada correcta. Los cinco audios históricos diferentes están versionados en GCS, con 1205 filas conservadas en el índice; catálogo SQL de 1220 objetos de aves, 1386 de motores y un audio histórico industrial. Pesos respaldados por contenido y verificados. Los contadores globales ahora recorren todo el bucket: 2646 objetos observados. Siguen pesos del ensamble industrial, respaldo SQL externo/retención y despliegue universitario con HTTPS y servicio estable. [Estado operativo y límites](conciliacion_catalogo_y_pesos_oficiales.md), [recibo actual](../receipts/catalogo_oficial_publicado_20261024.json). Los bloques inferiores conservan sus cortes históricos.

**Actualización: 24 de octubre de 2026. Estado: IAM/ADC, perfil, esquema e historia real verificados. Runtime oficial con cinco pesos cargables y un audio; copia SQL posterior recuperada en laboratorio. Pendientes decisiones de catálogo, archivos restantes, adopción y arranque. Perfil sin activar.**

El operador ya compartió el resultado correcto del comprobador SQL: ambas identidades conectan a `fama_oficial` por el proxy local, con consultas de solo lectura, cero tablas públicas y CREATE en `public` únicamente para `fama_oficial_migrador`. Esto no configura todavía la identidad Google Cloud del nodo, el esquema o los permisos DML.

## Alcance autorizado y verificado

El operador autorizó explícitamente crear `fama-oficial-app@proyectotesis-fama.iam.gserviceaccount.com`, nombre visible **FAMA - Nodo oficial**, y las tres vinculaciones siguientes. Codex creó la cuenta y verificó las políticas guardadas mediante consultas posteriores. Es la identidad de transporte y archivos prevista para el nodo; los usuarios SQL y las cuentas web conservan sus funciones distintas.

| Destinatario | Permiso aplicado | Recurso exacto y alcance |
| --- | --- | --- |
| Nueva cuenta técnica `fama-oficial-app` | `roles/cloudsql.client` — Cliente de Cloud SQL | Proyecto `proyectotesis-fama`. Permite obtener metadatos y conectar a instancias del proyecto; no concede por sí solo acceso a filas, creación de bases o administración SQL. La base oficial utiliza sus usuarios SQL propios. |
| Nueva cuenta técnica `fama-oficial-app` | `roles/storage.objectUser` — Usuario de objetos de Storage | Solo bucket `fama-audio-records-2026`. Permite leer, crear, actualizar y borrar objetos, además de las operaciones de carpetas y cargas multipart del rol. No se propone un rol Storage a nivel de proyecto. |
| Cuenta Google operadora de esta sesión | `roles/iam.serviceAccountTokenCreator` — Creador de tokens de cuentas de servicio | Solo la nueva cuenta `fama-oficial-app`. Permite generar credenciales temporales de esa identidad para el uso local del operador. No es un permiso de las cuentas investigadoras de F.A.M.A. |

El correo exacto del operador figuró en la pregunta de aprobación y permanece en el registro local protegido; el recibo público lo identifica por huella. No se retiraron ni ampliaron permisos de `fama-orquestador` o `fama-pruebas-app`.

La inspección de la definición vigente de los roles mostró `cloudsql.instances.connect/get` para Cliente de Cloud SQL y las operaciones de objetos utilizadas por la ingesta/checkpoints para Usuario de objetos. La consulta posterior observó la cuenta oficial habilitada, una sola vinculación para ella en el proyecto y otra en el bucket, ambas con los roles aprobados y sin condición. El operador tiene Token Creator sobre esa cuenta. Cero claves administradas por usuario. Después del login, la comprobación con el ADC oficial confirmó renovación de credenciales temporales, listado de como máximo un objeto en el bucket y HTTP 200 de `connectSettings` de la instancia.

## Revisión automática y estado actual

El primer intento fue rechazado por la revisión automática antes de ejecutarse: faltaba autorización humana explícita para los destinos y alcances exactos. Ese corte queda conservado en el recibo anterior. Después, el operador respondió **«Autorizar la configuración propuesta»** a la pregunta que enumeraba cuenta, correo, roles y recursos. Con esa autorización se ejecutaron y verificaron únicamente los cambios acordados; no se utilizó una vía indirecta para eludir el rechazo.

La carpeta `backend/credentials/gcloud-oficial/` del equipo tiene DACL protegida para el usuario Windows actual y SYSTEM, sin reglas Allow ajenas. Sus registros y el ADC generado por Google Cloud SDK heredan esa protección; el archivo ADC también se comprobó sin reglas Allow ajenas. No contiene contraseñas SQL. El directorio está excluido de Git y del contexto Docker.

## Inicio de sesión Google completado

El operador informó que eligió su correo y el navegador confirmó la autenticación de gcloud. Codex observó el ADC local de tipo `impersonated_service_account`, origen `authorized_user` y destino exacto `fama-oficial-app`. Se verificaron los accesos de lectura indicados arriba. Las instrucciones siguientes conservan el procedimiento realizado; no hay que repetirlo ahora.

Abrir PowerShell en este equipo y ejecutar las dos instrucciones siguientes. La primera elige la carpeta oficial solo para ese terminal; no cambia el perfil que usa la aplicación en ejecución. El comando de inicio de sesión y sus opciones se contrastaron con la ayuda de la versión instalada de Google Cloud SDK.

```powershell
$env:CLOUDSDK_CONFIG = 'C:\Users\fabia\Desktop\F.A.M.A\backend\credentials\gcloud-oficial'
& 'C:\Users\fabia\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd' auth application-default login --impersonate-service-account=fama-oficial-app@proyectotesis-fama.iam.gserviceaccount.com --disable-quota-project --project=proyectotesis-fama
```

En el navegador, elegir la cuenta Google operadora autorizada, completar el consentimiento y volver a PowerShell. El SDK debe informar que guardó credenciales en `backend/credentials/gcloud-oficial/application_default_credentials.json`. No abrir ni pegar ese archivo; basta confirmar que el comando terminó correctamente. No introducir las contraseñas SQL en este paso. `--disable-quota-project` evita añadir un proyecto de cuota al ADC; no desactiva la facturación de los recursos.

La credencial contiene la autenticación local del operador que permite obtener credenciales temporales de `fama-oficial-app`. No se genera una clave privada de la cuenta de servicio.

## Perfil local preparado y comprobado

El operador confirmó la ejecución del comando siguiente. Codex observó perfiles nativo/Docker, secretos presentes y `completed=false`; el perfil nativo utiliza `fama_oficial_app`, `fama_oficial`, `127.0.0.1:5434` y el bucket oficial. `app.node check` devolvió `database_connected` y `storage_read_connected`. Otra consulta de solo lectura confirmó identidad, puerto y cero tablas públicas. El procedimiento siguiente conserva cómo se preparó el perfil; ya no es un paso pendiente.

La inspección Windows encontró que `mkdir(mode=0o700)` creaba las carpetas hijas con su propia DACL de usuario/administradores/Owner Rights, distinta de la DACL explícita usuario/SYSTEM del directorio superior. La CLI ahora protege también `secrets`, `native` y `docker` antes de escribir; prueba pública extendida a todo el árbol. Rojo funcional por regla Allow adicional y verde final **13 PASS / dos archivos**. En el perfil ya creado se corrigieron únicamente ACL: siete archivos conservaron exactamente su contenido. Verificación posterior de perfil y respaldo: 25 entradas, cero reglas Allow ajenas y cero directorios sin protección de herencia.

Codex inició un segundo proxy con ADC oficial, binario 2.26.2 observado y huella `41cfddfe79fdb5eb89a42c8c76149384eb1c564cfcaa7369a3261c95a5338b35`. Su prueba informó `Connection test passed`; proceso, ejecutable, argumentos de instancia/credencial y propietario del listener `127.0.0.1:5434` coinciden. PID observado: 21152; no es una identidad permanente del servicio. El listener anterior de pruebas en 5433 conserva el mismo propietario. No se inició sesión SQL por el nuevo proxy todavía. Registros y logs quedan en la carpeta privada `backend/credentials/gcloud-oficial/runtime/`.

En un PowerShell interactivo del operador:

```powershell
Set-Location 'C:\Users\fabia\Desktop\F.A.M.A\backend'
& .\.venv\Scripts\python.exe -m app.node --config-dir 'C:\Users\fabia\Desktop\F.A.M.A\backend\installation\cloud-oficial' prepare `
  --project proyectotesis-fama `
  --bucket fama-audio-records-2026 `
  --credentials-file 'C:\Users\fabia\Desktop\F.A.M.A\backend\credentials\gcloud-oficial\application_default_credentials.json' `
  --connection-name proyectotesis-fama:us-central1:fama-postgres-pruebas `
  --database fama_oficial `
  --user fama_oficial_app `
  --proxy-port 5434 `
  --web-origin http://localhost:3010
```

Introducir la contraseña SQL asignada a **`fama_oficial_app`** cuando se solicite, con entrada oculta. Es la contraseña de ese usuario de base de datos; no se pide la cuenta web administradora. La CLI guarda referencias y secretos protegidos para los modos nativo/Docker bajo el nuevo directorio `cloud-oficial`; no aplica migraciones ni activa el perfil. La salida correcta es `{"code": "configuration_prepared"}`. Comunicar únicamente ese resultado.

El directorio debe ser nuevo: si aparece `configuration_directory_exists`, conservarlo para revisar su estado sin borrarlo ni sobrescribirlo. La ayuda del comando existente se comprobó antes del relevo. Las pruebas de esa CLI corresponden a su recibo anterior; no se reejecutaron ni se añadió código de producción en esta unidad.

## Continuación

1. **Completado:** cuenta creada y tres vinculaciones aprobadas verificadas mediante consulta de sus políticas guardadas.
2. **Completado:** ADC oficial generado por el operador y comprobado en lectura contra GCS/Cloud SQL; proxy propio de loopback listo. No se copiaron credenciales de pruebas.
3. **Completado:** perfil creado y conexiones verificadas; permisos Windows de todo el árbol corregidos y probados. Sin activar el perfil ni aplicar migraciones.
4. **Respaldo histórico completado:** PostgreSQL 18 local exportado y recuperado en ensayo exclusivo de la misma versión principal; ver [respaldo histórico](respaldo_historico_postgresql18.md). Sigue el traslado controlado al esquema vigente, permisos DML, adopción de cuenta existente y conciliación de archivos antes del corte.

La credencial local se prepara inicialmente para este PC. Al trasladar el nodo al servidor universitario se acordará su identidad de ejecución y autenticación institucional; la credencial del operador personal no se considera automáticamente apropiada para distribuirla al servidor.

Referencias: [ADC local con suplantación](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment), [suplantación de cuentas de servicio](https://docs.cloud.google.com/docs/authentication/use-service-account-impersonation), [roles de Cloud Storage](https://docs.cloud.google.com/storage/docs/access-control/iam-roles). [Preparación oficial](preparacion_entorno_oficial.md), [corte anterior SQL y propuesta](../receipts/acceso_sql_oficial_confirmado_20261024.json), [IAM aplicado y verificado](../receipts/identidad_oficial_iam_20261024.json), [ADC y proxy verificados](../receipts/identidad_oficial_adc_proxy_20261024.json), [perfil y respaldo histórico](../receipts/perfil_oficial_y_respaldo_historico_20261024.json).

**Relevo posterior:** traslado y adopción ya implementados y ensayados. El paso inmediato es [preparar esquema oficial](traslado_historia_y_adopcion.md#paso-inmediato-del-operador-preparar-el-esquema-oficial); la copia real y el corte siguen pendientes.
