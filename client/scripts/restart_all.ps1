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

$statePath = Join-Path $root ".runtime\server.json"
if (Test-Path -LiteralPath $statePath) {
  try {
    $previousState = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    $previousProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($previousState.pid)" -ErrorAction SilentlyContinue
    if ($previousProcess -and $previousProcess.CommandLine -match 'server\.py') {
      Stop-Process -Id $previousState.pid -Force
      Start-Sleep -Milliseconds 600
    }
  } catch { }
  Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
}

Start-Process -FilePath $python -ArgumentList "server.py" -WorkingDirectory $root -WindowStyle Hidden | Out-Null
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1
  try {
    if (-not (Test-Path -LiteralPath $statePath)) { continue }
    $currentState = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    $baseUrl = [string]$currentState.url
    if (-not $baseUrl) { continue }
    $status = Invoke-RestMethod -Uri "$baseUrl/api/license/status" -TimeoutSec 2
    if ($null -ne $status.active) {
      Write-Host "Client API ready at $baseUrl"
      Write-Host "License active: $($status.active)"
      exit 0
    }
  } catch { }
}
throw "Client API did not publish a healthy adaptive port within 30 seconds"
