# Nodo de inferencia en el servidor universitario

Instalación nativa de F.A.M.A. en el servidor virtual de la universidad, destinada a inferencia con los modelos respaldados en GCS. El nodo **no entrena**: el servidor carece de GPU y su uso se limita a predicción. Registro de avance y evidencia: [bitácora de acceso e instalación](bitacora_acceso_e_instalacion.md).

## Alcance y acceso

| Elemento | Valor |
| --- | --- |
| URL | `https://146.83.194.142:2064` (solo desde la red o la VPN de la universidad) |
| Base de datos | `fama_oficial` en Cloud SQL, compartida con el nodo oficial del PC del operador |
| Bucket | `fama-audio-records-2026` |
| Identidad de Google | Cuenta de servicio `fama-servidor-ubb` (`roles/cloudsql.client` en el proyecto y `roles/storage.objectUser` solo en el bucket oficial) |
| Código | Commit indicado en `/opt/fama/app/COMMIT` |

El backend solo admite orígenes `https://` o `http://localhost` (`backend/app/web_settings.py`), por lo que el nodo se sirve con HTTPS. El certificado es autofirmado, válido dos años, para `146.83.194.142` y la IP interna. La primera visita desde cada navegador muestra una advertencia de conexión no privada que se acepta una vez. Iniciar sesión siempre con la URL anterior: otro origen, como la IP interna, no coincide con `FAMA_WEB_ORIGIN`.

## Arquitectura en el contenedor

El servidor es un contenedor Docker sin systemd. El puerto público 2064 corresponde al puerto 80 interno.

```text
Navegador ──HTTPS──▶ :80 Caddy ──▶ 127.0.0.1:3000 Next.js (standalone)
                                         └─ /api ──▶ 127.0.0.1:8010 FastAPI (app.node serve)
                                                          ├─ 127.0.0.1:5434 Cloud SQL Auth Proxy ──▶ fama_oficial
                                                          └─ GCS fama-audio-records-2026
```

| Ruta | Contenido |
| --- | --- |
| `/opt/fama/app` | Código (`backend/`, `frontend/`) |
| `/opt/fama/venv` | Python 3.12 con `torch`, `torchvision` y `torchaudio` en variantes CPU |
| `/opt/node` | Node.js 22 |
| `/opt/fama/web` | Frontend compilado con `API_URL=http://127.0.0.1:8010` |
| `/opt/fama/perfil` | Perfil de instalación y secretos (0700) |
| `/opt/fama/runtime` | Checkpoints y datos locales del nodo |
| `/opt/fama/credentials`, `/opt/fama/tls` | Llave de la cuenta de servicio y certificado (0600) |
| `/opt/fama/logs` | Registros de cada proceso |

## Operación

Arranque, idempotente (no duplica procesos ya activos):

```bash
/opt/fama/iniciar.sh
```

Comprobaciones:

```bash
curl -s http://127.0.0.1:8010/ready          # {"code":"schema_current"}
curl -sk https://127.0.0.1/api/installation/status -H 'Host: 146.83.194.142'
pgrep -af 'cloud-sql-proxy|app.node|next-server|caddy run'
```

Los procesos sobreviven al cierre de la sesión SSH, pero no a un reinicio del contenedor: tras un reinicio, ejecutar `/opt/fama/iniciar.sh`. El contenedor solo conserva `/var/lib/postgresql` si se recrea desde su imagen; en ese caso se repite la instalación.

## Modelos para inferencia

Un nodo nuevo no tiene checkpoints locales. Desde **Entrenamiento → Historial de Modelos Guardados**, cada modelo muestra **Descargar desde GCS** cuando solo existe la copia remota; la descarga verifica tamaño y SHA-256. No hay un comando para restaurarlos todos a la vez.

## Problemas conocidos

- `timm` instala `torchvision` desde PyPI, incompatible con `torch` CPU (`RuntimeError: operator torchvision::nms does not exist`). Reinstalar `torchvision` y `torchaudio` desde `https://download.pytorch.org/whl/cpu`.
- Las evaluaciones guardan `runtime_versions` (`torch` sin sufijo de build, `numpy`, `librosa`) y el catálogo rechaza el modelo con «runtime del predictor incompatible con los informes» si el nodo usa otra versión (`backend/app/services/standard_evaluation_guard.py`). `backend/requirements.txt` no fija esas versiones; en este nodo se instalaron las del nodo evaluador: `torch==2.14.0`, `torchaudio==2.11.0`, `torchvision==0.29.0` (índice CPU), `numpy==2.5.3` y `librosa==1.0.0`.
- Un checkpoint aún no descargado se informa como «checkpoint inválido o distinto de la identidad registrada»; descargarlo desde GCS lo resuelve.
- Caddy no acepta `https://:80`; se declara `https_port 80` en las opciones globales.
- Next.js renombra su proceso a `next-server`; el script lo detecta con ese nombre.

## Retiro

Revocar el acceso eliminando la cuenta de servicio `fama-servidor-ubb` (o su llave) en GCP; el nodo deja de conectar a la base y al bucket.
