#!/usr/bin/env bash
# ==============================================================================
# F.A.M.A. - Script de Arranque Rápido para Linux y macOS
# ==============================================================================
set -euo pipefail

# Colores para la terminal
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # Sin color

echo -e "${GREEN}F.A.M.A. - Framework de Monitoreo y Diagnóstico Acústico${NC}"

# 1. Verificar si Docker está instalado
if ! command -v docker >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Docker no está instalado en este sistema.${NC}"
    echo "Instale Docker Desktop o Docker Engine desde: https://docs.docker.com/get-docker/"
    exit 1
fi

# 2. Verificar acceso al motor de Docker
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] No se pudo acceder al motor de Docker.${NC}"
    echo "Revise que el servicio esté disponible, los permisos, el contexto y la conexión de Docker."
    exit 1
fi

# 3. Detectar comando de Docker Compose (docker compose v2 o docker-compose v1)
COMPOSE_CMD=()
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1 && docker-compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
else
    echo -e "${RED}[ERROR] No se encontró docker compose ni docker-compose.${NC}"
    exit 1
fi

# 4. Asegurar existencia de directorios mapeados
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p backend/checkpoints backend/data

fail() { echo -e "${RED}[ERROR] $*${NC}" >&2; exit 1; }
WAIT_TIMEOUT=180
UP_ARGS=()
SERVICES=()
while (($#)); do
    case "$1" in
        --wait-timeout|--wait-timeout=*)
            if [[ $1 == *=* ]]; then WAIT_TIMEOUT=${1#*=}; else
                (($# >= 2)) || fail 'Falta el valor de --wait-timeout.'
                shift; WAIT_TIMEOUT=$1
            fi
            ;;
        --build|--no-build|-d|--detach|--no-deps|--force-recreate|--no-recreate|--remove-orphans|--renew-anon-volumes|-V|--quiet-pull|--quiet-build)
            UP_ARGS+=("$1") ;;
        --scale|--pull|--timeout|-t)
            (($# >= 2)) || fail "Falta el valor de $1."
            UP_ARGS+=("$1" "$2"); shift ;;
        --scale=*|--pull=*|--timeout=*) UP_ARGS+=("$1") ;;
        --) shift; SERVICES+=("$@"); UP_ARGS+=(-- "$@"); break ;;
        -*) fail "Opción incompatible o no soportada por la espera: $1. Use docker compose directamente para otros modos." ;;
        *) SERVICES+=("$1"); UP_ARGS+=("$1") ;;
    esac
    shift
done
[[ $WAIT_TIMEOUT =~ ^[1-9][0-9]{0,4}$ ]] && ((WAIT_TIMEOUT <= 86400)) || fail '--wait-timeout debe ser un entero entre 1 y 86400 segundos.'
[[ " ${UP_ARGS[*]} " != *' --build '* || " ${UP_ARGS[*]} " != *' --no-build '* ]] || fail '--build y --no-build son incompatibles.'
before_all=$("${COMPOSE_CMD[@]}" ps -a -q) || fail 'No se pudo consultar Compose antes del arranque.'
before_running=$("${COMPOSE_CMD[@]}" ps -q --filter status=running) || fail 'No se pudo consultar Compose antes del arranque.'

echo -e "\n${YELLOW}[1/3] Iniciando contenedores en segundo plano (reutilizando imágenes)...${NC}"
if ! "${COMPOSE_CMD[@]}" up -d "${UP_ARGS[@]}"; then
    fail 'Falló Docker Compose up; revise el diagnóstico anterior. No se confirmó disponibilidad.'
fi

echo -e "\n${YELLOW}[2/3] Esperando disponibilidad de los servicios...${NC}"
contains_id() {
    local candidate
    for candidate in $1; do [[ $candidate != "$2" ]] || return 0; done
    return 1
}
all_ids=$("${COMPOSE_CMD[@]}" ps -a -q) || fail 'No se pudo consultar los contenedores.'
running_ids=$("${COMPOSE_CMD[@]}" ps -q --filter status=running) || fail 'No se pudo consultar los contenedores activos.'
ids=$("${COMPOSE_CMD[@]}" ps -a -q "${SERVICES[@]}") || fail 'No se pudo consultar los servicios solicitados.'
[[ -n $ids ]] || fail 'No se encontraron contenedores para los servicios solicitados.'
for service in "${SERVICES[@]}"; do
    service_ids=$("${COMPOSE_CMD[@]}" ps -a -q "$service") || fail "No se pudo consultar $service."
    [[ -n $service_ids ]] || fail "No se encontraron contenedores para $service."
done
# New containers and stopped containers now running include started dependencies.
# Existing unrelated containers (running or stopped) are not part of this scope.
for id in $all_ids; do
    if ! contains_id "$before_all" "$id" || { contains_id "$running_ids" "$id" && ! contains_id "$before_running" "$id"; }; then
        contains_id "$ids" "$id" || ids+=$'\n'"$id"
    fi
done
deadline=$((SECONDS + WAIT_TIMEOUT))
while :; do
    ready=true
    pending=''
    for id in $ids; do
        state=$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id") || fail "No se pudo inspeccionar $id."
        case "$state" in
            'running healthy'|'running none') ;;
            *' unhealthy'|exited*|dead*|removing*) fail "Contenedor $id no disponible: $state. Revise los logs de Compose." ;;
            *) ready=false; pending+=" $id ($state)" ;;
        esac
    done
    $ready && break
    ((SECONDS < deadline)) || fail "Tiempo de espera agotado (${WAIT_TIMEOUT}s):$pending. Revise los logs de Compose."
    sleep 1
done
"${COMPOSE_CMD[@]}" ps "${SERVICES[@]}" || fail 'No se pudo mostrar el estado final.'

echo -e "\n${GREEN}Servicios iniciados correctamente.${NC}"
echo -e "  • Aplicación Web (Frontend):      ${BLUE}http://localhost:3000${NC}"
echo -e "  • Documentación API (FastAPI):    ${BLUE}http://localhost:8000/docs${NC}"
echo -e "  • Base de Datos (PostgreSQL):     ${BLUE}localhost:5432 (fama_db)${NC}"
echo -e "\n${YELLOW}Comandos:${NC}"
echo "  • Ver logs en tiempo real:        ${COMPOSE_CMD[*]} logs -f"
echo "  • Detener el sistema:             ${COMPOSE_CMD[*]} down"
echo "  • Reiniciar el sistema:           ./iniciar_fama.sh"
echo ""

