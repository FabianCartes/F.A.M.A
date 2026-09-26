@echo off
REM ==============================================================================
REM F.A.M.A. - Script de Arranque Rapido para Windows (cmd / PowerShell)
REM ==============================================================================
chcp 65001 >nul
title F.A.M.A. - Framework Bioacustico MLOps

echo ===================================================================
echo    F.A.M.A. - Framework MLOps Hibrido para Clasificacion Bioacustica
echo ===================================================================

REM 1. Verificar presencia de Docker
where docker >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Docker no esta instalado o no se encuentra en el PATH del sistema.
    echo Por favor descargue e instale Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/
    pause
    exit /b 1
)

REM 2. Verificar si Docker Desktop esta ejecutandose
docker info >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Docker Desktop no esta en ejecucion.
    echo Inicie Docker Desktop y vuelva a intentar ejecutar este script.
    pause
    exit /b 1
)

REM 3. Asegurar que las carpetas de volumenes existan
if not exist "backend\checkpoints" mkdir "backend\checkpoints"
if not exist "backend\data" mkdir "backend\data"

REM 4. Iniciar y construir contenedores
echo [1/3] Construyendo e iniciando contenedores en segundo plano...
docker compose up -d --build

if %errorlevel% neq 0 (
    echo [ERROR] Hubo un problema al iniciar los contenedores con docker compose.
    pause
    exit /b %errorlevel%
)

echo.
echo [2/3] Verificando estado de los servicios...
docker compose ps

echo.
echo ===================================================================
echo    ¡F.A.M.A. se ha iniciado exitosamente!
echo ===================================================================
echo   - Aplicacion Web (Frontend):    http://localhost:3000
echo   - Documentacion API (FastAPI):  http://localhost:8000/docs
echo   - Base de Datos (PostgreSQL):   localhost:5432 (fama_db)
echo.
echo Comandos utiles:
echo   - Ver logs en vivo:             docker compose logs -f
echo   - Detener el sistema:           docker compose down
echo ===================================================================
echo.
pause
