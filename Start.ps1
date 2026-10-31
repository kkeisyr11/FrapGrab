param([switch]$Source, [switch]$Setup, [switch]$Build)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$releaseExe = Join-Path $projectRoot 'dist\FrapGrab\FrapGrab.exe'
if ((Test-Path -LiteralPath $releaseExe) -and -not ($Source -or $Setup -or $Build)) {
    Start-Process -FilePath $releaseExe -WorkingDirectory $projectRoot
    exit 0
}
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Potrzebny Python 3.12 (64-bit).' }
    $Setup = $true
}
if ($Setup) {
    & $venvPython -m pip install -r (Join-Path $projectRoot 'requirements-build.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Nie udało się przygotować zależności.' }
}
Push-Location $projectRoot
try {
    if ($Build) {
        & $venvPython (Join-Path $projectRoot 'build_exe.py')
    } elseif (-not $Setup -or $Source) {
        & $venvPython (Join-Path $projectRoot 'main.py')
    }
} finally { Pop-Location }
