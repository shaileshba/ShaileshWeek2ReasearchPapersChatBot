$ErrorActionPreference = 'Stop'
$backendPython = Join-Path $PSScriptRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $backendPython)) { throw 'Install the backend dependencies first; see README.md.' }
& $backendPython -m uvicorn app.main:app --app-dir (Join-Path $PSScriptRoot 'backend') --host 127.0.0.1 --port 8000
