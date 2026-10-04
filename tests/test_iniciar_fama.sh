#!/usr/bin/env bash
# Public seam: copied startup script, isolated PATH, observed CLI/output/status.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORK=$(mktemp -d "$ROOT/tests/fixtures/docker-startup/runtime-XXXXXX")
# Remove only the directory allocated by this invocation, including on failure.
cleanup() {
    case "$WORK" in
        "$ROOT/tests/fixtures/docker-startup/runtime-"*)
            [[ -d "$WORK" && ! -L "$WORK" ]] || return 0
            rm -rf -- "$WORK"
            ;;
        *) printf 'Refusing cleanup outside the test runtime directory.\n' >&2; return 1 ;;
    esac
}
trap cleanup EXIT
mkdir -p "$WORK/project with spaces" "$WORK/bin" "$WORK/outside"
cp "$ROOT/iniciar_fama.sh" "$WORK/project with spaces/"
cp "$ROOT/tests/fixtures/docker-startup/docker" "$WORK/bin/docker"
chmod +x "$WORK/bin/docker"
# Only these ordinary utilities can be found: no fallback to a host Docker CLI.
for utility in bash dirname mkdir sleep touch; do
    ln -s "$(command -v "$utility")" "$WORK/bin/$utility"
done
mkdir -p "$WORK/legacy-bin" "$WORK/no-docker-bin"
for utility in bash dirname mkdir sleep touch; do
    ln -s "$(command -v "$utility")" "$WORK/no-docker-bin/$utility"
