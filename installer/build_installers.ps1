param(
    [switch] $SkipApplicationBuild
)

$ErrorActionPreference = "Stop"
$installerRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $installerRoot
$pythonCandidates = @(
    (Join-Path $repoRoot ".venv\Scripts\python.exe"),
    (Join-Path $repoRoot ".venv-local\Scripts\python.exe")
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$isccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $iscc) {
    throw "Inno Setup 6 is required. Install package JRSoftware.InnoSetup first."
}
if (-not $python) {
    throw "Python environment not found. Run client\setup.bat first."
}

& $python -m pip install -r (Join-Path $installerRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Installer build dependency installation failed." }
& $python (Join-Path $installerRoot "render_icons.py")
if ($LASTEXITCODE -ne 0) { throw "Logo rendering failed." }

$requiredIcons = @(
    (Join-Path $installerRoot "assets\client-icon.ico"),
    (Join-Path $installerRoot "assets\admin-icon.ico")
)
foreach ($icon in $requiredIcons) {
    if (-not (Test-Path -LiteralPath $icon)) {
        throw "Installer icon is missing: $icon"
    }
}

if (-not $SkipApplicationBuild) {
    Push-Location (Join-Path $repoRoot "client")
    try {
        & $python -m PyInstaller yuncomfyui.spec --clean --noconfirm
        if ($LASTEXITCODE -ne 0) { throw "Client packaging failed." }
    } finally {
        Pop-Location
    }

    Push-Location (Join-Path $repoRoot "admin")
    try {
        & $python -m PyInstaller admin.spec --clean --noconfirm
        if ($LASTEXITCODE -ne 0) { throw "Admin packaging failed." }
    } finally {
        Pop-Location
    }
}

& $iscc (Join-Path $installerRoot "client.iss")
if ($LASTEXITCODE -ne 0) { throw "Client installer build failed." }
& $iscc (Join-Path $installerRoot "admin.iss")
if ($LASTEXITCODE -ne 0) { throw "Admin installer build failed." }

Write-Host "Installers are ready in: $(Join-Path $installerRoot 'output')"
