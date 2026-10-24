param(
    [Parameter(Mandatory=$true)][string]$ConfigDirectory,
    [ValidateRange(1,65535)][int]$BackendPort = 8010,
    [ValidateRange(1,65535)][int]$FrontendPort = 3010,
    [string]$PythonExecutable,
    [string]$NodeExecutable,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
try {
    $sourceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $backendDirectory = Join-Path $sourceRoot 'backend'
    $frontendDirectory = Join-Path $sourceRoot 'frontend'
    $selectedConfiguration = (Resolve-Path -LiteralPath $ConfigDirectory).ProviderPath
    if (-not $PythonExecutable) { $PythonExecutable = Join-Path $backendDirectory '.venv/Scripts/python.exe' }
    if (-not $NodeExecutable) { $NodeExecutable = (Get-Command node -ErrorAction Stop).Source }
    if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf) -or -not (Test-Path -LiteralPath $NodeExecutable -PathType Leaf)) { throw 'native_dependency_missing' }
    if ($BackendPort -eq $FrontendPort) { throw 'native_port_in_use' }
    foreach ($port in @($BackendPort,$FrontendPort)) {
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw 'native_port_in_use' }
    }
    $env:PYTHON_DOTENV_DISABLED = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    Push-Location -LiteralPath $backendDirectory
    try {
        $runtimeText = & $PythonExecutable -m app.node --config-dir $selectedConfiguration runtime
        if ($LASTEXITCODE -ne 0) { throw 'native_runtime_not_ready' }
        $runtime = $runtimeText | ConvertFrom-Json
    } finally { Pop-Location }
    if ($runtime.code -ne 'runtime_ready') { throw 'native_runtime_not_ready' }
    $distDirectory = '.next-' + $FrontendPort
    $result = @{code='native_launch_validated'; runtime_root=$runtime.root; frontend_dist_dir=$distDirectory; backend_port=$BackendPort; frontend_port=$FrontendPort}
    if (-not $ValidateOnly) {
        $stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff')
        $backendLog = Join-Path $runtime.directories.logs ('backend-' + $stamp)
        $frontendLog = Join-Path $runtime.directories.logs ('frontend-' + $stamp)
        $env:API_URL = 'http://127.0.0.1:' + $BackendPort
        $env:NEXT_PUBLIC_API_URL = 'http://localhost:' + $FrontendPort
        $env:FAMA_NEXT_DIST_DIR = $distDirectory
        $backendProcess = Start-Process -FilePath $PythonExecutable -ArgumentList @('-m','app.node','--config-dir',('"' + $selectedConfiguration + '"'),'serve','--port',$BackendPort) -WorkingDirectory $backendDirectory -WindowStyle Hidden -RedirectStandardOutput ($backendLog + '.out.log') -RedirectStandardError ($backendLog + '.err.log') -PassThru
        $frontendProcess = Start-Process -FilePath $NodeExecutable -ArgumentList @('node_modules/next/dist/bin/next','dev','--webpack','--hostname','127.0.0.1','--port',$FrontendPort) -WorkingDirectory $frontendDirectory -WindowStyle Hidden -RedirectStandardOutput ($frontendLog + '.out.log') -RedirectStandardError ($frontendLog + '.err.log') -PassThru
        $result.code = 'native_processes_started'
        $result.backend_pid = $backendProcess.Id
        $result.frontend_pid = $frontendProcess.Id
        $result.backend_log_prefix = $backendLog
        $result.frontend_log_prefix = $frontendLog
        $result.checked_at = [DateTime]::UtcNow.ToString('o')
        $result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runtime.root 'run-last.json') -Encoding utf8
    }
    $result | ConvertTo-Json -Compress -Depth 4
    exit 0
} catch {
    $code = $_.Exception.Message
    if ($code -notin @('native_dependency_missing','native_port_in_use','native_runtime_not_ready')) { $code = 'native_launch_failed' }
    @{code=$code} | ConvertTo-Json -Compress
    exit 1
}
