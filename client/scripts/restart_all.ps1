$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$repoRoot = Split-Path -Parent $root
$pythonCandidates = @(
  (Join-Path $root ".venv-local\Scripts\python.exe"),
  (Join-Path $root ".venv\Scripts\python.exe"),
  (Join-Path $repoRoot ".venv\Scripts\python.exe"),
  (Join-Path $repoRoot ".venv-local\Scripts\python.exe")
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not (Test-Path -LiteralPath $python)) {
  throw "Python environment not found. Run setup.bat first."
}

$listener = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
  $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
  if ($processInfo -and $processInfo.CommandLine -match 'server\.py') {
    Stop-Process -Id $listener.OwningProcess -Force
    Start-Sleep -Milliseconds 600
  } else {
    throw "Port 8080 is occupied by a process that is not this workspace server."
  }
}

Start-Process -FilePath $python -ArgumentList "server.py" -WorkingDirectory $root -WindowStyle Hidden | Out-Null
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1
  try {
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/license/status" -TimeoutSec 2
    if ($null -ne $status.active) {
      Write-Host "Client API ready at http://127.0.0.1:8080"
      Write-Host "License active: $($status.active)"
      exit 0
    }
  } catch { }
}
throw "Client API did not become healthy at http://127.0.0.1:8080"
