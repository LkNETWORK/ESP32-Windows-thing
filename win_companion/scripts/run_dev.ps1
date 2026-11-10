# Start the companion in the foreground with console logs.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found. Create it and install requirements-dev.txt first."
}

& $python app.py --console
exit $LASTEXITCODE
