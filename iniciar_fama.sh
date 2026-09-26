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

echo -e "${BLUE}===================================================================${NC}"
echo -e "${GREEN}   F.A.M.A. - Framework MLOps Híbrido para Clasificación Bioacústica${NC}"
echo -e "${BLUE}===================================================================${NC}"

# 1. Verificar si Docker está instalado
if ! command -v docker >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Docker no está instalado en este sistema.${NC}"
    echo "Por favor instale Docker Desktop o Docker Engine desde: https://docs.docker.com/get-docker/"
    exit 1
fi

# 2. Verificar si el demonio de Docker está en ejecución
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] El servicio de Docker no está corriendo.${NC}"
    echo "Inicie Docker Desktop o el servicio dockerd antes de continuar."
    exit 1
fi

# 3. Detectar comando de Docker Compose (docker compose v2 o docker-compose v1)
COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}[ERROR] No se encontró docker compose ni docker-compose.${NC}"
    exit 1
fi

# 4. Asegurar existencia de directorios mapeados
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p backend/checkpoints backend/data

echo -e "\n${YELLOW}[1/3] Construyendo e iniciando contenedores en segundo plano...${NC}"
$COMPOSE_CMD up -d --build "$@"

echo -e "\n${YELLOW}[2/3] Verificando estado de los servicios...${NC}"
$COMPOSE_CMD ps

echo -e "\n${GREEN}===================================================================${NC}"
echo -e "${GREEN}   ¡F.A.M.A. se ha iniciado exitosamente!                         ${NC}"
echo -e "${GREEN}===================================================================${NC}"
echo -e "  • Aplicación Web (Frontend):      ${BLUE}http://localhost:3000${NC}"
echo -e "  • Documentación API (FastAPI):    ${BLUE}http://localhost:8000/docs${NC}"
echo -e "  • Base de Datos (PostgreSQL):     ${BLUE}localhost:5432 (fama_db)${NC}"
echo -e "\n${YELLOW}Comandos útiles:${NC}"
echo "  • Ver logs en tiempo real:        $COMPOSE_CMD logs -f"
echo "  • Detener el sistema:             $COMPOSE_CMD down"
echo "  • Reiniciar el sistema:           ./iniciar_fama.sh"
echo -e "===================================================================\n"
