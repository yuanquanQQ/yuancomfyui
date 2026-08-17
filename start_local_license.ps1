$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$licenseRoot = Join-Path $root "license_server"
$dataRoot = Join-Path $licenseRoot "local_data"
$envPath = Join-Path $licenseRoot ".env.local"
$cardPath = Join-Path $dataRoot "first_permanent_card.txt"
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = Join-Path $root ".venv-local\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $python)) {
  throw "Python environment not found. Run setup.bat first."
}

New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null

function New-HexSecret([int] $Bytes) {
  $buffer = [byte[]]::new($Bytes)
  $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $generator.GetBytes($buffer) } finally { $generator.Dispose() }
  return ([BitConverter]::ToString($buffer) -replace '-', '').ToLowerInvariant()
}

if (-not (Test-Path -LiteralPath $envPath)) {
  $dbPath = (Join-Path $dataRoot "license.db").Replace('\', '/')
  $adminPassword = "Local-" + (New-HexSecret 10)
  @(
    "ENVIRONMENT=development"
    "DATABASE_URL=sqlite:///$dbPath"
    "JWT_SECRET=$(New-HexSecret 32)"
    "CARD_HASH_PEPPER=$(New-HexSecret 32)"
    "SIGNING_KEY_PATH=$(Join-Path $dataRoot 'license_ed25519.pem')"
    "SIGNING_KEY_ID=local-license-key-2026"
    "BOOTSTRAP_ADMIN_USERNAME=admin"
    "BOOTSTRAP_ADMIN_PASSWORD=$adminPassword"
    "ADMIN_TOKEN_MINUTES=480"
    "REFRESH_TOKEN_DAYS=3650"
    "DEFAULT_OFFLINE_GRACE_HOURS=72"
  ) | Set-Content -LiteralPath $envPath -Encoding ascii
  Write-Host "Local admin credentials were generated and saved to: $envPath"
  Write-Host "Admin username: admin"
  Write-Host "Admin password: $adminPassword"
}

foreach ($line in Get-Content -LiteralPath $envPath) {
  if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
  $parts = $line -split '=', 2
  [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1], 'Process')
}

$healthUrl = "http://127.0.0.1:8088/api/health"
$healthy = $false
try {
  $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
  $healthy = ($health.status -eq "ok")
} catch { }

if (-not $healthy) {
  Start-Process -FilePath $python -ArgumentList @(
    "-m", "uvicorn", "app.main:create_app", "--factory",
    "--host", "127.0.0.1", "--port", "8088"
  ) -WorkingDirectory $licenseRoot -WindowStyle Hidden | Out-Null
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
      $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
      if ($health.status -eq "ok") { $healthy = $true; break }
    } catch { }
  }
}
if (-not $healthy) { throw "Local license service did not become healthy at $healthUrl" }

if (-not (Test-Path -LiteralPath $cardPath)) {
  try {
    $loginBody = @{ username = $env:BOOTSTRAP_ADMIN_USERNAME; password = $env:BOOTSTRAP_ADMIN_PASSWORD } | ConvertTo-Json
    $login = Invoke-RestMethod -Uri "http://127.0.0.1:8088/api/admin/login" -Method Post -ContentType "application/json" -Body $loginBody
    $headers = @{ Authorization = "Bearer $($login.access_token)" }
    $cardBody = @{ plan_type = "permanent"; count = 1; device_limit = 1; offline_grace_hours = 72; channel = "local-development" } | ConvertTo-Json
    $generated = Invoke-RestMethod -Uri "http://127.0.0.1:8088/api/admin/cards/generate" -Method Post -Headers $headers -ContentType "application/json" -Body $cardBody
    $generated.codes[0] | Set-Content -LiteralPath $cardPath -Encoding ascii
    Write-Host "Local permanent activation card saved to: $cardPath"
  } catch {
    Write-Warning "Could not generate the local bootstrap card: $($_.Exception.Message)"
  }
}

Write-Host "Local license API is ready at http://127.0.0.1:8088"