done
cp "$ROOT/tests/fixtures/docker-startup/docker-compose" "$WORK/legacy-bin/docker-compose"
chmod +x "$WORK/legacy-bin/docker-compose"
count=0
run() {
    count=$((count + 1))
    mkdir -p "$WORK/state-$count"
    LOG="$WORK/log-$count"; OUTPUT="$WORK/output-$count"
    RC=0
    local fake_path="$WORK/bin"
    [[ $1 != legacy ]] || fake_path="$WORK/legacy-bin:$WORK/bin"
    [[ $1 != cli_missing ]] || fake_path="$WORK/no-docker-bin"
    (cd "$WORK/outside"; PATH="$fake_path" SCENARIO="$1" FAKE_CLI=docker \
        FAKE_LOG="$LOG" FAKE_STATE="$WORK/state-$count" \
        bash "$WORK/project with spaces/iniciar_fama.sh" "${@:2}") > "$OUTPUT" 2>&1 || RC=$?
}
fail() { printf 'FAIL: %s (exit %s)\n' "$1" "$RC"; while IFS= read -r line; do printf '%s\n' "$line"; done < "$OUTPUT"; exit 1; }
has() { grep -Fq -- "$2" "$1" || fail "missing: $2"; }
lacks() { if grep -Fq -- "$2" "$1"; then fail "unexpected: $2"; fi; }
ok() { [[ $RC == 0 ]] || fail "$1"; printf 'ok %s - %s\n' "$count" "$1"; }
run healthy backend
ok 'daily startup reuses images'
lacks "$LOG" '<--build>'
run transition backend
ok 'waits through starting and includes newly started dependency'
has "$LOG" '<inspect>'
has "$LOG" '<db-id>'
[[ $(grep -c '<inspect>.*<backend-id>' "$LOG") -ge 2 ]] || fail 'starting must be polled again'
lacks "$LOG" '<unrelated>'
run unhealthy --wait-timeout 1 backend
[[ $RC != 0 ]] || fail 'unhealthy must fail'
has "$OUTPUT" 'unhealthy'
lacks "$OUTPUT" 'Servicios iniciados correctamente'
printf 'ok %s - unhealthy dependency fails clearly\n' "$count"
bad() {
    [[ $RC != 0 ]] || fail "$1"
    has "$OUTPUT" "$2"
    lacks "$OUTPUT" 'Servicios iniciados correctamente'
    printf 'ok %s - %s\n' "$count" "$1"
}
run exited backend
bad 'exited container fails' 'exited'
run timeout --wait-timeout=1 backend
bad 'bounded starting timeout' 'Tiempo de espera agotado (1s)'
run empty backend
bad 'no containers is not success' 'No se encontraron contenedores'
run daemon backend
bad 'Docker access preflight' 'No se pudo acceder al motor de Docker'
has "$OUTPUT" 'permisos, el contexto y la conexión'
lacks "$OUTPUT" 'servicio de Docker no está en ejecución'
lacks "$LOG" '<compose>'
run compose_missing backend
bad 'Compose preflight' 'No se encontró docker compose'
run cli_missing backend
bad 'Docker CLI preflight' 'Docker no está instalado'
run up_failure backend
bad 'up failure diagnosis' 'Falló Docker Compose up'
run healthy --no-start backend
bad 'reject non-start mode' 'Opción incompatible'
lacks "$LOG" '<up>'
# This fake checks our script/CLI contract, not real Compose build semantics.
run missing backend
ok 'missing buildable image bootstraps'
has "$LOG" '<compose> <up> <-d> <backend>'
has "$WORK/state-$count/image-events" 'before-up absent'
has "$WORK/state-$count/image-events" 'after-up present'
[[ -f "$WORK/state-$count/image-present" ]] || fail 'bootstrap must create image state'
lacks "$LOG" '<--build>'
run healthy --build backend
ok 'explicit rebuild'
has "$LOG" '<up> <-d> <--build> <backend>'
lacks "$LOG" '<--no-cache>'
run missing --no-build backend
bad 'no-build forbids bootstrap' 'Falló Docker Compose up'
has "$LOG" '<compose> <up> <-d> <--no-build> <backend>'
has "$WORK/state-$count/image-events" 'before-up absent'
has "$WORK/state-$count/image-events" 'after-up absent'
[[ ! -f "$WORK/state-$count/image-present" && ! -f "$WORK/state-$count/up" ]] || fail 'no-build must leave image and service absent'
lacks "$LOG" '<inspect>'
run healthy --no-build backend
ok 'no-build reuses existing image'
has "$LOG" '<--no-build>'
run legacy --scale 'backend=2' --pull 'missing' backend
ok 'legacy Compose and value options'
has "$LOG" '|docker-compose <up> <-d> <--scale> <backend=2> <--pull> <missing> <backend>'
lacks "$LOG" '<ps> <-a> <-q> <backend=2>'
run healthy --scale 'backend=2 with spaces' backend
ok 'space-containing argv and script-relative working directory'
has "$LOG" "$WORK/project with spaces|docker <compose> <up> <-d> <--scale> <backend=2 with spaces> <backend>"
[[ -d "$WORK/project with spaces/backend/checkpoints" && -d "$WORK/project with spaces/backend/data" ]] || fail 'mapped dirs'
[[ ! -d "$WORK/outside/backend" ]] || fail 'caller directory mutated'
run all
ok 'all services including healthy and no-healthcheck running'
run healthy db
ok 'selected db excludes unrelated services'
lacks "$LOG" '<inspect> <--format> <{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}> <backend-id>'
run healthy --wait-timeout 0 backend
bad 'invalid timeout rejected' 'entero entre 1 y 86400'
run healthy --build --no-build backend
bad 'conflicting build modes rejected' 'son incompatibles'
run dep_restarted backend
ok 'existing stopped dependency is waited after restart'
has "$LOG" '<inspect> <--format> <{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}> <db-id>'
run dormant backend
ok 'unrelated stopped container stays outside scope'
lacks "$LOG" '<inspect> <--format> <{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}> <dormant-id>'
run missing_selected backend db
bad 'each selected service needs containers' 'No se encontraron contenedores para backend'
printf 'PASS: %s public behavior cases\n' "$count"
printf 'Temporary runtime will be removed on exit.\n'
