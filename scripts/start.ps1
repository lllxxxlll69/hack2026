$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
if (-not (Test-Path -LiteralPath '.env')) { & '.\.venv\Scripts\python.exe' 'scripts\setup.py' }
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop and retry.' }
& '.\.venv\Scripts\python.exe' -m desktop.main
